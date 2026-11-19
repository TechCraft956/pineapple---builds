"""Everything a strategy is allowed to know, and the contract it implements.

Two ideas hold this module together:

1. **A strategy never sees a fill.** It emits :class:`~lab.core.types.Signal`
   objects describing intent (entry, stop, tag, decision-time context); only
   :mod:`lab.backtest.engine` decides whether and at what price they become
   trades. Keeping that boundary hard is what makes "swap the exit policy" or
   "swap the cost model" a one-line change instead of a strategy rewrite.
2. **Decision-time context is captured once, at decision time, in full.**
   :class:`SessionContext` computes everything a discretionary trader could
   plausibly have looked at (session levels, ATR, VWAP, realised vol, a
   trend label, news windows, a regime tag) and every :class:`Strategy` is
   required to stuff the resulting snapshot into ``Signal.meta``. The ML
   layer downstream reads its features from there and nowhere else -- a
   field left out now is unrecoverable later, because by the time anyone
   notices it's missing the market that produced it is gone.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Sequence

import numpy as np
import pandas as pd

from lab.core.instruments import Instrument
from lab.core.sessions import (
    ASIA,
    OVERNIGHT,
    SessionWindow,
    prior_day_levels,
    session_levels,
    slice_window,
    trading_day,
)
from lab.core.types import Signal

__all__ = ["NewsWindow", "SessionContext", "build_session_context", "Strategy"]

#: A blocked interval, e.g. an FOMC or high-impact energy inventory release.
NewsWindow = tuple[pd.Timestamp, pd.Timestamp]


def _percentile_of(value: float, history: Sequence[float]) -> float | None:
    """Fraction of ``history`` at or below ``value``. ``None`` if ``history`` is empty."""
    hist = [h for h in history if h is not None and np.isfinite(h)]
    if not hist or value is None or not np.isfinite(value):
        return None
    return float(sum(1 for h in hist if h <= value) / len(hist))


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Decision-time context for one CME trading day, safe to hand to a strategy.

    Two kinds of field live here:

    * **Day-level, fixed before the decision window opens** (Asia/overnight
      levels, prior-day levels, news windows). These are legitimately known
      before London or RTH begins, so they are computed once at
      :func:`build_session_context` time and never change across
      :meth:`as_of` calls for the same day.
    * **As-of-``ts`` fields** (``atr``, ``session_vwap``, ``dist_to_vwap``,
      ``realised_vol``, ``trend_label``, ``regime``) are ``None`` until
      :meth:`as_of` is called, and are then computed strictly from bars
      timestamped ``<= ts``. This is the one and only sanctioned way to get a
      context object with those fields populated -- there is no setter, so a
      strategy cannot accidentally reach past ``ts``.
    """

    day: date
    symbol: str
    ts: pd.Timestamp | None = None

    asia_high: float | None = None
    asia_low: float | None = None
    asia_range: float | None = None
    prior_day_high: float | None = None
    prior_day_low: float | None = None
    prior_day_close: float | None = None
    overnight_high: float | None = None
    overnight_low: float | None = None
    overnight_range: float | None = None
    overnight_range_percentile: float | None = None
    news_windows: tuple[NewsWindow, ...] = ()

    atr: float | None = None
    session_vwap: float | None = None
    dist_to_vwap: float | None = None
    realised_vol: float | None = None
    realised_vol_percentile: float | None = None
    trend_label: str | None = None
    regime: str | None = None

    # Internal only: full bar history up to and including `day`, used to
    # compute as-of-ts fields on demand. Never read this from strategy code;
    # go through as_of()/in_news_block() instead.
    _history: pd.DataFrame = field(default=None, repr=False, compare=False)
    _atr_period: int = field(default=14, repr=False, compare=False)
    _vol_lookback: int = field(default=20, repr=False, compare=False)
    _trend_lookback: int = field(default=50, repr=False, compare=False)
    _tz: str = field(default="America/Chicago", repr=False, compare=False)

    def in_news_block(self, ts: pd.Timestamp) -> bool:
        """Whether ``ts`` falls inside any configured blocked news window."""
        return any(start <= ts < end for start, end in self.news_windows)

    def same_time_of_day_volume(self, ts: pd.Timestamp, lookback_days: int = 20) -> float | None:
        """Median volume of bars at the same wall-clock minute on prior trading days.

        Used by volume-filtered strategies (e.g. ``ClOpeningRange``) to judge
        whether a bar's volume is "elevated" relative to what normally trades
        at that time of day, rather than against the session's own average
        (which would flag every session's naturally busiest minute as
        elevated). Only *prior* days (``< self.day``) are ever included, so
        this cannot leak same-day-later information either.
        """
        if self._history is None or self._history.empty:
            return None
        local = self._history.index.tz_convert(self._tz)
        target = pd.Timestamp(ts).tz_convert(self._tz)
        same_minute = self._history.loc[(local.hour == target.hour) & (local.minute == target.minute)]
        if same_minute.empty:
            return None
        days = trading_day(same_minute.index, tz=self._tz)
        prior_days = sorted(d for d in pd.unique(days) if d < self.day)[-lookback_days:]
        vols = same_minute.loc[pd.Index(days).isin(prior_days)]["volume"].dropna()
        return float(vols.median()) if len(vols) else None

    def as_of(self, ts: pd.Timestamp) -> "SessionContext":
        """Return a snapshot with the as-of-``ts`` fields computed from bars ``<= ts``.

        The only source of truth for "what did the strategy know at ``ts``"
        anywhere in the lab. Recomputes from scratch each call rather than
        mutating, so calling it twice at the same ``ts`` is always safe and
        cheap enough to call from inside a strategy's per-bar loop.
        """
        if self._history is None or len(self._history) == 0:
            return replace(self, ts=ts)
        sliced = self._history.loc[self._history.index <= ts]
        if sliced.empty:
            return replace(self, ts=ts)

        atr = _atr(sliced, self._atr_period)

        today = sliced.loc[trading_day(sliced.index) == self.day]
        vwap = _vwap(today) if len(today) else None
        last_close = float(sliced["close"].iloc[-1])
        dist_to_vwap = (last_close - vwap) if vwap is not None else None

        vol_window = sliced["close"].iloc[-(self._vol_lookback + 1):]
        realised_vol = float(vol_window.pct_change().dropna().std()) if len(vol_window) > 2 else None
        # trailing distribution of the same rolling-vol measure, for a percentile
        vol_hist = (
            sliced["close"].pct_change().rolling(self._vol_lookback).std().dropna().tolist()
        )
        realised_vol_pctl = _percentile_of(realised_vol, vol_hist[:-1]) if realised_vol is not None and vol_hist else None

        trend_window = sliced["close"].iloc[-self._trend_lookback:]
        trend_label = None
        if len(trend_window) >= 5:
            sma = float(trend_window.mean())
            if last_close > sma * 1.0005:
                trend_label = "up"
            elif last_close < sma * 0.9995:
                trend_label = "down"
            else:
                trend_label = "flat"

        regime = _regime_label(realised_vol_pctl, self.overnight_range_percentile)

        return replace(
            self,
            ts=ts,
            atr=atr,
            session_vwap=vwap,
            dist_to_vwap=dist_to_vwap,
            realised_vol=realised_vol,
            realised_vol_percentile=realised_vol_pctl,
            trend_label=trend_label,
            regime=regime,
        )

    def as_dict(self) -> dict[str, Any]:
        """Flatten into a plain dict for ``Signal.meta`` -- what the ML layer reads."""
        return {
            "day": self.day,
            "ts": self.ts,
            "asia_high": self.asia_high,
            "asia_low": self.asia_low,
            "asia_range": self.asia_range,
            "prior_day_high": self.prior_day_high,
            "prior_day_low": self.prior_day_low,
            "prior_day_close": self.prior_day_close,
            "overnight_high": self.overnight_high,
            "overnight_low": self.overnight_low,
            "overnight_range": self.overnight_range,
            "overnight_range_percentile": self.overnight_range_percentile,
            "atr": self.atr,
            "session_vwap": self.session_vwap,
            "dist_to_vwap": self.dist_to_vwap,
            "realised_vol": self.realised_vol,
            "realised_vol_percentile": self.realised_vol_percentile,
            "trend_label": self.trend_label,
            "regime": self.regime,
        }


