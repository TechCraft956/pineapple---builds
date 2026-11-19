"""Point-in-time feature builders for the probability-gate model.

Every builder in this module has the signature ``f(bars, as_of, ...)`` and the
*first* thing it does is ``bars.loc[:as_of]`` -- so a feature is structurally
incapable of seeing a bar that had not printed yet at decision time. This is
not a style preference: the leakage test in ``tests/test_ml_features.py``
appends future bars to a frame and asserts every feature value is bit-identical
before and after, and that test is the actual contract, not this docstring.

The model here never predicts direction. Every feature answers some flavour of
"given that the setup has already fired, what does the tape look like right
now" -- range context, location, time, and correlated confirmation. None of
them are allowed to encode the outcome of the trade itself.

Preferring ``Signal.meta`` over recomputing
--------------------------------------------
A strategy records the values it actually acted on (Asia range, ATR, VWAP
distance, ...) in :attr:`lab.core.types.Signal.meta` at the moment it decided
to trade. That recorded value is the *true* decision-time value -- it reflects
exactly what the strategy saw, including any strategy-specific rounding or
session-boundary choice. Recomputing from bars here is a fallback for signals
whose strategy did not record a given field, not the preferred path. See
:func:`build_feature_frame`.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from lab.core.instruments import Instrument, get_instrument
from lab.core.sessions import (
    ASIA,
    CME_TZ,
    NY_RTH,
    OVERNIGHT,
    SessionWindow,
    slice_window,
    trading_day,
    window_bounds,
)
from lab.core.types import LONG, Direction, Signal

__all__ = [
    "atr",
    "atr_percentile",
    "asia_range_size",
    "asia_range_percentile",
    "overnight_realised_vol",
    "session_vwap",
    "vwap_distance_atr",
    "sweep_depth_ticks",
    "minutes_since_session_open",
    "time_of_day_cyclical",
    "opening_gap",
    "volume_relative_to_tod",
    "dist_to_prior_day_high_atr",
    "dist_to_prior_day_low_atr",
    "minutes_to_next_release",
    "correlated_instrument_move",
    "day_of_week",
    "FEATURE_REGISTRY",
    "build_feature_frame",
]


def _asof(bars: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """The only correct way to look at ``bars`` from inside a feature builder.

    Every builder below calls this (or ``bars.loc[:as_of]`` directly) as its
    very first line. Centralising it here means the "as_of must be
    tz-aware / bars must already be validated" checks live in one place.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    return bars.loc[:as_of]


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(bars: pd.DataFrame, as_of: pd.Timestamp, window: int = 14) -> float:
    """Average true range as of ``as_of``, in price units. NaN if not enough history."""
    b = _asof(bars, as_of)
    if len(b) < window + 1:
        return float("nan")
    tr = _true_range(b)
    return float(tr.rolling(window, min_periods=window).mean().iloc[-1])


def atr_percentile(
    bars: pd.DataFrame, as_of: pd.Timestamp, window: int = 14, lookback: int = 200
) -> float:
    """Percentile rank (0-1) of the current ATR within its trailing ``lookback`` values."""
    b = _asof(bars, as_of)
    if len(b) < window + 2:
        return float("nan")
    tr = _true_range(b)
    atr_series = tr.rolling(window, min_periods=window).mean().dropna()
    if len(atr_series) < 2:
        return float("nan")
    recent = atr_series.iloc[-lookback:]
    current = recent.iloc[-1]
    return float((recent <= current).mean())


def asia_range_size(bars: pd.DataFrame, as_of: pd.Timestamp) -> float:
    """High-low of the Asia session belonging to ``as_of``'s trading day.

    If ``as_of`` falls before the Asia session for its trading day has
    finished (or started), this reflects only the portion observed so far --
    which is the correct, non-leaking answer to "what do I know about today's
    Asia range right now."
    """
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    day = trading_day(as_of)
    win = slice_window(b, ASIA, day)
    if len(win) == 0:
        return float("nan")
    return float(win["high"].max() - win["low"].min())


def asia_range_percentile(
    bars: pd.DataFrame, as_of: pd.Timestamp, lookback_days: int = 20
) -> float:
    """Percentile of today's (possibly partial) Asia range vs the trailing N sessions."""
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    day = trading_day(as_of)
    days = pd.unique(trading_day(b.index))
    days = sorted(d for d in days if d <= day)
    ranges: list[float] = []
    for d in days[-(lookback_days + 1) :]:
        win = slice_window(b, ASIA, d)
        if len(win) > 0:
            ranges.append(float(win["high"].max() - win["low"].min()))
    if len(ranges) < 2:
        return float("nan")
    current = ranges[-1]
    hist = ranges[-lookback_days:]
    return float((pd.Series(hist) <= current).mean())


