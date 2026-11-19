"""Tests for lab.ml.features and the leakage gate in lab.ml.datasets.

The single most important test in this file (and arguably in the whole ML
layer) is `test_features_are_bit_identical_before_and_after_future_bars`:
every feature builder must be structurally incapable of seeing a bar that
had not printed yet at decision time, and the only trustworthy way to check
that is to actually append future bars and recompute.
"""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd
import pytest

from lab.core.types import LONG, Signal
from lab.ml.datasets import LeakageError, build_dataset
from lab.ml.features import (
    FEATURE_REGISTRY,
    build_feature_frame,
    dist_to_prior_day_high_atr,
    sweep_depth_ticks,
)
from lab.ml.labels import triple_barrier


def _bars(start: str = "2024-01-01", days: int = 6, seed: int = 3) -> pd.DataFrame:
    """Continuous 1-minute bars over `days` full calendar days, UTC, with a
    deterministic random walk and non-trivial volume -- enough history for
    ATR/session/volume-relative features to have real values partway through."""
    idx = pd.date_range(start, periods=days * 24 * 60, freq="1min", tz="UTC")
    rng = np.random.default_rng(seed)
    n = len(idx)
    steps = rng.normal(0, 0.15, size=n)
    close = 5000.0 + np.cumsum(steps)
    open_ = close - rng.normal(0, 0.05, size=n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.1, size=n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.1, size=n))
    volume = rng.integers(50, 500, size=n).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    df.index.name = "ts"
    return df


def _signal(ts: pd.Timestamp, entry: float, **kw) -> Signal:
    kw.setdefault("direction", LONG)
    kw.setdefault("stop", entry - 5.0)
    kw.setdefault("symbol", "ES")
    kw.setdefault("strategy", "test_strategy")
    kw.setdefault("tag", "test")
    return Signal(ts=ts, entry=entry, **kw)


BARS = _bars()
# An as_of timestamp with several days of warm-up history behind it and
# several days of "future" ahead of it to append.
AS_OF = BARS.index[3 * 24 * 60 + 137]  # day 4, 02:17 UTC


# ---------------------------------------------------------------------------
# the leakage test
# ---------------------------------------------------------------------------


def test_features_are_bit_identical_before_and_after_future_bars():
    """Compute every registered feature at AS_OF, append future bars the
    strategy could not have seen, recompute, and assert bit-identical
    values. This is the actual contract every feature builder promises."""
    bars_before = BARS.loc[:AS_OF]
    sig = _signal(AS_OF, entry=float(bars_before["close"].iloc[-1]))

    frame_before = build_feature_frame([sig], bars_before)
    frame_after = build_feature_frame([sig], BARS)  # BARS has ~2 extra days past AS_OF

    assert list(frame_before.columns) == list(frame_after.columns)
    for col in frame_before.columns:
        before_val = frame_before[col].iloc[0]
        after_val = frame_after[col].iloc[0]
        if isinstance(before_val, float) and np.isnan(before_val):
            assert isinstance(after_val, float) and np.isnan(after_val), f"{col} changed from NaN"
        else:
            assert before_val == after_val, f"feature {col!r} leaked: {before_val!r} -> {after_val!r}"


def test_features_bit_identical_with_bars_truncated_exactly_at_as_of():
    """Same idea, but comparing 'bars that stop exactly at as_of' (what a
    live system would actually have) against 'the full historical frame' --
    the two must agree, since a feature is only allowed to use bars up to
    and including as_of either way."""
    sig = _signal(AS_OF, entry=float(BARS.loc[:AS_OF]["close"].iloc[-1]))
    truncated = build_feature_frame([sig], BARS.loc[:AS_OF])
    full = build_feature_frame([sig], BARS)
    pd.testing.assert_frame_equal(truncated, full, check_dtype=False)