def _atr(bars: pd.DataFrame, period: int) -> float | None:
    if len(bars) < 2:
        return None
    window = bars.iloc[-(period + 1):]
    prev_close = window["close"].shift(1)
    tr = pd.concat(
        [window["high"] - window["low"], (window["high"] - prev_close).abs(), (window["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1).dropna()
    return float(tr.mean()) if len(tr) else None


def _vwap(bars: pd.DataFrame) -> float | None:
    vol = bars["volume"].fillna(0)
    if vol.sum() <= 0:
        return float(bars["close"].mean()) if len(bars) else None
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    return float((typical * vol).sum() / vol.sum())


def _regime_label(vol_pctl: float | None, range_pctl: float | None) -> str | None:
    if vol_pctl is None and range_pctl is None:
        return None
    signal = [p for p in (vol_pctl, range_pctl) if p is not None]
    avg = sum(signal) / len(signal)
    if avg >= 0.8:
        return "high_vol"
    if avg <= 0.2:
        return "low_vol"
    return "normal"


def build_session_context(
    day: date,
    bars: pd.DataFrame,
    symbol: str,
    instrument: Instrument,
    *,
    news_windows: Sequence[NewsWindow] = (),
    overnight_lookback_days: int = 20,
    atr_period: int = 14,
    vol_lookback: int = 20,
    trend_lookback: int = 50,
) -> SessionContext:
    """Build the day-level part of a :class:`SessionContext`.

    ``bars`` may safely contain data for days after ``day`` -- everything
    that must not leak forward is filtered out here, up front, rather than
    trusted to the caller. Asia/overnight/prior-day levels are legitimately
    knowable before the decision window opens (they precede London/RTH in
    the CME trading day), so they are the only fields populated before
    :meth:`SessionContext.as_of` is ever called.
    """
    tz = instrument.session_tz
    days = trading_day(bars.index, tz=tz)
    history = bars.loc[days <= day]
    if history.empty:
        return SessionContext(day=day, symbol=symbol, news_windows=tuple(news_windows), _history=history,
                               _atr_period=atr_period, _vol_lookback=vol_lookback, _trend_lookback=trend_lookback)

    asia = session_levels(history, ASIA, day)
    overnight = session_levels(history, OVERNIGHT, day)
    prior = prior_day_levels(history, day, tz=tz)

    overnight_hist: list[float] = []
    if overnight is not None:
        all_days = pd.unique(trading_day(history.index, tz=tz))
        prior_days = sorted(d for d in all_days if d < day)[-overnight_lookback_days:]
        for d in prior_days:
            lv = session_levels(history, OVERNIGHT, d)
            if lv is not None:
                overnight_hist.append(lv["range"])
    overnight_pctl = _percentile_of(overnight["range"], overnight_hist) if overnight is not None else None

    return SessionContext(
        day=day,
        symbol=symbol,
        asia_high=asia["high"] if asia else None,
        asia_low=asia["low"] if asia else None,
        asia_range=asia["range"] if asia else None,
        prior_day_high=prior["high"] if prior else None,
        prior_day_low=prior["low"] if prior else None,
        prior_day_close=prior["close"] if prior else None,
        overnight_high=overnight["high"] if overnight else None,
        overnight_low=overnight["low"] if overnight else None,
        overnight_range=overnight["range"] if overnight else None,
        overnight_range_percentile=overnight_pctl,
        news_windows=tuple(news_windows),
        _history=history,
        _atr_period=atr_period,
        _vol_lookback=vol_lookback,
        _trend_lookback=trend_lookback,
    )


class Strategy(ABC):
    """Contract every rule-based strategy implements.

    Deliberately thin: a strategy is a pure function from
    ``(day, bars, ctx)`` to a list of signals, with no state carried between
    days and no knowledge of fills, costs or exits. That purity is what
    makes it possible to backtest, walk-forward and paper-trade the exact
    same object.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short, stable identifier used in ``Signal.strategy`` and file names."""

    @property
    @abstractmethod
    def version(self) -> str:
        """``"v1.0"``-style tag. Bump per the spec's change-log rule: one
        rule change per version, and old results are never rewritten under
        an old version tag."""

    @property
    @abstractmethod
    def params(self) -> Any:
        """The dataclass instance holding this strategy's tunable parameters."""

    @abstractmethod
    def generate(self, day: date, bars: pd.DataFrame, ctx: SessionContext) -> list[Signal]:
        """Emit zero or more signals for one CME trading day.

        ``bars`` is that trading day's bar frame (as yielded by
        :func:`lab.core.sessions.iter_sessions`); ``ctx`` is the
        :class:`SessionContext` built for the same day. Implementations must
        call ``ctx.as_of(ts)`` at each candidate decision timestamp ``ts``
        and must never index into ``bars`` past that same ``ts`` -- both are
        asserted against in the strategy test suite by re-running with future
        bars appended and checking for identical output.
        """

    @abstractmethod
    def describe(self) -> str:
        """Human-readable spec text: rules, parameters, current defaults."""
