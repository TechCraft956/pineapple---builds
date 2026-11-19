"""Tests for lab.data.continuity: rollover-gap detection on a synthetically
stitched series, back-adjustment inference from negative prices, and the
manual-check sampler."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.core.instruments import get_instrument
from lab.data.continuity import analyse_continuity, sample_for_manual_check


def _daily_bars(start: str, end: str, *, price0: float = 5000.0, seed: int = 7) -> pd.DataFrame:
    """A quiet one-bar-per-trading-day series: small deterministic wobble,
    no gaps, nothing that should trip the roll detector on its own."""
    days = pd.bdate_range(start, end) + pd.Timedelta(hours=14, minutes=30)  # ~RTH open, UTC
    idx = pd.DatetimeIndex(days).tz_localize("UTC")
    rng = np.random.default_rng(seed)
    n = len(idx)
    steps = rng.normal(0, 0.3, size=n)
    closes = price0 + np.cumsum(steps)
    opens = closes - rng.normal(0, 0.1, size=n)
    highs = np.maximum(opens, closes) + 0.5
    lows = np.minimum(opens, closes) - 0.5
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": 1000.0}, index=idx
    )
    df.index.name = "ts"
    return df


def _inject_roll_gap(df: pd.DataFrame, roll_date: str, jump: float) -> pd.DataFrame:
    """Shift every bar at/after `roll_date` by `jump` price units -- a single
    permanent discontinuity, exactly what a raw front/back contract splice
    looks like: one jump, then business as usual from the new level."""
    out = df.copy()
    mask = out.index.date >= pd.Timestamp(roll_date).date()
    out.loc[mask, ["open", "high", "low", "close"]] += jump
    return out


ES = get_instrument("ES")


def test_quiet_series_has_no_roll_candidates() -> None:
    df = _daily_bars("2024-01-02", "2024-06-28")
    report = analyse_continuity(df, ES)
    assert report.roll_events == ()
    assert not report.has_negative_prices
    # under one quarterly cycle from Jan-Jun is actually >1 cycle (Jan->Mar,
    # Mar->Jun) so a clean read here should lean toward "no visible rolls
    # despite spanning a cycle", not "single expiry".
    assert report.verdict in ("likely_continuous_backadjusted", "likely_single_expiry")


def test_detects_stitched_roll_gap_near_quarterly_expiry() -> None:
    df = _daily_bars("2024-01-02", "2024-06-28")
    roll_date = "2024-03-15"  # March: a standard equity-index expiry month
    df = _inject_roll_gap(df, roll_date, jump=50.0)  # ~200 ticks, far past noise

    report = analyse_continuity(df, ES)

    assert len(report.roll_events) == 1
    ev = report.roll_events[0]
    assert ev.trading_day == pd.Timestamp(roll_date).date()
    assert ev.gap == pytest.approx(50.0, abs=1.0)
    assert ev.near_expiry_cycle is True
    assert ev.month == 3
    assert report.verdict == "likely_continuous_stitched_raw"
    assert report.confidence > 0.5
    assert any("stitched" in w for w in report.warnings)


def test_gap_far_from_expiry_cycle_is_unclear() -> None:
    # CL (commodity) treats every month as plausible, so use ES and roll on a
    # date nowhere near March/June/September/December to get an "off cycle" read.
    df = _daily_bars("2024-01-02", "2024-06-28")
    df = _inject_roll_gap(df, "2024-02-06", jump=50.0)  # February: off the quarterly cycle
    report = analyse_continuity(df, ES)
    assert len(report.roll_events) == 1
    assert report.roll_events[0].near_expiry_cycle is False
    assert report.verdict == "unclear"


def test_negative_prices_are_flagged_as_backadjustment_artefact() -> None:
    df = _daily_bars("2024-01-02", "2024-06-28", price0=30.0)
    # simulate a cumulative back-adjustment offset dragging early history
    # below zero -- the one unambiguous tell mentioned in the module docs.
    df = _inject_roll_gap(df.iloc[:1], "2024-01-02", jump=0.0)  # no-op, keep df var
    df = df.copy()
    early = df.index.date <= pd.Timestamp("2024-02-01").date()
    df.loc[early, ["open", "high", "low", "close"]] -= 60.0

    report = analyse_continuity(df, ES)

    assert report.has_negative_prices is True
    assert report.n_negative_bars > 0
    assert report.verdict == "likely_continuous_backadjusted"
    assert report.confidence >= 0.8
    assert any("back-adjust" in w or "back adjust" in w for w in report.warnings)


def test_consistent_sign_offsets_flag_needs_at_least_two_rolls() -> None:
    df = _daily_bars("2024-01-02", "2024-12-31")
    df = _inject_roll_gap(df, "2024-03-15", jump=50.0)
    df = _inject_roll_gap(df, "2024-06-21", jump=45.0)  # same sign as the March roll
    report = analyse_continuity(df, ES)
    assert len(report.roll_events) == 2
    assert report.consistent_sign_offsets is True

    df2 = _daily_bars("2024-01-02", "2024-12-31")
    df2 = _inject_roll_gap(df2, "2024-03-15", jump=50.0)
    df2 = _inject_roll_gap(df2, "2024-06-21", jump=-45.0)  # opposite sign
    report2 = analyse_continuity(df2, ES)
    assert len(report2.roll_events) == 2
    assert report2.consistent_sign_offsets is False


def test_empty_frame_is_insufficient_data() -> None:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty.index = pd.DatetimeIndex([], tz="UTC", name="ts")
    report = analyse_continuity(empty, ES)
    assert report.verdict == "insufficient_data"
    assert report.n_bars == 0


def test_sample_for_manual_check_always_includes_roll_candidates() -> None:
    df = _daily_bars("2024-01-02", "2024-06-28")
    roll_date = "2024-03-15"
    df = _inject_roll_gap(df, roll_date, jump=50.0)

    sample = sample_for_manual_check(df, n=5, seed=42, instrument=ES)

    assert len(sample) >= 5
    roll_rows = sample[sample["kind"] == "roll_candidate"]
    assert len(roll_rows) == 1
    assert roll_rows.iloc[0]["trading_day"] == pd.Timestamp(roll_date).date()
    assert (sample["kind"].isin(["roll_candidate", "random_sample"])).all()
    assert sample["trading_day"].is_monotonic_increasing


def test_sample_for_manual_check_without_instrument_is_pure_random() -> None:
    df = _daily_bars("2024-01-02", "2024-03-01")
    sample = sample_for_manual_check(df, n=4, seed=1)
    assert len(sample) == 4
    assert (sample["kind"] == "random_sample").all()
