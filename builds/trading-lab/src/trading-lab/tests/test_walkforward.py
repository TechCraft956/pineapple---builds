"""Tests for lab.ml.walkforward: non-overlapping folds, purge, embargo, and
the final-holdout single-use guard."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.ml.datasets import Dataset
from lab.ml.walkforward import WalkForwardSplitter, final_holdout


def _dataset(ts: pd.DatetimeIndex, exit_ts: list[pd.Timestamp] | None = None) -> Dataset:
    """A minimal, fully synthetic Dataset -- enough to drive
    WalkForwardSplitter, which only reads .ts, .X, .y and .meta['exit_ts']."""
    idx = pd.DatetimeIndex(ts, name="ts")
    X = pd.DataFrame({"f": range(len(idx))}, index=idx)
    y = pd.Series([i % 2 for i in range(len(idx))], index=idx, name="y")
    exit_ts = exit_ts if exit_ts is not None else list(idx)  # same-day exit by default
    meta = pd.DataFrame({"exit_ts": exit_ts, "r": [0.0] * len(idx)}, index=idx)
    leak = pd.DataFrame(columns=["ts", "feature", "source", "max_bar_ts"])
    return Dataset(X=X, y=y, meta=meta, ts=idx, _leak_detail=leak)


def _daily(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="1D", tz="UTC") + pd.Timedelta(hours=12)


# ---------------------------------------------------------------------------
# non-overlap
# ---------------------------------------------------------------------------


def test_folds_never_overlap_in_test_rows():
    ds = _dataset(_daily(24))
    sp = WalkForwardSplitter(train="5D", test="5D", step="5D", embargo="0D")
    folds = list(sp.split(ds))
    assert len(folds) >= 2
    seen: set[pd.Timestamp] = set()
    for fold in folds:
        overlap = set(fold.test_idx) & seen
        assert not overlap, f"test rows reused across folds: {overlap}"
        seen |= set(fold.test_idx)


def test_folds_never_overlap_in_test_time_spans():
    ds = _dataset(_daily(24))
    sp = WalkForwardSplitter(train="5D", test="5D", step="5D", embargo="0D")
    folds = list(sp.split(ds))
    for a, b in zip(folds, folds[1:]):
        assert a.test_span[1] <= b.test_span[0]


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------


def test_purge_removes_train_samples_whose_outcome_reaches_into_test():
    days = _daily(12)
    # Every signal exits the same day it fires, except day-4's, whose
    # outcome resolves on day 7 -- deep inside the first fold's test window.
    exit_ts = list(days)
    long_exit_idx = 3  # day 4 (0-indexed)
    exit_ts[long_exit_idx] = days[long_exit_idx] + pd.Timedelta(days=3)  # -> day 7

    ds = _dataset(days, exit_ts=exit_ts)
    sp = WalkForwardSplitter(train="5D", test="4D", step="4D", embargo="1D")
    fold0 = next(sp.split(ds))

    assert fold0.train_span == (days[0].normalize() + pd.Timedelta(hours=12), fold0.train_span[1])
    assert days[long_exit_idx] not in fold0.train_idx, "sample whose outcome bleeds into test was not purged"
    assert fold0.n_purged >= 1
    # a same-day-exit neighbour must remain, so this isn't purging everything
    assert days[long_exit_idx - 1] in fold0.train_idx


def test_purge_is_a_noop_when_disabled():
    days = _daily(12)
    exit_ts = list(days)
    exit_ts[3] = days[3] + pd.Timedelta(days=3)
    ds = _dataset(days, exit_ts=exit_ts)

    sp_on = WalkForwardSplitter(train="5D", test="4D", step="4D", embargo="1D", purge=True)
    sp_off = WalkForwardSplitter(train="5D", test="4D", step="4D", embargo="1D", purge=False)

    fold_on = next(sp_on.split(ds))
    fold_off = next(sp_off.split(ds))

    assert fold_on.n_purged >= 1
    assert fold_off.n_purged == 0
    assert days[3] in fold_off.train_idx
    assert days[3] not in fold_on.train_idx


# ---------------------------------------------------------------------------
# embargo
# ---------------------------------------------------------------------------


def test_embargo_blocks_samples_shortly_after_an_earlier_test_window():
    """train=4D, test=4D, step=2D, embargo=1D on 14 daily signals: fold 0's
    test window is days 5-8 (ending day 9 12:00), which opens a dead zone
    (day 9 12:00, day 10 12:00). By fold 3, whose train span reaches
    forward to day 9, day 9's signal must be excluded from train by
    embargo -- not by purge (its exit_ts is same-day, nothing to purge) and
    not by the train window boundary itself (day 9 is otherwise squarely
    inside fold 3's train span)."""
    days = _daily(14)
    ds = _dataset(days)  # same-day exits everywhere: nothing for purge to remove
    sp = WalkForwardSplitter(train="4D", test="4D", step="2D", embargo="1D")
    folds = list(sp.split(ds))

    day9 = days[8]
    fold3 = folds[3]
    assert fold3.train_span[0] <= day9 < fold3.train_span[1], "test setup assumption: day 9 is inside fold 3's train span"
    assert fold3.n_purged == 0, "nothing should need purging in this same-day-exit dataset"
    assert fold3.n_embargoed >= 1
    assert day9 not in fold3.train_idx

    # fold 4 accumulates a second dead zone from fold 1's test window.
    fold4 = folds[4]
    day11 = days[10]
    assert fold4.n_embargoed >= 2
    assert day9 not in fold4.train_idx
    assert day11 not in fold4.train_idx


def test_embargo_window_has_the_configured_length():
    days = _daily(14)
    ds = _dataset(days)
    embargo_days = 2
    sp = WalkForwardSplitter(train="4D", test="4D", step="2D", embargo=f"{embargo_days}D")
    folds = list(sp.split(ds))
    fold0 = folds[0]
    test_end = fold0.test_span[1]

    # A signal exactly at test_end + embargo (i.e. just past the dead zone)
    # is eligible for a later fold's training set; one strictly inside the
    # dead zone is not. Probe both edges directly against the splitter's own
    # forbidden-zone bookkeeping via the next fold that reaches this far back.
    later = [f for f in folds if f.train_span[0] <= test_end < f.train_span[1]]
    assert later, "expected some later fold whose train span straddles the dead-zone start"
    fold = later[0]
    dead_zone_end = test_end + pd.Timedelta(days=embargo_days)
    for ts in fold.train_idx:
        assert not (test_end <= ts < dead_zone_end), f"{ts} sits inside the embargo dead zone but was kept"


# ---------------------------------------------------------------------------
# final_holdout
# ---------------------------------------------------------------------------


def test_final_holdout_splits_by_fraction_and_covers_everything_once():
    ds = _dataset(_daily(20))
    split = final_holdout(ds, 0.2, i_am_deliberately_re_using_the_holdout=True)
    assert len(split.train) + len(split.holdout) == len(ds)
    assert all(t < split.split_ts for t in split.train.ts)
    assert all(t >= split.split_ts for t in split.holdout.ts)


def test_final_holdout_raises_on_second_access_without_override():
    ds = _dataset(_daily(20), exit_ts=None)
    # Use a distinct cutoff so this test's key can't collide with another
    # test's already-touched holdout for the "same" dataset/cutoff pair.
    final_holdout(ds, 0.25)
    with pytest.raises(RuntimeError):
        final_holdout(ds, 0.25)


def test_final_holdout_second_access_allowed_with_explicit_override():
    ds = _dataset(_daily(20), exit_ts=None)
    first = final_holdout(ds, 0.3)
    second = final_holdout(ds, 0.3, i_am_deliberately_re_using_the_holdout=True)
    assert first.split_ts == second.split_ts
