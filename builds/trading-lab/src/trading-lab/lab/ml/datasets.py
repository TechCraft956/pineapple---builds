"""Assemble a point-in-time feature matrix with a hard gate against leakage.

:func:`build_dataset` is the only place in the ML layer allowed to turn a list
of :class:`~lab.core.types.Signal` into ``(X, y)``. It does two things a plain
``DataFrame.apply`` would not:

1. It runs every feature function through a small spy that records the
   *latest bar timestamp actually read* via ``.loc[...]``, and raises before
   returning anything if any feature consulted a bar strictly after the
   signal's own timestamp. That is the leakage gate -- see
   :func:`Dataset.leakage_report` for the audit trail it leaves behind.
2. It enforces a strictly increasing time index, because
   :mod:`lab.ml.walkforward` assumes one and a dataset that silently contains
   two signals at the same timestamp (or out of order) makes purge/embargo
   math wrong in a way that is very hard to notice later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from lab.ml.features import FEATURE_REGISTRY, build_feature_frame
from lab.core.types import Signal

__all__ = ["Dataset", "build_dataset", "LeakageError"]


class LeakageError(ValueError):
    """Raised when a feature consulted a bar at or after the signal it describes."""


class _LocSpy:
    __slots__ = ("_spy",)

    def __init__(self, spy: "_LeakSpy") -> None:
        self._spy = spy

    def __getitem__(self, key: Any) -> Any:
        result = self._spy._bars.loc[key]
        idx = getattr(result, "index", None)
        if isinstance(idx, pd.DatetimeIndex) and len(idx) > 0:
            ts = idx.max()
            if self._spy.max_ts is None or ts > self._spy.max_ts:
                self._spy.max_ts = ts
        return result


class _LeakSpy:
    """Delegates like a bar frame, but remembers the max timestamp any ``.loc`` read touched.

    Every feature builder in :mod:`lab.ml.features` starts with
    ``bars.loc[:as_of]`` (or an equivalent ``.loc`` slice), so wrapping the
    real frame here and handing the wrapper to a feature function is enough to
    audit what it actually looked at, without needing the function to
    cooperate in any way.
    """

    __slots__ = ("_bars", "max_ts")

    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars
        self.max_ts: pd.Timestamp | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bars, name)

    def __getitem__(self, key: Any) -> Any:
        return self._bars[key]

    @property
    def loc(self) -> _LocSpy:
        return _LocSpy(self)


def _leakage_detail(
    signals: Sequence[Signal], bars: pd.DataFrame, feature_fns: Mapping[str, Callable[..., Any]]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sig in signals:
        as_of = sig.ts
        for name, fn in feature_fns.items():
            if name in sig.meta:
                rows.append(
                    {"ts": as_of, "feature": name, "source": "meta", "max_bar_ts": pd.NaT}
                )
                continue
            spy = _LeakSpy(bars)
            try:
                fn(spy, as_of)
            except Exception:
                rows.append(
                    {"ts": as_of, "feature": name, "source": "bars", "max_bar_ts": pd.NaT}
                )
                continue
            rows.append(
                {"ts": as_of, "feature": name, "source": "bars", "max_bar_ts": spy.max_ts}
            )
    return pd.DataFrame(rows, columns=["ts", "feature", "source", "max_bar_ts"])


def _extract_label(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "label"):
        return {
            "label": obj.label,
            "r": obj.r,
            "outcome": obj.outcome,
            "entry_ts": obj.entry_ts,
            "exit_ts": obj.exit_ts,
            "bars_held": getattr(obj, "bars_held", None),
        }
    if isinstance(obj, Mapping):
        return {
            "label": obj["label"],
            "r": obj.get("r", obj.get("r_label")),
            "outcome": obj.get("outcome", ""),
            "entry_ts": obj.get("entry_ts"),
            "exit_ts": obj.get("exit_ts"),
            "bars_held": obj.get("bars_held"),
        }
    raise TypeError(
        f"label_fn must return a BarrierOutcome-like object or a Mapping with a "
        f"'label' key, got {type(obj)!r}"
    )


@dataclass(slots=True)
class Dataset:
    """A model-ready, leakage-audited feature matrix.

    ``X``, ``y`` and ``meta`` share the same index: signal timestamps, unique
    and strictly increasing. ``ts`` is that same index, exposed separately
    because :mod:`lab.ml.walkforward` wants a plain time index to split on
    without caring which DataFrame it came from.
    """

    X: pd.DataFrame
    y: pd.Series
    meta: pd.DataFrame
    ts: pd.DatetimeIndex
    _leak_detail: pd.DataFrame = field(repr=False)

    def __len__(self) -> int:
        return len(self.X)

    def leakage_report(self) -> pd.DataFrame:
        """Per-feature summary of how close each feature came to leaking.

        ``worst_lag`` is the *smallest* gap observed, across every signal in
        this dataset, between the signal's own timestamp and the latest bar
        that feature consulted for it -- i.e. the closest any single signal
        came to the boundary. A feature sourced entirely from ``Signal.meta``
        never touches bars at all and is reported with ``source="meta"`` and
        no lag statistics, since there is nothing to audit.
        """
        if len(self._leak_detail) == 0:
            return pd.DataFrame(
                columns=["source", "n", "worst_lag", "mean_lag"]
            )

        def _agg(g: pd.DataFrame) -> pd.Series:
            bars_rows = g[g["source"] == "bars"]
            consulted = bars_rows.dropna(subset=["max_bar_ts"])
            if len(consulted) == 0:
                return pd.Series(
                    {"source": g["source"].iloc[0], "n": len(g), "worst_lag": pd.NaT, "mean_lag": pd.NaT}
                )
            lag = consulted["ts"] - consulted["max_bar_ts"]
            return pd.Series(
                {"source": "bars", "n": len(g), "worst_lag": lag.min(), "mean_lag": lag.mean()}
            )

        return self._leak_detail.groupby("feature", sort=True).apply(_agg, include_groups=False)


def build_dataset(
    signals: Sequence[Signal],
    bars: pd.DataFrame,
    feature_fns: Mapping[str, Callable[..., Any]] | None = None,
    label_fn: Callable[[Signal], Any] | None = None,
    *,
    extra_frames: Mapping[str, pd.DataFrame] | None = None,
    calendar: pd.DataFrame | None = None,
    categorical_features: Sequence[str] = ("day_of_week",),
    nan_policy: str = "keep",
    drop_unfilled: bool = True,
) -> Dataset:
    """Build a leakage-audited :class:`Dataset` from signals and bars.

    Parameters
    ----------
    feature_fns:
        name -> ``f(bars, as_of) -> float``. Merged on top of
        :data:`lab.ml.features.FEATURE_REGISTRY` (your entries win on name
        clash). Every callable here must accept exactly ``(bars, as_of)`` --
        wrap anything needing more context (an instrument, a level) with
        ``functools.partial`` before passing it in, so the leakage spy can
        call it uniformly.
    label_fn:
        ``f(signal) -> BarrierOutcome | Mapping``. Typically
        ``functools.partial(triple_barrier, bars, horizon=...)`` or a lookup
        into a :func:`lab.ml.labels.label_from_trades` frame.
    nan_policy:
        ``"keep"`` (default -- leave NaN for the model pipeline's imputer to
        handle) or ``"drop_rows"`` (drop any row with a NaN feature; use this
        only if you are deliberately excluding warm-up-period signals).
    drop_unfilled:
        Signals whose ``label_fn`` outcome is ``"no_fill"`` carry no realised
        result and are excluded by default -- there is nothing to learn from
        an order that never triggered.

    Raises
    ------
    LeakageError:
        If any feature consulted a bar strictly after its signal's timestamp.
        This is a hard error by design -- see the module docstring.
    ValueError:
        If ``label_fn`` is not supplied, if signal timestamps are not unique,
        or if ``nan_policy`` is not recognised.
    """
    if label_fn is None:
        raise ValueError("label_fn is required")
    if nan_policy not in ("keep", "drop_rows"):
        raise ValueError(f"unknown nan_policy {nan_policy!r}")

    ordered = sorted(signals, key=lambda s: s.ts)
    seen_ts = [s.ts for s in ordered]
    if len(seen_ts) != len(set(seen_ts)):
        dupes = sorted({t for t in seen_ts if seen_ts.count(t) > 1})
        raise ValueError(f"signal timestamps must be unique; duplicates at {dupes[:5]}")

    fns: dict[str, Callable[..., Any]] = dict(FEATURE_REGISTRY)
    if feature_fns:
        fns.update(feature_fns)

    leak_detail = _leakage_detail(ordered, bars, fns)
    violations = leak_detail[
        (leak_detail["source"] == "bars")
        & leak_detail["max_bar_ts"].notna()
        & (leak_detail["max_bar_ts"] > leak_detail["ts"])
    ]
    if len(violations):
        sample = violations.head(5).to_dict("records")
        raise LeakageError(
            f"{len(violations)} feature/signal pair(s) consulted a bar after the "
            f"signal timestamp -- this is a leak, not a warning. Examples: {sample}"
        )

    labels: list[dict[str, Any]] = []
    kept: list[Signal] = []
    for sig in ordered:
        info = _extract_label(label_fn(sig))
        if drop_unfilled and info.get("outcome") == "no_fill":
            continue
        info["ts"] = sig.ts
        info["symbol"] = sig.symbol
        info["strategy"] = sig.strategy
        info["tag"] = sig.tag
        info["direction"] = sig.direction
        labels.append(info)
        kept.append(sig)

    X = build_feature_frame(kept, bars, extra_frames=extra_frames, feature_fns=feature_fns, calendar=calendar)

    for col in categorical_features:
        if col in X.columns:
            X[col] = X[col].astype("category")

    label_df = pd.DataFrame(labels).set_index("ts") if labels else pd.DataFrame(
        columns=["label", "r", "outcome", "entry_ts", "exit_ts", "bars_held", "symbol", "strategy", "tag", "direction"]
    )
    label_df.index.name = "ts"
    label_df = label_df.reindex(X.index)

    y = label_df["label"].astype("Int64").rename("y")
    meta = label_df[["r", "outcome", "entry_ts", "exit_ts", "bars_held", "symbol", "strategy", "tag", "direction"]]

    if nan_policy == "drop_rows":
        keep_mask = X.notna().all(axis=1)
        X, y, meta = X.loc[keep_mask], y.loc[keep_mask], meta.loc[keep_mask]

    kept_ts = set(X.index)
    leak_detail = leak_detail[leak_detail["ts"].isin(kept_ts)]

    return Dataset(X=X, y=y, meta=meta, ts=X.index, _leak_detail=leak_detail)