@pytest.mark.parametrize("name", sorted(FEATURE_REGISTRY))
def test_each_registry_feature_individually_ignores_future_bars(name):
    """Belt-and-suspenders: exercise each builder directly (not just through
    build_feature_frame), so a future refactor of the registry can't
    accidentally hide a leak behind aggregate-frame comparison."""
    fn = FEATURE_REGISTRY[name]
    before = fn(BARS.loc[:AS_OF], AS_OF)
    after = fn(BARS, AS_OF)
    if isinstance(before, float) and np.isnan(before):
        assert isinstance(after, float) and np.isnan(after)
    else:
        assert before == after, f"{name} leaked: {before!r} -> {after!r}"


def test_sweep_depth_ticks_ignores_future_bars():
    from lab.core.instruments import get_instrument

    inst = get_instrument("ES")
    level = float(BARS.loc[:AS_OF]["low"].iloc[-5])
    before = sweep_depth_ticks(BARS.loc[:AS_OF], AS_OF, level, LONG, inst, lookback=10)
    after = sweep_depth_ticks(BARS, AS_OF, level, LONG, inst, lookback=10)
    assert before == after


def test_dist_to_prior_day_high_atr_ignores_future_bars():
    before = dist_to_prior_day_high_atr(BARS.loc[:AS_OF], AS_OF, "ES")
    after = dist_to_prior_day_high_atr(BARS, AS_OF, "ES")
    assert before == after


# ---------------------------------------------------------------------------
# build_dataset's leakage_report / hard-error gate
# ---------------------------------------------------------------------------


def _signals_over(bars: pd.DataFrame, n: int = 12, step_minutes: int = 90) -> list[Signal]:
    start_i = 2 * 24 * 60  # leave two days of warm-up
    out = []
    for i in range(n):
        ts = bars.index[start_i + i * step_minutes]
        entry = float(bars.loc[:ts]["close"].iloc[-1])
        out.append(_signal(ts, entry=entry, tag=f"s{i}"))
    return out


def test_build_dataset_leakage_report_is_clean_for_honest_features():
    bars = BARS
    signals = _signals_over(bars)
    label_fn = functools.partial(triple_barrier, bars, horizon=pd.Timedelta("4h"))
    ds = build_dataset(signals, bars, label_fn=label_fn)
    report = ds.leakage_report()
    # every worst_lag (signal_ts - latest bar consulted) must be >= 0: the
    # latest bar any feature touched is never after its own signal.
    bars_rows = report[report["source"] == "bars"]
    assert (bars_rows["worst_lag"].dropna() >= pd.Timedelta(0)).all()


def test_build_dataset_raises_on_a_planted_lookahead_feature():
    """A feature that deliberately reads forward via `.loc` must be caught
    as a hard LeakageError, not silently accepted or merely logged."""

    def leaky_feature(bars: pd.DataFrame, as_of: pd.Timestamp) -> float:
        # Deliberately reads *forward* from as_of -- the leak this module
        # exists to catch.
        future = bars.loc[as_of:]
        return float(future["close"].iloc[-1]) if len(future) else float("nan")

    bars = BARS
    signals = _signals_over(bars, n=3)
    label_fn = functools.partial(triple_barrier, bars, horizon=pd.Timedelta("4h"))

    with pytest.raises(LeakageError):
        build_dataset(signals, bars, feature_fns={"leaky": leaky_feature}, label_fn=label_fn)


def test_build_dataset_does_not_raise_when_leaky_feature_only_reads_up_to_as_of():
    """Sanity check on the gate itself: a feature that *looks* similar but
    correctly stops at as_of must not trip the detector."""

    def honest_feature(bars: pd.DataFrame, as_of: pd.Timestamp) -> float:
        past = bars.loc[:as_of]
        return float(past["close"].iloc[-1])

    bars = BARS
    signals = _signals_over(bars, n=3)
    label_fn = functools.partial(triple_barrier, bars, horizon=pd.Timedelta("4h"))

    ds = build_dataset(signals, bars, feature_fns={"honest": honest_feature}, label_fn=label_fn)
    assert "honest" in ds.X.columns