def overnight_realised_vol(bars: pd.DataFrame, as_of: pd.Timestamp) -> float:
    """Stdev of log returns over the overnight session belonging to ``as_of``."""
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    day = trading_day(as_of)
    win = slice_window(b, OVERNIGHT, day)
    if len(win) < 3:
        return float("nan")
    rets = np.log(win["close"] / win["close"].shift(1)).dropna()
    if len(rets) < 2:
        return float("nan")
    return float(rets.std())


def session_vwap(bars: pd.DataFrame, as_of: pd.Timestamp, session: SessionWindow = NY_RTH) -> float:
    """Volume-weighted average price of ``session`` up to ``as_of``, this trading day."""
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    day = trading_day(as_of)
    win = slice_window(b, session, day)
    if len(win) == 0:
        return float("nan")
    typical = (win["high"] + win["low"] + win["close"]) / 3.0
    vol = win["volume"].fillna(0.0)
    if vol.sum() <= 0:
        return float(typical.mean())
    return float((typical * vol).sum() / vol.sum())


def vwap_distance_atr(
    bars: pd.DataFrame,
    as_of: pd.Timestamp,
    session: SessionWindow = NY_RTH,
    atr_window: int = 14,
) -> float:
    """(last close - session VWAP) / ATR. Positive means trading above VWAP."""
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    vwap = session_vwap(bars, as_of, session)
    a = atr(bars, as_of, atr_window)
    if math.isnan(vwap) or math.isnan(a) or a == 0:
        return float("nan")
    return float((b["close"].iloc[-1] - vwap) / a)


def sweep_depth_ticks(
    bars: pd.DataFrame,
    as_of: pd.Timestamp,
    level: float,
    direction: Direction,
    instrument: Instrument,
    lookback: int = 1,
) -> float:
    """How far, in ticks, price traded beyond ``level`` in the ``lookback`` bars up to ``as_of``.

    ``direction`` is the direction of the *intended trade*: LONG means the
    setup is a sweep of a low (support swept, then a long reversal), so depth
    is measured below ``level``; SHORT is the mirror image above ``level``.
    Zero if the level was never actually swept.
    """
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    win = b.iloc[-lookback:]
    if direction == LONG:
        extreme = float(win["low"].min())
        depth = max(0.0, level - extreme)
    else:
        extreme = float(win["high"].max())
        depth = max(0.0, extreme - level)
    return instrument.ticks(depth)


def minutes_since_session_open(
    bars: pd.DataFrame, as_of: pd.Timestamp, session: SessionWindow = NY_RTH
) -> float:
    """Minutes elapsed since ``session`` opened on ``as_of``'s trading day.

    NaN if the session has not started yet relative to ``as_of``. Does not
    need to touch bars at all -- session boundaries are a schedule, not
    market data -- but takes ``bars`` for signature uniformity with the rest
    of this module.
    """
    del bars  # unused: session clock is schedule, not price data
    day = trading_day(as_of)
    start, _end = window_bounds(session, day)
    if as_of < start:
        return float("nan")
    return float((as_of - start).total_seconds() / 60.0)


def time_of_day_cyclical(
    bars: pd.DataFrame, as_of: pd.Timestamp, tz: str = CME_TZ
) -> tuple[float, float]:
    """(sin, cos) encoding of time-of-day in ``tz``, period 24h.

    Cyclical encoding avoids the discontinuity a raw "minutes since midnight"
    feature would have at the day boundary (23:59 and 00:00 are adjacent in
    reality but maximally far apart as a raw number).
    """
    del bars  # unused: clock time only
    local = as_of.tz_convert(tz)
    minutes = local.hour * 60 + local.minute + local.second / 60.0
    frac = minutes / (24 * 60)
    return float(np.sin(2 * np.pi * frac)), float(np.cos(2 * np.pi * frac))


def opening_gap(bars: pd.DataFrame, as_of: pd.Timestamp, session: SessionWindow = NY_RTH) -> float:
    """(session open - prior trading day's close), in price units.

    Only meaningful once the session has actually opened; NaN otherwise, so a
    signal fired before the open never gets a fabricated gap value.
    """
    from lab.core.sessions import prior_day_levels  # local import: avoid cycle risk

    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    day = trading_day(as_of)
    win = slice_window(b, session, day)
    if len(win) == 0:
        return float("nan")
    prior = prior_day_levels(b, day)
    if prior is None:
        return float("nan")
    return float(win["open"].iloc[0] - prior["close"])


