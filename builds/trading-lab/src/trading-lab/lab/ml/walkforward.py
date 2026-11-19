"""Walk-forward splitting with purge and embargo, and a holdout that resists reuse.

Why purge and embargo matter here specifically: a signal's label is not known
at its own timestamp -- it is only known once its outcome window resolves
(``triple_barrier``'s horizon, or a trade's actual exit). A training sample
whose outcome resolves *inside* the test window has, in effect, leaked test-set
information into training (the label was partly determined by the same price
action the test set is being scored on). :meth:`WalkForwardSplitter.split`
purges those samples out of train. Embargo goes one step further: because nearby
bars are serially correlated, it also refuses to let samples from shortly after
a test window ever re-enter training in a *later* fold, even though they are
chronologically "before" that later fold's own test window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd

from lab.ml.datasets import Dataset

__all__ = ["Fold", "WalkForwardSplitter", "HoldoutSplit", "final_holdout"]


@dataclass(frozen=True, slots=True)
class Fold:
    """One walk-forward split. Indices are the actual signal timestamps, so a
    caller does ``dataset.X.loc[fold.train_idx]`` directly."""

    train_idx: pd.DatetimeIndex
    test_idx: pd.DatetimeIndex
    train_span: tuple[pd.Timestamp, pd.Timestamp]
    test_span: tuple[pd.Timestamp, pd.Timestamp]
    n_purged: int = 0
    n_embargoed: int = 0


@dataclass(frozen=True, slots=True)
class WalkForwardSplitter:
    """Rolling train/test windows over a :class:`~lab.ml.datasets.Dataset`.

    ``train``, ``test``, ``step`` and ``embargo`` are pandas offset-alias
    strings (``"365D"``, ``"90D"``, ...). The window is a fixed-length rolling
    window (not expanding) so every fold trains on a comparable amount of
    history -- an expanding window would make the model progressively slower
    to adapt to regime change and would make fold-to-fold comparisons of
    expectancy unfair.
    """

    train: str = "365D"
    test: str = "90D"
    step: str = "90D"
    embargo: str = "1D"
    purge: bool = True

    def split(self, dataset: Dataset) -> Iterator[Fold]:
        ts = dataset.ts
        if len(ts) == 0:
            return
        if not ts.is_monotonic_increasing:
            raise ValueError("dataset.ts must be sorted increasing")

        exit_ts = dataset.meta["exit_ts"]
        train_td = pd.Timedelta(self.train)
        test_td = pd.Timedelta(self.test)
        step_td = pd.Timedelta(self.step)
        embargo_td = pd.Timedelta(self.embargo)

        cur_train_start = ts.min()
        data_end = ts.max()
        # Dead zones opened by embargo on *earlier* folds' test windows -- once
        # opened they stay forbidden to training for the rest of the walk, not
        # just for the fold that created them.
        forbidden: list[tuple[pd.Timestamp, pd.Timestamp]] = []

        while True:
            train_end = cur_train_start + train_td
            test_start = train_end
            test_end = test_start + test_td
            if test_start > data_end:
                break

            train_mask = (ts >= cur_train_start) & (ts < train_end)
            test_mask = (ts >= test_start) & (ts < test_end)
            if test_mask.sum() == 0:
                break

            n_purged = 0
            if self.purge:
                bleeds_into_test = train_mask & exit_ts.notna().to_numpy() & (exit_ts >= test_start).to_numpy()
                n_purged = int(bleeds_into_test.sum())
                train_mask = train_mask & ~bleeds_into_test

            n_embargoed = 0
            for fs, fe in forbidden:
                hit = train_mask & (ts >= fs) & (ts < fe)
                n_embargoed += int(hit.sum())
                train_mask = train_mask & ~hit

            yield Fold(
                train_idx=ts[train_mask],
                test_idx=ts[test_mask],
                train_span=(cur_train_start, train_end),
                test_span=(test_start, test_end),
                n_purged=n_purged,
                n_embargoed=n_embargoed,
            )

            forbidden.append((test_end, test_end + embargo_td))
            cur_train_start = cur_train_start + step_td


@dataclass(frozen=True, slots=True)
class HoldoutSplit:
    train: Dataset
    holdout: Dataset
    split_ts: pd.Timestamp


_HOLDOUT_TOUCHED: set[tuple] = set()


def _slice_dataset(dataset: Dataset, mask: pd.Series) -> Dataset:
    kept_ts = dataset.X.index[mask.to_numpy()]
    leak = dataset._leak_detail[dataset._leak_detail["ts"].isin(set(kept_ts))]
    return Dataset(
        X=dataset.X.loc[mask.to_numpy()],
        y=dataset.y.loc[mask.to_numpy()],
        meta=dataset.meta.loc[mask.to_numpy()],
        ts=kept_ts,
        _leak_detail=leak,
    )


def final_holdout(
    dataset: Dataset,
    fraction_or_date: float | str | pd.Timestamp,
    *,
    i_am_deliberately_re_using_the_holdout: bool = False,
) -> HoldoutSplit:
    """Carve off the untouched final slice of ``dataset``, exactly once per process.

    ``fraction_or_date`` is either a fraction in ``(0, 1)`` of the dataset's
    time span reserved for holdout (e.g. ``0.2`` for the most recent 20%), or
    an explicit cutoff timestamp/date -- everything at or after it becomes the
    holdout.

    Calling this a second time for the same dataset and cutoff raises
    :class:`RuntimeError` unless ``i_am_deliberately_re_using_the_holdout=True``
    is passed explicitly. This is deliberately annoying: a holdout you can
    re-touch after looking at the model's performance on it is not a holdout,
    it is one more fold you will unconsciously overfit to by trying again.
    (Python does not allow a hyphen in a keyword argument, hence the
    underscored name in place of the prose in the spec.)
    """
    if isinstance(fraction_or_date, (int, float)):
        frac = float(fraction_or_date)
        if not 0.0 < frac < 1.0:
            raise ValueError("fraction must be strictly between 0 and 1")
        n = len(dataset.ts)
        if n == 0:
            raise ValueError("cannot take a holdout from an empty dataset")
        split_pos = max(0, min(n - 1, int(round(n * (1.0 - frac)))))
        split_ts = dataset.ts[split_pos]
    else:
        split_ts = pd.Timestamp(fraction_or_date)
        if split_ts.tzinfo is None:
            split_ts = split_ts.tz_localize("UTC")

    key = (id(dataset), len(dataset.ts), str(dataset.ts.min()) if len(dataset.ts) else "", str(fraction_or_date))
    if key in _HOLDOUT_TOUCHED and not i_am_deliberately_re_using_the_holdout:
        raise RuntimeError(
            "final_holdout() was already called for this dataset/cutoff in this "
            "process. Re-accessing the holdout after having seen it defeats the "
            "point of an untouched out-of-sample period. If you are certain this "
            "is not p-hacking (e.g. a genuinely fresh process, or a deliberate "
            "final check before shipping), pass "
            "i_am_deliberately_re_using_the_holdout=True."
        )
    _HOLDOUT_TOUCHED.add(key)

    train_mask = dataset.ts < split_ts
    holdout_mask = ~train_mask
    return HoldoutSplit(
        train=_slice_dataset(dataset, pd.Series(train_mask, index=dataset.ts)),
        holdout=_slice_dataset(dataset, pd.Series(holdout_mask, index=dataset.ts)),
        split_ts=split_ts,
    )
