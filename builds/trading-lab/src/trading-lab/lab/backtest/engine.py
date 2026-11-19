"""The backtest engine: turns signals into trades without lookahead.

This module is the one place in the lab allowed to decide *when and at what
price* a :class:`~lab.core.types.Signal` becomes one or more
:class:`~lab.core.types.Trade` records. Strategies never see a fill; exit
policies never see slippage. Everything that makes a number here trustworthy
or not is concentrated in this file -- read the section docstrings below
before trusting a result; each documents an assumption a careful reader needs
to audit.

No-lookahead invariant
-----------------------
The engine processes bars strictly in index order. At bar *i* it may only
read ``bars.iloc[: i + 1]`` (exit policies get the same truncated slice via
:class:`~lab.backtest.exits.ExitContext`). A signal stamped at ``ts`` is
eligible to fill starting at the first bar whose own timestamp is strictly
greater than ``ts`` -- never the bar at or before ``ts``. The eligibility
index is computed once with ``bars.index.searchsorted(ts, side="right")``,
so appending future bars to the frame cannot change any fill already decided
using earlier bars -- see ``test_engine.py::test_no_lookahead_invariance``.

One signal, many trades
------------------------
:class:`~lab.core.types.Trade` is a round-turn *slice*, not "the outcome of
one signal": a signal that scales out across three targets and then stops
out on the remainder produces up to four ``Trade`` records, all sharing
``entry_ts``/``entry_price``/``signal_ts``/``tag`` but each with its own
``exit_ts``/``exit_price``/``qty``/``pnl``. This is what lets
``trades_to_frame`` (which is one row per round-turn) stay a faithful,
un-aggregated ledger.

Fill pricing conventions (read before trusting a number)
----------------------------------------------------------
* **Market** entries/exits: next bar's open, slipped adversely.
* **Limit** entries/targets: fill at the exact stated price, no slippage,
  the moment the bar's range reaches it -- even if the bar gapped straight
  through in the trader's favour. This is conservative (a real resting order
  can sometimes do better on a favourable gap) and documented again in
  :mod:`lab.backtest.costs`.
* **Stop** entries and the protective stop: fill at the stop price plus
  slippage, *unless* the bar's open already gapped through the trigger, in
  which case fill at the open (worse for the trader) plus slippage. This is
  the "gaps invent no free money" rule: a naive engine that always fills a
  stop at its own price during a gap-through bar is quietly assuming a fill
  the market never offered.
* **Time stop / session end**: market fill at the triggering bar's close.
* **Opposing level**: fills at the level itself (limit-style, no slippage) or
  at the open on a favourable gap through it -- see
  :class:`lab.backtest.exits.OpposingLevel`.

Ambiguous bars (stop and a target both in range)
---------------------------------------------------
Resolved with ``finer_bars`` when supplied (replaying the sub-bars in
timestamp order and applying the same touch/gap rules at that resolution);
otherwise resolved by ``cfg.pessimistic_intrabar`` -- ``True`` (the default,
and the only setting meant for a result you'd publish) means the stop is
assumed to have traded first, so the bar produces a full stop-out and no
target credit. The toggle exists solely so the *size* of this effect can be
measured (``stats["ambiguous_bars_total"]``); a strategy whose numbers swing
heavily between the two settings needs tick data before its edge means
anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace as dc_replace
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from lab.core.config import LabConfig
from lab.core.frames import fingerprint
from lab.core.instruments import Instrument
from lab.core.sessions import trading_day
from lab.core.types import LONG, BacktestResult, ExitReason, Signal, Trade

from lab.backtest.costs import CostModel, SlippageContext
from lab.backtest.exits import ExitContext, ExitPolicy, PositionState
from lab.backtest.metrics import compute_stats, equity_curve

__all__ = ["SizingFn", "fixed_contracts", "risk_based", "BacktestEngine"]

SizingFn = Callable[[Signal, Instrument, float], float]

# Exit reasons whose native fill is limit/level-style and pays no slippage.
_NO_SLIP_REASONS = {ExitReason.TARGET, ExitReason.OPPOSING_LEVEL}


def fixed_contracts(n: int) -> SizingFn:
    """Always trade ``n`` contracts, regardless of risk or equity."""

    def _size(signal: Signal, instrument: Instrument, equity: float) -> float:
        return float(n)

    return _size


def risk_based(risk_dollars: float, max_contracts: int | None = None) -> SizingFn:
    """Size so the *intended* dollar risk is close to ``risk_dollars``.

    ``contracts = floor(risk_dollars / (risk_per_unit * point_value))``,
    never rounded up -- a stop so wide that even one contract risks more than
    ``risk_dollars`` sizes to zero. The engine treats qty 0 as a skip
    (recorded in ``BacktestResult.skipped``), never a forced 1-lot: a
    wide-stop setup silently trading "at least one contract" is exactly the
    undisclosed risk-budget breach this function exists to prevent.
    """

    def _size(signal: Signal, instrument: Instrument, equity: float) -> float:
        risk_per_unit_dollars = signal.risk_per_unit * instrument.point_value
        if risk_per_unit_dollars <= 0:
            return 0.0
        n = max(int(np.floor(risk_dollars / risk_per_unit_dollars)), 0)
        if max_contracts is not None:
            n = min(n, max_contracts)
        return float(n)

    return _size


@dataclass
class _Order:
    """Bookkeeping for one pending (not yet filled) entry order."""

    signal: Signal
    eligible_idx: int
    expire_idx: int | None


@dataclass
class _OpenPosition:
    """Bookkeeping pairing a live :class:`PositionState` with its signal."""

    signal: Signal
    state: PositionState
    entry_slip_ticks: float


@dataclass
class _Event:
    """One native (stop/target) fill decided for the current bar."""

    reason: ExitReason
    qty: float
    price: float
    target_idx: int | None
    meta: dict = field(default_factory=dict)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


class BacktestEngine:
    """Replays signals against bars, bar by bar, with honest fill mechanics.

    Parameters
    ----------
    instrument:
        Contract spec and tick/point conversions.
    cost_model:
        Commission and slippage, see :mod:`lab.backtest.costs`.
    cfg:
        Lab-wide config; only ``cfg.pessimistic_intrabar`` and
        ``cfg.account_size`` are read here.
    max_concurrent:
        Positions that may be open at once in this run. Defaults to 1 --
        "one position at a time" is how a single discretionary account
        actually trades one setup.
    max_attempts_per_day:
        Cap on *filled* entries per CME trading day (``None`` = unlimited).
        Independent of any per-strategy cap enforced at signal-generation
        time (see ``lab.strategies.base``); either can bind first.
    """

    def __init__(
        self,
        instrument: Instrument,
        cost_model: CostModel,
        cfg: LabConfig,
        *,
        max_concurrent: int = 1,
        max_attempts_per_day: int | None = None,
    ) -> None:
        self.instrument = instrument
        self.cost_model = cost_model
        self.cfg = cfg
        self.max_concurrent = max_concurrent
        self.max_attempts_per_day = max_attempts_per_day

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        bars: pd.DataFrame,
        signals: Sequence[Signal],
        exit_policy: ExitPolicy,
        sizing: SizingFn,
        finer_bars: pd.DataFrame | None = None,
        *,
        strategy: str | None = None,
        version: str = "",
    ) -> BacktestResult:
        """Replay ``signals`` against ``bars`` and return a full result.

        Signals whose eligible fill bar never falls inside ``bars`` (decided
        at or after the last timestamp) simply never fill and are not
        recorded as skipped -- there is nothing to skip; they never became
        live. ``strategy`` defaults to the (required-homogeneous) name
        carried by the signals themselves.
        """
        if len(bars) == 0:
            raise ValueError("bars must be non-empty")
        symbol = self.instrument.symbol
        for s in signals:
            if s.symbol and s.symbol != symbol:
                raise ValueError(f"signal for {s.symbol!r} passed to engine configured for {symbol!r}")
        strat_names = {s.strategy for s in signals if s.strategy}
        if strategy is None:
            if len(strat_names) > 1:
                raise ValueError(f"signals carry mixed strategy names: {sorted(strat_names)}")
            strategy = next(iter(strat_names), "")

        index = bars.index
        freq = index.to_series().diff().median()
        if pd.isna(freq) or freq <= pd.Timedelta(0):
            freq = pd.Timedelta(minutes=1)

        orders: list[_Order] = []
        for s in sorted(signals, key=lambda sig: sig.ts):
            eligible_idx = int(index.searchsorted(s.ts, side="right"))
            if eligible_idx >= len(index):
                continue
            expire_idx = None
            if s.valid_until is not None:
                if s.valid_until < index[eligible_idx]:
                    continue
                expire_idx = int(index.searchsorted(s.valid_until, side="right")) - 1
            orders.append(_Order(signal=s, eligible_idx=eligible_idx, expire_idx=expire_idx))

        pending: list[_Order] = []
        open_positions: list[_OpenPosition] = []
        trades: list[Trade] = []
        skipped: list[dict] = []
        attempts_today: dict[tuple, int] = {}
        realised_pnl = 0.0
        order_ptr = 0
        n_ambiguous_finer = 0
        n_ambiguous_pessimistic = 0

        for i in range(len(bars)):
            ts = index[i]
            bar = bars.iloc[i]
            ctx = ExitContext(instrument=self.instrument, bars=bars.iloc[: i + 1], now=ts)

            # 1) manage existing positions against this bar
            still_open: list[_OpenPosition] = []
            for op in open_positions:
                new_trades, amb_finer, amb_pess = self._advance_position(
                    op, bar, ts, i, exit_policy, ctx, finer_bars, freq
                )
                trades.extend(new_trades)
                realised_pnl += sum(t.pnl for t in new_trades)
                n_ambiguous_finer += amb_finer
                n_ambiguous_pessimistic += amb_pess
                if op.state.remaining_qty > 1e-9:
                    still_open.append(op)
            open_positions = still_open

            # 2) newly-eligible orders join the pending queue
            while order_ptr < len(orders) and orders[order_ptr].eligible_idx == i:
                pending.append(orders[order_ptr])
                order_ptr += 1

            # 3) try to fill pending orders against this bar
            still_pending: list[_Order] = []
            for order in pending:
                if order.expire_idx is not None and i > order.expire_idx:
                    skipped.append(self._skip(order.signal, "expired_unfilled", ts))
                    continue
                touched, gapped = self._entry_touch(order.signal, bar)
                if not touched:
                    still_pending.append(order)
                    continue

                day = trading_day(ts)
                key = (order.signal.symbol or symbol, day)
                n_today = attempts_today.get(key, 0)
                if self.max_attempts_per_day is not None and n_today >= self.max_attempts_per_day:
                    skipped.append(self._skip(order.signal, "max_attempts_per_day", ts))
                    continue
                if len(open_positions) >= self.max_concurrent:
                    skipped.append(self._skip(order.signal, "capacity_blocked", ts))
                    continue

                equity = self.cfg.account_size + realised_pnl
                qty = sizing(order.signal, self.instrument, equity)
                if qty <= 0:
                    skipped.append(self._skip(order.signal, "sizing_zero_qty", ts))
                    continue

                price, slip_ticks = self._fill_price_for_entry(order.signal, bar, gapped)
                targets, weights = exit_policy.initial_targets(order.signal, ctx)
                if not targets:
                    targets = order.signal.targets
                    weights = order.signal.target_weights
                if targets and weights is None:
                    weights = tuple(1.0 / len(targets) for _ in targets)
                state = PositionState(
                    symbol=symbol,
                    direction=order.signal.direction,
                    entry_ts=ts,
                    entry_price=price,
                    initial_qty=qty,
                    remaining_qty=qty,
                    stop=order.signal.stop,
                    initial_risk_per_unit=order.signal.risk_per_unit,
                    targets=tuple(targets),
                    target_weights=tuple(weights) if weights else (),
                    targets_filled=tuple(False for _ in targets),
                    high_water=price,
                    low_water=price,
                    tag=order.signal.tag,
                    meta=dict(order.signal.meta),
                )
                open_positions.append(_OpenPosition(signal=order.signal, state=state, entry_slip_ticks=slip_ticks))
                attempts_today[key] = n_today + 1
            pending = still_pending

        # anything still open at data end closes at the last bar's close
        last_ts = index[-1]
        last_close = float(bars.iloc[-1]["close"])
        for op in open_positions:
            trades.append(
                self._close_slice(
                    op, op.state.remaining_qty, last_close, last_ts, ExitReason.DATA_END,
                    exit_slip_ticks=0.0, meta={"note": "position still open at data end"},
                )
            )
        for order in pending:
            skipped.append(self._skip(order.signal, "data_ended_before_fill", index[-1]))

        equity = equity_curve(trades)
        stats = dict(compute_stats(trades, equity, start=index[0], end=index[-1]))
        stats["ambiguous_bars_resolved_by_finer_bars"] = n_ambiguous_finer
        stats["ambiguous_bars_resolved_by_pessimistic_default"] = n_ambiguous_pessimistic
        stats["ambiguous_bars_total"] = n_ambiguous_finer + n_ambiguous_pessimistic

        return BacktestResult(
            trades=trades,
            equity=equity,
            strategy=strategy or "",
            version=version,
            symbol=symbol,
            start=index[0],
            end=index[-1],
            params={
                "max_concurrent": self.max_concurrent,
                "max_attempts_per_day": self.max_attempts_per_day,
                "commission_round_turn": self.cost_model.commission_round_turn,
                "slippage_ticks": self.cost_model.slippage_ticks,
                "pessimistic_intrabar": self.cfg.pessimistic_intrabar,
                "finer_bars_supplied": finer_bars is not None,
            },
            stats=stats,
            data_fingerprint=fingerprint(bars),
            skipped=skipped,
        )

    # ------------------------------------------------------------------
    # entry fills
    # ------------------------------------------------------------------

    def _skip(self, signal: Signal, reason: str, ts: pd.Timestamp) -> dict:
        return {
            "ts": ts,
            "signal_ts": signal.ts,
            "symbol": signal.symbol or self.instrument.symbol,
            "strategy": signal.strategy,
            "tag": signal.tag,
            "direction": signal.direction,
            "entry_type": signal.entry_type,
            "reason": reason,
        }

    def _entry_touch(self, signal: Signal, bar: pd.Series) -> tuple[bool, bool]:
        """``(touched, gapped_through)`` for one pending entry order on ``bar``."""
        d = signal.direction
        price = signal.entry
        if signal.entry_type == "market":
            return True, False
        if signal.entry_type == "limit":
            touched = (d == LONG and bar["low"] <= price) or (d != LONG and bar["high"] >= price)
            return bool(touched), False  # limits never gap-favour; see costs.py
        if signal.entry_type == "stop":
            touched = (d == LONG and bar["high"] >= price) or (d != LONG and bar["low"] <= price)
            gapped = (d == LONG and bar["open"] >= price) or (d != LONG and bar["open"] <= price)
            return bool(touched), bool(gapped)
        raise ValueError(f"unknown entry_type {signal.entry_type!r}")

    def _fill_price_for_entry(self, signal: Signal, bar: pd.Series, gapped_through: bool) -> tuple[float, float]:
        d = signal.direction
        if signal.entry_type == "market":
            base = float(bar["open"])
            ctx = SlippageContext("market", float(bar["high"] - bar["low"]), None, None)
            ticks = self.cost_model.slippage_ticks_for(ctx)
            return self.instrument.slip(base, d, ticks), ticks
        if signal.entry_type == "limit":
            return self.instrument.round_to_tick(signal.entry), 0.0
        if signal.entry_type == "stop":
            base = float(bar["open"]) if gapped_through else signal.entry
            ctx = SlippageContext("stop", float(bar["high"] - bar["low"]), None, None)
            ticks = self.cost_model.slippage_ticks_for(ctx)
            return self.instrument.slip(base, d, ticks), ticks
        raise ValueError(f"unknown entry_type {signal.entry_type!r}")

    # ------------------------------------------------------------------
    # position lifecycle
    # ------------------------------------------------------------------

    def _advance_position(
        self,
        op: _OpenPosition,
        bar: pd.Series,
        ts: pd.Timestamp,
        i: int,
        exit_policy: ExitPolicy,
        ctx: ExitContext,
        finer_bars: pd.DataFrame | None,
        freq: pd.Timedelta,
    ) -> tuple[list[Trade], int, int]:
        state = op.state
        d = state.direction
        state.high_water = bar["high"] if pd.isna(state.high_water) else max(state.high_water, bar["high"])
        state.low_water = bar["low"] if pd.isna(state.low_water) else min(state.low_water, bar["low"])
        state.bars_held += 1

        trades: list[Trade] = []
        events, amb_finer, amb_pess = self._resolve_bar(state, bar, ts, finer_bars, freq)
        for ev in events:
            trades.append(self._apply_event(op, ev, ts))
            if state.remaining_qty <= 1e-9:
                break

        if state.remaining_qty > 1e-9:
            decision = exit_policy.check(op.signal, state, bar, ctx)
            if decision is not None:
                if decision.new_stop is not None:
                    if (d > 0 and decision.new_stop > state.stop) or (d < 0 and decision.new_stop < state.stop):
                        state.stop = decision.new_stop
                if decision.is_exit:
                    qty = state.remaining_qty if decision.qty is None else min(decision.qty, state.remaining_qty)
                    price = decision.price if decision.price is not None else float(bar["close"])
                    slips = decision.reason not in _NO_SLIP_REASONS
                    slip_ticks = 0.0
                    if slips:
                        sctx = SlippageContext(str(decision.reason), float(bar["high"] - bar["low"]), None, None)
                        slip_ticks = self.cost_model.slippage_ticks_for(sctx)
                        price = self.instrument.slip(price, -d, slip_ticks)
                    trades.append(
                        self._close_slice(op, qty, price, ts, decision.reason, exit_slip_ticks=slip_ticks, meta=dict(decision.meta))
                    )
        return trades, amb_finer, amb_pess

    def _bar_touches(self, state: PositionState, bar: pd.Series) -> tuple[bool, list[int]]:
        d = state.direction
        stop_touched = (d > 0 and bar["low"] <= state.stop) or (d < 0 and bar["high"] >= state.stop)
        touched_targets = [
            idx
            for idx, (tgt, filled) in enumerate(zip(state.targets, state.targets_filled))
            if not filled and ((d > 0 and bar["high"] >= tgt) or (d < 0 and bar["low"] <= tgt))
        ]
        return bool(stop_touched), touched_targets

    def _stop_event(self, state: PositionState, bar: pd.Series, meta: dict | None = None) -> _Event:
        d = state.direction
        gapped = (d > 0 and bar["open"] <= state.stop) or (d < 0 and bar["open"] >= state.stop)
        base = float(bar["open"]) if gapped else state.stop
        return _Event(reason=ExitReason.STOP, qty=state.remaining_qty, price=base, target_idx=None, meta=dict(meta or {}))

    def _target_events(self, state: PositionState, bar: pd.Series, idxs: list[int]) -> list[_Event]:
        d = state.direction
        events: list[_Event] = []
        remaining = state.remaining_qty
        for idx in idxs:
            if remaining <= 1e-9:
                break
            tgt = state.targets[idx]
            weight = state.target_weights[idx] if state.target_weights else 1.0 / len(state.targets)
            qty = min(state.initial_qty * weight, remaining)
            gapped = (d > 0 and bar["open"] >= tgt) or (d < 0 and bar["open"] <= tgt)
            price = float(bar["open"]) if gapped else tgt
            events.append(_Event(reason=ExitReason.TARGET, qty=qty, price=price, target_idx=idx))
            remaining -= qty
        return events

    def _resolve_bar(
        self, state: PositionState, bar: pd.Series, ts: pd.Timestamp, finer_bars: pd.DataFrame | None, freq: pd.Timedelta
    ) -> tuple[list[_Event], int, int]:
        stop_touched, touched_targets = self._bar_touches(state, bar)
        if not stop_touched and not touched_targets:
            return [], 0, 0
        if stop_touched and not touched_targets:
            return [self._stop_event(state, bar)], 0, 0
        if touched_targets and not stop_touched:
            return self._target_events(state, bar, touched_targets), 0, 0

        # ambiguous: both a stop and at least one target are in range this bar
        if finer_bars is not None:
            events = self._resolve_with_finer(state, bar, ts, finer_bars, freq)
            if events is not None:
                for ev in events:
                    ev.meta["resolution"] = "finer_bars"
                return events, 1, 0

        # pessimistic default (or finer_bars had no usable data for this bar)
        if self.cfg.pessimistic_intrabar:
            ev = self._stop_event(state, bar, meta={"resolution": "pessimistic_default"})
            return [ev], 0, 1
        # optimistic stress setting: credit the touched targets first, then
        # the stop takes whatever remains -- only reachable when
        # cfg.pessimistic_intrabar is explicitly turned off for a stress run.
        events = self._target_events(state, bar, touched_targets)
        remaining = state.remaining_qty - sum(e.qty for e in events)
        if remaining > 1e-9:
            stub = dc_replace(state, remaining_qty=remaining)
            events.append(self._stop_event(stub, bar, meta={"resolution": "pessimistic_default"}))
        for ev in events:
            ev.meta.setdefault("resolution", "pessimistic_default")
        return events, 0, 1

    def _resolve_with_finer(
        self, state: PositionState, bar: pd.Series, ts: pd.Timestamp, finer_bars: pd.DataFrame, freq: pd.Timedelta
    ) -> list[_Event] | None:
        """Replay sub-bars inside ``[ts, ts + freq)`` to sequence stop vs target.

        Returns ``None`` (meaning "fall back to the pessimistic default") when
        ``finer_bars`` has no rows covering this coarse bar -- silently
        trusting an absent slice would be worse than falling back honestly.
        """
        window = finer_bars.loc[(finer_bars.index >= ts) & (finer_bars.index < ts + freq)]
        if window.empty:
            return None

        # work on a scratch copy so a mid-replay abort doesn't mutate state
        scratch = dc_replace(state)
        events: list[_Event] = []
        for _, fbar in window.iterrows():
            if scratch.remaining_qty <= 1e-9:
                break
            stop_touched, touched = self._bar_touches(scratch, fbar)
            if not stop_touched and not touched:
                continue
            if stop_touched and touched:
                # still ambiguous at finer resolution: stop wins this sub-bar
                ev = self._stop_event(scratch, fbar)
                events.append(ev)
                scratch.remaining_qty -= ev.qty
                break
            if stop_touched:
                ev = self._stop_event(scratch, fbar)
                events.append(ev)
                scratch.remaining_qty -= ev.qty
                break
            for ev in self._target_events(scratch, fbar, touched):
                events.append(ev)
                scratch.remaining_qty -= ev.qty
                flags = list(scratch.targets_filled)
                flags[ev.target_idx] = True
                scratch.targets_filled = tuple(flags)
        if not events:
            return None  # coarse bar signalled a touch the finer slice never confirmed
        return events

    def _apply_event(self, op: _OpenPosition, ev: _Event, ts: pd.Timestamp) -> Trade:
        state = op.state
        if ev.target_idx is not None:
            flags = list(state.targets_filled)
            flags[ev.target_idx] = True
            state.targets_filled = tuple(flags)
        slips = ev.reason not in _NO_SLIP_REASONS
        slip_ticks = 0.0
        price = ev.price
        if slips:
            sctx = SlippageContext(str(ev.reason), 0.0, None, None)
            slip_ticks = self.cost_model.slippage_ticks_for(sctx)
            price = self.instrument.slip(price, -state.direction, slip_ticks)
        return self._close_slice(op, ev.qty, price, ts, ev.reason, exit_slip_ticks=slip_ticks, meta=ev.meta)

    def _close_slice(
        self,
        op: _OpenPosition,
        qty: float,
        price: float,
        ts: pd.Timestamp,
        reason: ExitReason,
        *,
        exit_slip_ticks: float,
        meta: dict | None = None,
    ) -> Trade:
        """Book one exit slice as a :class:`Trade` and shrink the position.

        ``price`` must already be the final fill price (slippage included, if
        any). ``exit_slip_ticks`` is purely for the cost-drag breakdown --
        it is *not* re-applied to ``price`` here.
        """
        state = op.state
        signal = op.signal
        qty = min(qty, state.remaining_qty)
        inst = self.instrument
        commission = self.cost_model.commission_for_qty(qty, state.initial_qty)
        entry_slip_dollars = inst.dollars(op.entry_slip_ticks * inst.tick_size, qty)
        exit_slip_dollars = inst.dollars(exit_slip_ticks * inst.tick_size, qty)
        slippage_cost = entry_slip_dollars + exit_slip_dollars
        gross = state.direction * (price - state.entry_price) * qty * inst.point_value
        pnl = gross - commission
        risk_dollars = state.initial_risk_per_unit * qty * inst.point_value

        favourable = state.favourable_excursion()
        adverse = (
            max(0.0, state.entry_price - state.low_water)
            if state.direction > 0
            else max(0.0, state.high_water - state.entry_price)
        )
        mfe = inst.dollars(favourable, state.initial_qty)
        mae = -inst.dollars(adverse, state.initial_qty)

        trade_meta = {"entry_type": signal.entry_type, "signal_meta": dict(signal.meta)}
        trade_meta.update(meta or {})

        state.remaining_qty -= qty
        return Trade(
            symbol=state.symbol,
            strategy=signal.strategy,
            direction=state.direction,
            entry_ts=state.entry_ts,
            entry_price=state.entry_price,
            exit_ts=ts,
            exit_price=price,
            qty=qty,
            pnl=pnl,
            commission=commission,
            slippage_cost=slippage_cost,
            risk_dollars=risk_dollars,
            exit_reason=reason,
            mfe=mfe,
            mae=mae,
            bars_held=state.bars_held,
            tag=state.tag,
            signal_ts=signal.ts,
            meta=trade_meta,
        )
