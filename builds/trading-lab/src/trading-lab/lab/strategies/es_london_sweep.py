"""ES London liquidity sweep and reversal.

One pattern, kept to one pattern on purpose (see ``specs/es_london_sweep.md``
for the full spec and change log): price takes out the Asia session's high or
low, fails to hold outside it, and reverses with displacement. The strategy's
job stops at emitting a :class:`~lab.core.types.Signal` for the retrace back
into the displacement leg -- it does not know or care how the trade is
managed afterwards; that is entirely the :class:`~lab.backtest.exits.ExitPolicy`
handed to the engine.

Rule sequence, both directions symmetric
------------------------------------------
1. **Sweep**: a bar's high (low) trades ``>= sweep_min_ticks`` beyond the
   Asia high (low).
2. **Reclaim**: within ``reclaim_within_bars`` of the sweep bar, a bar
   *closes* back inside the Asia range.
3. **Displacement**: within the same window, a later bar's close breaks the
   recent swing low/high (the extreme over ``structure_lookback`` bars
   immediately preceding the sweep) by ``>= displacement_atr_mult`` ATR --
   the "structure shift" that separates a real reversal from a sweep that
   just chops back to the middle of the range.
4. **Entry**: a ``retrace_pct`` pullback into the displacement leg, as a
   limit order -- or at market immediately on confirmed displacement if
   ``entry_type="market"``.
5. **Stop**: ``stop_buffer_ticks`` beyond the sweep extreme.
6. **Exit**: supplied entirely by the caller's ``ExitPolicy``; this module
   never sets a target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from lab.core.instruments import Instrument, get_instrument
from lab.core.sessions import LONDON, SessionWindow, slice_window
from lab.core.types import LONG, SHORT, Direction, Signal
from lab.strategies.base import SessionContext, Strategy

__all__ = ["EsLondonSweepParams", "EsLondonSweep"]


@dataclass(frozen=True, slots=True)
class EsLondonSweepParams:
    """Tunable parameters. Defaults match ``specs/es_london_sweep.md`` v1.0."""

    sweep_min_ticks: int = 4
    reclaim_within_bars: int = 6
    structure_lookback: int = 15
    displacement_atr_mult: float = 0.5
    retrace_pct: float = 0.5
    entry_type: str = "limit"  # "limit" or "market"
    stop_buffer_ticks: int = 3
    entry_window: SessionWindow = LONDON
    max_attempts_per_day: int = 1
    min_overnight_range: float | None = None  # in points; None = no floor
    max_overnight_range: float | None = None  # in points; None = no ceiling
    order_valid_bars: int = 10  # how long the retrace limit order stays live


class EsLondonSweep(Strategy):
    """Asia-range liquidity sweep + reclaim + displacement, retrace entry."""

    def __init__(self, params: EsLondonSweepParams | None = None, instrument: Instrument | None = None) -> None:
        self._params = params or EsLondonSweepParams()
        self._instrument = instrument or get_instrument("ES")

    @property
    def name(self) -> str:
        return "es_london_sweep"

    @property
    def version(self) -> str:
        return "v1.0"

    @property
    def params(self) -> EsLondonSweepParams:
        return self._params

    def describe(self) -> str:
        p = self._params
        return (
            f"{self.name} {self.version}: sweep Asia high/low by >= {p.sweep_min_ticks} ticks, "
            f"reclaim within {p.reclaim_within_bars} bars, displacement >= {p.displacement_atr_mult} ATR "
            f"beyond a {p.structure_lookback}-bar swing, entry at a {p.retrace_pct:.0%} retrace "
            f"({p.entry_type}), stop {p.stop_buffer_ticks} ticks beyond the sweep extreme. "
            f"Window: {p.entry_window.name} ({p.entry_window.start}-{p.entry_window.end} "
            f"{p.entry_window.tz}). Max {p.max_attempts_per_day} attempt(s)/day. "
            "See specs/es_london_sweep.md for the full contract and change log."
        )

    # ------------------------------------------------------------------

    def generate(self, day: date, bars: pd.DataFrame, ctx: SessionContext) -> list[Signal]:
        p = self._params
        if ctx.asia_high is None or ctx.asia_low is None:
            return []  # no Asia session data for this day -- nothing to sweep
        if p.min_overnight_range is not None and (ctx.overnight_range or 0.0) < p.min_overnight_range:
            return []
        if p.max_overnight_range is not None and (ctx.overnight_range or float("inf")) > p.max_overnight_range:
            return []

        window = slice_window(bars, p.entry_window, day)
        if window.empty:
            return []

        signals: list[Signal] = []
        for direction in (SHORT, LONG):
            sig = self._scan(direction, window, ctx, day)
            if sig is not None:
                signals.append(sig)
        signals.sort(key=lambda s: s.ts)
        return signals[: p.max_attempts_per_day]

    # ------------------------------------------------------------------

    def _scan(self, direction: Direction, window: pd.DataFrame, ctx: SessionContext, day: date) -> Signal | None:
        """Run the sweep -> reclaim -> displacement state machine for one direction."""
        p = self._params
        inst = self._instrument
        level = ctx.asia_high if direction == SHORT else ctx.asia_low
        sweep_dist = p.sweep_min_ticks * inst.tick_size

        sweep_idx: int | None = None
        sweep_extreme: float | None = None
        for i in range(len(window)):
            bar = window.iloc[i]
            ts = window.index[i]
            if ctx.in_news_block(ts):
                continue
            if direction == SHORT and bar["high"] >= level + sweep_dist:
                sweep_idx, sweep_extreme = i, float(bar["high"])
                break
            if direction == LONG and bar["low"] <= level - sweep_dist:
                sweep_idx, sweep_extreme = i, float(bar["low"])
                break
        if sweep_idx is None:
            return None

        lookback_start = max(0, sweep_idx - p.structure_lookback)
        prior_swing = (
            float(window.iloc[lookback_start:sweep_idx]["low"].min())
            if direction == SHORT
            else float(window.iloc[lookback_start:sweep_idx]["high"].max())
        ) if sweep_idx > lookback_start else None

        reclaim_idx: int | None = None
        end = min(len(window), sweep_idx + 1 + p.reclaim_within_bars)
        for i in range(sweep_idx + 1, end):
            bar = window.iloc[i]
            if direction == SHORT and bar["close"] < level:
                reclaim_idx = i
                break
            if direction == LONG and bar["close"] > level:
                reclaim_idx = i
                break
        if reclaim_idx is None or prior_swing is None:
            return None

        displaced_idx: int | None = None
        displaced_close: float | None = None
        for i in range(reclaim_idx, end):
            ts = window.index[i]
            bar = window.iloc[i]
            local_ctx = ctx.as_of(ts)
            if local_ctx.atr is None or local_ctx.atr <= 0:
                continue
            threshold = p.displacement_atr_mult * local_ctx.atr
            close = float(bar["close"])
            if direction == SHORT and close <= prior_swing - threshold:
                displaced_idx, displaced_close = i, close
                break
            if direction == LONG and close >= prior_swing + threshold:
                displaced_idx, displaced_close = i, close
                break
        if displaced_idx is None:
            return None

        decision_ts = window.index[displaced_idx]
        if ctx.in_news_block(decision_ts):
            return None

        stop = (
            sweep_extreme + p.stop_buffer_ticks * inst.tick_size
            if direction == SHORT
            else sweep_extreme - p.stop_buffer_ticks * inst.tick_size
        )
        if p.entry_type == "market":
            entry = displaced_close
        else:
            # retrace_pct of the way back from the displacement close toward the
            # sweep extreme -- works unmodified for both directions since
            # (sweep_extreme - displaced_close) is already signed correctly:
            # positive (pulls up) for shorts, negative (pulls down) for longs.
            entry = displaced_close + p.retrace_pct * (sweep_extreme - displaced_close)
            entry = inst.round_to_tick(entry)

        valid_until = window.index[min(displaced_idx + p.order_valid_bars, len(window) - 1)]
        local_ctx = ctx.as_of(decision_ts)
        meta = dict(local_ctx.as_dict())
        meta.update({
            "sweep_extreme": sweep_extreme,
            "sweep_level": level,
            "prior_swing": prior_swing,
            "displacement_close": displaced_close,
            "reclaim_ts": window.index[reclaim_idx],
            "sweep_ts": window.index[sweep_idx],
        })

        try:
            return Signal(
                ts=decision_ts,
                direction=direction,
                entry=float(entry),
                stop=float(stop),
                entry_type=p.entry_type,
                valid_until=valid_until,
                tag="asia_high_sweep" if direction == SHORT else "asia_low_sweep",
                strategy=self.name,
                symbol=inst.symbol,
                meta=meta,
            )
        except ValueError:
            # entry/stop ordering violated by tick rounding on a razor-thin
            # displacement leg -- a real setup would not be sized this way,
            # so skip rather than fabricate a degenerate signal.
            return None
