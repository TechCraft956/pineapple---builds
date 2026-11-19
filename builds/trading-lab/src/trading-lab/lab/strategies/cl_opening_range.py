"""CL (Crude Oil) opening-range breakout family.

Three related setups sharing one range definition (see
``specs/cl_opening_range.md`` for the full contract and change log): the
opening range is the high/low of the first ``or_minutes`` minutes of the
NYMEX pit session (:data:`lab.core.sessions.CL_RTH`, 08:00 CT). What happens
once that range is set is controlled by ``variant``:

* ``breakout`` -- a trade-through of the OR edge is a stop entry in the
  breakout direction.
* ``breakout_retest`` -- the OR edge must first be confirmed (a bar closes
  beyond it), then a limit order sits at the edge waiting for price to come
  back and retest it.
* ``failed_breakout`` -- price pokes beyond the edge and is rejected (closes
  back inside) -- a fade of the failed break, entered in the opposite
  direction.

Detection is a batch scan over the day's bars, exactly like
:mod:`lab.strategies.es_london_sweep`: the strategy is free to read any bar's
own OHLCV once it is scanning up to and including that bar's index, but the
resulting :class:`~lab.core.types.Signal` is always stamped with that bar's
own timestamp, and the engine's no-lookahead rule (fill eligibility starts
strictly *after* ``Signal.ts``) is what stops the strategy from "trading on"
a bar before it closed. Every variant therefore effectively enters one bar
after the pattern is confirmed at the earliest.

Only one setup is attempted per direction per day (mirroring
``EsLondonSweep``): this module deliberately does not re-scan for a second
attempt after an earlier one is invalidated. ``max_attempts_per_day`` caps
how many of the (at most two, one per direction) candidate signals are kept,
chosen in chronological order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from lab.core.instruments import Instrument, get_instrument
from lab.core.sessions import CL_RTH, window_bounds
from lab.core.types import LONG, SHORT, Direction, Signal
from lab.strategies.base import SessionContext, Strategy

__all__ = ["ClOpeningRangeParams", "ClOpeningRange"]

_VARIANTS = ("breakout", "breakout_retest", "failed_breakout")
_STOP_MODES = ("opposite_edge", "buffer")


@dataclass(frozen=True, slots=True)
class ClOpeningRangeParams:
    """Tunable parameters. Defaults match ``specs/cl_opening_range.md`` v1.0."""

    or_minutes: int = 15  # {5, 15, 30}
    variant: str = "breakout"  # "breakout" | "breakout_retest" | "failed_breakout"
    stop_mode: str = "opposite_edge"  # "opposite_edge" | "buffer" -- breakout/breakout_retest only
    stop_buffer_ticks: int = 10
    min_break_ticks: int = 4  # failed_breakout: how far beyond the edge counts as a real break
    reclaim_within_bars: int = 6  # failed_breakout: bars allowed for the close-back-inside
    retest_within_bars: int = 5  # breakout_retest: bars allowed for the retest to occur
    order_valid_bars: int = 5  # how long the resulting order stays live once placed
    volume_filter: bool = False
    vol_mult: float = 1.5
    max_range_atr_pct: float | None = None  # OR width must be <= this fraction of ATR; None = no cap
    max_attempts_per_day: int = 1
    entry_deadline_minutes: int = 120  # no new entries after this many minutes past the RTH open

    def __post_init__(self) -> None:
        if self.or_minutes not in (5, 15, 30):
            raise ValueError(f"or_minutes must be one of (5, 15, 30), got {self.or_minutes!r}")
        if self.variant not in _VARIANTS:
            raise ValueError(f"variant must be one of {_VARIANTS}, got {self.variant!r}")
        if self.stop_mode not in _STOP_MODES:
            raise ValueError(f"stop_mode must be one of {_STOP_MODES}, got {self.stop_mode!r}")
        if self.entry_deadline_minutes <= self.or_minutes:
            raise ValueError("entry_deadline_minutes must leave time after the OR completes")
        if self.max_attempts_per_day < 1:
            raise ValueError("max_attempts_per_day must be >= 1")
        for name, val in (
            ("stop_buffer_ticks", self.stop_buffer_ticks),
            ("min_break_ticks", self.min_break_ticks),
            ("reclaim_within_bars", self.reclaim_within_bars),
            ("retest_within_bars", self.retest_within_bars),
            ("order_valid_bars", self.order_valid_bars),
        ):
            if val < 1:
                raise ValueError(f"{name} must be >= 1, got {val!r}")
        if self.vol_mult <= 0:
            raise ValueError(f"vol_mult must be > 0, got {self.vol_mult!r}")
        if self.max_range_atr_pct is not None and self.max_range_atr_pct <= 0:
            raise ValueError(f"max_range_atr_pct must be > 0 or None, got {self.max_range_atr_pct!r}")


class ClOpeningRange(Strategy):
    """CL opening-range breakout / breakout-retest / failed-breakout fade."""

    def __init__(self, params: ClOpeningRangeParams | None = None, instrument: Instrument | None = None) -> None:
        self._params = params or ClOpeningRangeParams()
        self._instrument = instrument or get_instrument("CL")

    @property
    def name(self) -> str:
        return "cl_opening_range"

    @property
    def version(self) -> str:
        return "v1.0"

    @property
    def params(self) -> ClOpeningRangeParams:
        return self._params

    def describe(self) -> str:
        p = self._params
        return (
            f"{self.name} {self.version}: {p.or_minutes}-minute opening range off the CL RTH open "
            f"(08:00 CT), variant={p.variant}. Stop {p.stop_mode} "
            f"({'opposite OR edge' if p.stop_mode == 'opposite_edge' else f'{p.stop_buffer_ticks} ticks beyond entry'}). "
            f"No new entries after {p.entry_deadline_minutes} minutes past the open. "
            f"Max {p.max_attempts_per_day} attempt(s)/day. "
            "See specs/cl_opening_range.md for the full contract and change log."
        )

    # ------------------------------------------------------------------

    def generate(self, day: date, bars: pd.DataFrame, ctx: SessionContext) -> list[Signal]:
        p = self._params
        start, end = window_bounds(CL_RTH, day)
        or_end = start + pd.Timedelta(minutes=p.or_minutes)

        or_bars = bars.loc[(bars.index >= start) & (bars.index < or_end)]
        if or_bars.empty:
            return []  # no data for this day's opening range -- nothing to anchor to
        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_width = or_high - or_low
        if or_width <= 0:
            return []  # degenerate (single-print) range -- not a tradable OR

        or_ctx = ctx.as_of(or_end)
        atr = or_ctx.atr
        or_width_atr = (or_width / atr) if atr is not None and atr > 0 else None
        if p.max_range_atr_pct is not None:
            if or_width_atr is None or or_width_atr > p.max_range_atr_pct:
                return []  # range too wide (or ATR unknown) relative to normal -- sit out

        post_or = bars.loc[(bars.index >= or_end) & (bars.index < end)]
        if post_or.empty:
            return []

        deadline_ts = start + pd.Timedelta(minutes=p.entry_deadline_minutes)
        news_day = any(w_start < end and w_end > start for w_start, w_end in ctx.news_windows)

        scan = {
            "breakout": self._scan_breakout,
            "breakout_retest": self._scan_retest,
            "failed_breakout": self._scan_failed,
        }[p.variant]

        signals: list[Signal] = []
        for direction in (LONG, SHORT):
            sig = scan(direction, or_high, or_low, or_width, or_width_atr, post_or, ctx, deadline_ts, news_day)
            if sig is not None:
                signals.append(sig)
        signals.sort(key=lambda s: s.ts)
        return signals[: p.max_attempts_per_day]

    # ------------------------------------------------------------------
    # variant scans -- each returns at most one Signal for one direction
    # ------------------------------------------------------------------

    def _stop_for(self, direction: Direction, entry: float, opposite_edge: float) -> float:
        p, inst = self._params, self._instrument
        if p.stop_mode == "opposite_edge":
            stop = opposite_edge
        else:
            buf = p.stop_buffer_ticks * inst.tick_size
            stop = entry - buf if direction == LONG else entry + buf
        return inst.round_to_tick(stop)

    def _base_meta(
        self,
        ctx: SessionContext,
        decision_ts: pd.Timestamp,
        *,
        or_high: float,
        or_low: float,
        or_width: float,
        or_width_atr: float | None,
        break_depth: float,
        volume_ratio: float | None,
        news_day: bool,
    ) -> dict:
        p = self._params
        local_ctx = ctx.as_of(decision_ts)
        meta = dict(local_ctx.as_dict())
        meta.update({
            "variant": p.variant,
            "or_minutes": p.or_minutes,
            "or_high": or_high,
            "or_low": or_low,
            "or_width": or_width,
            "or_width_atr": or_width_atr,
            "break_depth": break_depth,
            "volume_ratio": volume_ratio,
            "news_day": news_day,
        })
        return meta

    def _scan_breakout(
        self,
        direction: Direction,
        or_high: float,
        or_low: float,
        or_width: float,
        or_width_atr: float | None,
        post_or: pd.DataFrame,
        ctx: SessionContext,
        deadline_ts: pd.Timestamp,
        news_day: bool,
    ) -> Signal | None:
        """Stop entry on the first bar whose range trades through the OR edge."""
        p, inst = self._params, self._instrument
        edge = or_high if direction == LONG else or_low
        opposite = or_low if direction == LONG else or_high

        for i in range(len(post_or)):
            ts = post_or.index[i]
            if ts >= deadline_ts:
                break
            if ctx.in_news_block(ts):
                continue
            bar = post_or.iloc[i]
            triggered = (direction == LONG and bar["high"] >= edge) or (direction == SHORT and bar["low"] <= edge)
            if not triggered:
                continue

            vol_ratio = None
            if p.volume_filter:
                median_vol = ctx.same_time_of_day_volume(ts)
                if median_vol is None or median_vol <= 0:
                    continue
                bar_vol = float(bar["volume"]) if pd.notna(bar["volume"]) else 0.0
                if not (bar_vol > p.vol_mult * median_vol):
                    continue
                vol_ratio = bar_vol / median_vol

            entry = inst.round_to_tick(edge)
            stop = self._stop_for(direction, entry, opposite)
            extreme = float(bar["high"]) if direction == LONG else float(bar["low"])
            break_depth = abs(extreme - edge)
            valid_until = post_or.index[min(i + p.order_valid_bars, len(post_or) - 1)]
            meta = self._base_meta(
                ctx, ts, or_high=or_high, or_low=or_low, or_width=or_width, or_width_atr=or_width_atr,
                break_depth=break_depth, volume_ratio=vol_ratio, news_day=news_day,
            )
            try:
                return Signal(
                    ts=ts, direction=direction, entry=entry, stop=stop, entry_type="stop",
                    valid_until=valid_until,
                    tag="cl_or_breakout_long" if direction == LONG else "cl_or_breakout_short",
                    strategy=self.name, symbol=inst.symbol, meta=meta,
                )
            except ValueError:
                # tick rounding put stop on the wrong side of a razor-thin edge -- skip.
                return None
        return None

    def _scan_retest(
        self,
        direction: Direction,
        or_high: float,
        or_low: float,
        or_width: float,
        or_width_atr: float | None,
        post_or: pd.DataFrame,
        ctx: SessionContext,
        deadline_ts: pd.Timestamp,
        news_day: bool,
    ) -> Signal | None:
        """Limit order at the edge, placed once a breakout bar *closes* beyond it and
        price comes back to retest within ``retest_within_bars``."""
        p, inst = self._params, self._instrument
        edge = or_high if direction == LONG else or_low
        opposite = or_low if direction == LONG else or_high

        breakout_idx: int | None = None
        for i in range(len(post_or)):
            ts = post_or.index[i]
            if ts >= deadline_ts:
                break
            if ctx.in_news_block(ts):
                continue
            bar = post_or.iloc[i]
            closed_beyond = (direction == LONG and bar["close"] > edge) or (direction == SHORT and bar["close"] < edge)
            if not closed_beyond:
                continue
            if p.volume_filter:
                median_vol = ctx.same_time_of_day_volume(ts)
                bar_vol = float(bar["volume"]) if pd.notna(bar["volume"]) else 0.0
                if median_vol is None or median_vol <= 0 or not (bar_vol > p.vol_mult * median_vol):
                    continue
            breakout_idx = i
            break
        if breakout_idx is None:
            return None

        end_scan = min(len(post_or), breakout_idx + 1 + p.retest_within_bars)
        retest_idx: int | None = None
        for i in range(breakout_idx + 1, end_scan):
            ts = post_or.index[i]
            if ts >= deadline_ts:
                break
            bar = post_or.iloc[i]
            retested = (direction == LONG and bar["low"] <= edge) or (direction == SHORT and bar["high"] >= edge)
            if retested:
                retest_idx = i
                break
        if retest_idx is None:
            return None

        decision_ts = post_or.index[retest_idx]
        if decision_ts >= deadline_ts or ctx.in_news_block(decision_ts):
            return None

        entry = inst.round_to_tick(edge)
        stop = self._stop_for(direction, entry, opposite)
        breakout_close = float(post_or.iloc[breakout_idx]["close"])
        break_depth = abs(breakout_close - edge)
        valid_until = post_or.index[min(retest_idx + p.order_valid_bars, len(post_or) - 1)]
        meta = self._base_meta(
            ctx, decision_ts, or_high=or_high, or_low=or_low, or_width=or_width, or_width_atr=or_width_atr,
            break_depth=break_depth, volume_ratio=None, news_day=news_day,
        )
        meta["breakout_ts"] = post_or.index[breakout_idx]
        try:
            return Signal(
                ts=decision_ts, direction=direction, entry=entry, stop=stop, entry_type="limit",
                valid_until=valid_until,
                tag="cl_or_breakout_retest_long" if direction == LONG else "cl_or_breakout_retest_short",
                strategy=self.name, symbol=inst.symbol, meta=meta,
            )
        except ValueError:
            return None

    def _scan_failed(
        self,
        direction: Direction,
        or_high: float,
        or_low: float,
        or_width: float,
        or_width_atr: float | None,
        post_or: pd.DataFrame,
        ctx: SessionContext,
        deadline_ts: pd.Timestamp,
        news_day: bool,
    ) -> Signal | None:
        """Fade a break that fails: price clears an edge by >= min_break_ticks then
        closes back inside within reclaim_within_bars. ``direction`` here is the
        *resulting trade's* direction, so a LONG fade watches the OR low being
        broken and reclaimed, and a SHORT fade watches the OR high."""
        p, inst = self._params, self._instrument
        if direction == LONG:
            break_edge = or_low
            reclaim_check = lambda bar: bar["close"] > or_low  # noqa: E731
            break_check = lambda bar: bar["low"] <= or_low - p.min_break_ticks * inst.tick_size  # noqa: E731
            extreme_of = lambda bar: float(bar["low"])  # noqa: E731
        else:
            break_edge = or_high
            reclaim_check = lambda bar: bar["close"] < or_high  # noqa: E731
            break_check = lambda bar: bar["high"] >= or_high + p.min_break_ticks * inst.tick_size  # noqa: E731
            extreme_of = lambda bar: float(bar["high"])  # noqa: E731

        break_idx: int | None = None
        extreme: float | None = None
        for i in range(len(post_or)):
            ts = post_or.index[i]
            if ts >= deadline_ts:
                break
            if ctx.in_news_block(ts):
                continue
            bar = post_or.iloc[i]
            if not break_check(bar):
                continue
            if p.volume_filter:
                median_vol = ctx.same_time_of_day_volume(ts)
                bar_vol = float(bar["volume"]) if pd.notna(bar["volume"]) else 0.0
                if median_vol is None or median_vol <= 0 or not (bar_vol > p.vol_mult * median_vol):
                    continue
            break_idx, extreme = i, extreme_of(bar)
            break
        if break_idx is None or extreme is None:
            return None

        end_scan = min(len(post_or), break_idx + 1 + p.reclaim_within_bars)
        reclaim_idx: int | None = None
        for i in range(break_idx + 1, end_scan):
            ts = post_or.index[i]
            if ts >= deadline_ts:
                break
            bar = post_or.iloc[i]
            if reclaim_check(bar):
                reclaim_idx = i
                break
        if reclaim_idx is None:
            return None

        decision_ts = post_or.index[reclaim_idx]
        if decision_ts >= deadline_ts or ctx.in_news_block(decision_ts):
            return None

        bar = post_or.iloc[reclaim_idx]
        entry = inst.round_to_tick(float(bar["close"]))
        buf = p.stop_buffer_ticks * inst.tick_size
        stop = inst.round_to_tick(extreme - buf if direction == LONG else extreme + buf)
        break_depth = abs(extreme - break_edge)
        valid_until = post_or.index[min(reclaim_idx + p.order_valid_bars, len(post_or) - 1)]
        meta = self._base_meta(
            ctx, decision_ts, or_high=or_high, or_low=or_low, or_width=or_width, or_width_atr=or_width_atr,
            break_depth=break_depth, volume_ratio=None, news_day=news_day,
        )
        meta["failed_extreme"] = extreme
        try:
            return Signal(
                ts=decision_ts, direction=direction, entry=entry, stop=stop, entry_type="market",
                valid_until=valid_until,
                tag="cl_or_failed_breakout_long" if direction == LONG else "cl_or_failed_breakout_short",
                strategy=self.name, symbol=inst.symbol, meta=meta,
            )
        except ValueError:
            return None