def volume_relative_to_tod(
    bars: pd.DataFrame, as_of: pd.Timestamp, lookback_days: int = 20, tolerance: str = "5min"
) -> float:
    """Volume in the bar(s) at ``as_of`` vs the median volume at the same clock
    time on the trailing ``lookback_days`` trading days.

    Ratio > 1 means "busier than usual for this time of day". Uses a
    +/- ``tolerance`` window around the same local clock time on each prior
    day rather than an exact-second match, since bar grids can jitter.
    """
    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    tol = pd.Timedelta(tolerance)
    current_vol = float(b["volume"].iloc[-1]) if pd.notna(b["volume"].iloc[-1]) else float("nan")
    if math.isnan(current_vol):
        return float("nan")
    local_time = as_of.tz_convert(CME_TZ).time()
    days = pd.unique(trading_day(b.index))
    today = trading_day(as_of)
    hist_vols: list[float] = []
    for d in sorted(days):
        if d >= today:
            continue
        start = pd.Timestamp.combine(d, local_time).tz_localize(
            CME_TZ, nonexistent="shift_forward", ambiguous=True
        ).tz_convert("UTC")
        window = b.loc[(b.index >= start - tol) & (b.index <= start + tol)]
        if len(window) > 0 and window["volume"].notna().any():
            hist_vols.append(float(window["volume"].fillna(0).mean()))
    hist_vols = hist_vols[-lookback_days:]
    if len(hist_vols) < 3:
        return float("nan")
    median = float(np.median(hist_vols))
    if median <= 0:
        return float("nan")
    return float(current_vol / median)


def dist_to_prior_day_high_atr(
    bars: pd.DataFrame, as_of: pd.Timestamp, instrument_or_symbol: Instrument | str, atr_window: int = 14
) -> float:
    """(prior day high - last close) / ATR. Positive means still below prior-day high."""
    return _dist_to_prior_level(bars, as_of, instrument_or_symbol, atr_window, level="high")


def dist_to_prior_day_low_atr(
    bars: pd.DataFrame, as_of: pd.Timestamp, instrument_or_symbol: Instrument | str, atr_window: int = 14
) -> float:
    """(last close - prior day low) / ATR. Positive means still above prior-day low."""
    return _dist_to_prior_level(bars, as_of, instrument_or_symbol, atr_window, level="low")


def _dist_to_prior_level(
    bars: pd.DataFrame,
    as_of: pd.Timestamp,
    instrument_or_symbol: Instrument | str,
    atr_window: int,
    level: str,
) -> float:
    from lab.core.sessions import prior_day_levels  # local import: avoid cycle risk

    b = _asof(bars, as_of)
    if len(b) == 0:
        return float("nan")
    day = trading_day(as_of)
    prior = prior_day_levels(b, day)
    a = atr(bars, as_of, atr_window)
    if prior is None or math.isnan(a) or a == 0:
        return float("nan")
    close = float(b["close"].iloc[-1])
    if level == "high":
        return float((prior["high"] - close) / a)
    return float((close - prior["low"]) / a)


def minutes_to_next_release(as_of: pd.Timestamp, calendar: pd.DataFrame | None) -> float:
    """Minutes until the next scheduled high-impact release at or after ``as_of``.

    ``calendar`` is exogenous, known-in-advance information (an economic
    calendar published ahead of time), not price data, so looking forward in
    it is not leakage the way looking forward in ``bars`` would be -- a trader
    at ``as_of`` genuinely knows when the next release is scheduled. NaN if no
    calendar is supplied or nothing remains scheduled.
    """
    if calendar is None or len(calendar) == 0:
        return float("nan")
    ts = calendar.index if isinstance(calendar.index, pd.DatetimeIndex) else pd.DatetimeIndex(calendar["ts"])
    upcoming = ts[ts >= as_of]
    if len(upcoming) == 0:
        return float("nan")
    return float((upcoming.min() - as_of).total_seconds() / 60.0)


def correlated_instrument_move(
    bars: pd.DataFrame,
    as_of: pd.Timestamp,
    other_bars: pd.DataFrame,
    window: str = "30min",
) -> float:
    """Percent move of a correlated instrument (e.g. NQ vs ES) over the trailing window.

    Both frames are sliced to ``as_of`` independently so the confirmation
    signal is exactly as point-in-time as the primary instrument's own
    features.
    """
    b_other = other_bars.loc[:as_of]
    if len(b_other) == 0:
        return float("nan")
    w = pd.Timedelta(window)
    start = as_of - w
    win = b_other.loc[(b_other.index >= start) & (b_other.index <= as_of)]
    if len(win) < 2:
        return float("nan")
    first, last = float(win["close"].iloc[0]), float(win["close"].iloc[-1])
    if first == 0:
        return float("nan")
    return float((last - first) / first)


def day_of_week(bars: pd.DataFrame, as_of: pd.Timestamp) -> int:
    """0=Monday ... 6=Sunday, in the CME trading-day sense (uses the exchange clock)."""
    del bars  # unused: calendar fact only
    return int(as_of.tz_convert(CME_TZ).dayofweek)


#: name -> builder, for :func:`build_feature_frame`'s default feature set.
#: Builders that need extra positional args beyond ``(bars, as_of)`` are
#: wrapped with sensible defaults; callers who need different windows/lookbacks
#: should pass their own ``feature_fns`` mapping instead of this default.
FEATURE_REGISTRY: dict[str, Callable[..., Any]] = {
    "atr": atr,
    "atr_percentile": atr_percentile,
    "asia_range_size": asia_range_size,
    "asia_range_percentile": asia_range_percentile,
    "overnight_realised_vol": overnight_realised_vol,
    "vwap_distance_atr": vwap_distance_atr,
    "minutes_since_session_open": minutes_since_session_open,
    "opening_gap": opening_gap,
    "volume_relative_to_tod": volume_relative_to_tod,
    "day_of_week": day_of_week,
}


def build_feature_frame(
    signals: Sequence[Signal],
    bars: pd.DataFrame,
    extra_frames: Mapping[str, pd.DataFrame] | None = None,
    feature_fns: Mapping[str, Callable[..., Any]] | None = None,
    calendar: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Assemble a feature matrix, one row per signal, indexed by ``signal.ts``.

    For each named feature, a signal's own ``meta`` dict is consulted first --
    if the strategy already recorded that value at decision time (e.g.
    ``meta["atr"]``), that value is used verbatim rather than recomputed,
    because the strategy's decision-time value is the ground truth of what it
    actually acted on. Only signals missing a given key fall back to calling
    the corresponding builder in ``feature_fns`` (default
    :data:`FEATURE_REGISTRY`) against ``bars``.

    ``time_of_day`` is expanded into ``time_of_day_sin`` / ``time_of_day_cos``
    columns since it is not a single scalar. ``sweep_depth_ticks`` and
    ``dist_to_prior_day_*_atr`` need the signal's own level/direction/symbol
    and so are only computed when the strategy did *not* already record them
    in ``meta`` -- add them to ``feature_fns`` with a partial application if
    you want them recomputed by default.
    """
    fns = dict(FEATURE_REGISTRY)
    if feature_fns:
        fns.update(feature_fns)
    extra_frames = extra_frames or {}

    rows: list[dict[str, Any]] = []
    idx: list[pd.Timestamp] = []
    for sig in signals:
        as_of = sig.ts
        row: dict[str, Any] = {}
        for name, fn in fns.items():
            if name in sig.meta:
                row[name] = sig.meta[name]
                continue
            try:
                row[name] = fn(bars, as_of)
            except Exception:
                row[name] = float("nan")

        # time-of-day is a pair; prefer meta keys if the strategy recorded them.
        if "time_of_day_sin" in sig.meta and "time_of_day_cos" in sig.meta:
            row["time_of_day_sin"] = sig.meta["time_of_day_sin"]
            row["time_of_day_cos"] = sig.meta["time_of_day_cos"]
        else:
            s, c = time_of_day_cyclical(bars, as_of)
            row["time_of_day_sin"], row["time_of_day_cos"] = s, c

        # correlated-instrument confirmation, one column per extra frame.
        for sym, other in extra_frames.items():
            meta_key = f"corr_{sym}_move"
            if meta_key in sig.meta:
                row[meta_key] = sig.meta[meta_key]
            else:
                row[meta_key] = correlated_instrument_move(bars, as_of, other)

        if "minutes_to_next_release" in sig.meta:
            row["minutes_to_next_release"] = sig.meta["minutes_to_next_release"]
        else:
            row["minutes_to_next_release"] = minutes_to_next_release(as_of, calendar)

        rows.append(row)
        idx.append(as_of)

    out = pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="ts"))
    out = out.sort_index(kind="stable")
    return out
