"""Composable exit policies.

The reason this module exists at all: "test each exit rule independently" is
supposed to be one loop over policy objects, never a fork of the strategy.
Every strategy in :mod:`lab.strategies` emits a :class:`~lab.core.types.Signal`
with a stop and (usually) an empty target ladder, then hands the *exit policy*
the job of deciding how the trade ever closes. Swapping ``FixedR(1.5)`` for
``AtrTrail(2.0, 14)`` on the same signal set requires touching nothing but the
call site.

Division of responsibility with the engine
-------------------------------------------
* The **hard protective stop** (``Signal.stop``, and anything a policy moves it
  to via :attr:`ExitDecision.new_stop`) is executed natively by
  :class:`lab.backtest.engine.BacktestEngine` -- gap handling, pessimistic
  intrabar resolution and ``finer_bars`` all apply to it. Exit policies never
  fabricate stop fills themselves; they only *propose new stop prices*
  (:class:`BreakevenAfterR`, :class:`AtrTrail`).
* **Targets** are also engine-native once a policy hands over a ladder via
  :meth:`ExitPolicy.initial_targets` -- the same gap/finer-bars/pessimistic
  machinery applies to them as to the stop, so a target and a stop in the same
  bar are resolved consistently.
* Everything else a policy wants to do -- close on a timer, close at session
  end, close because price reached a level that isn't a pre-declared target --
  is decided bar-by-bar in :meth:`ExitPolicy.check` and executed as a market
  fill (it pays slippage like any other market order; see
  :mod:`lab.backtest.costs`). :class:`OpposingLevel` is the one exception that
  fills at the level itself, not at market -- documented on the class.

Conflict resolution
--------------------
:class:`CompositeExit` may see several policies fire on the same bar (a time
stop and a trail both wanting to act). The rule is: **protective/stop-side
always wins**. Concretely, in one bar:

1. Any decision that is (or immediately produces, via a moved stop) a stop-side
   close beats every profit-taking or time-based close.
2. Among the rest, the earliest policy in the list the composite was built
   with wins -- list order *is* priority order, stated once here so nobody has
   to reverse-engineer it from behaviour.
3. Stop-tightening mutations (breakeven, trail) are never dropped just because
   another policy also wants to exit this bar: the tighter stop is always
   applied to the position, in addition to whatever exit decision wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np
import pandas as pd

from lab.core.instruments import Instrument
from lab.core.types import Direction, ExitReason, Signal

__all__ = [
    "ExitContext",
    "PositionState",
    "ExitDecision",
    "ExitPolicy",
    "FixedR",
    "MultiTargetR",
    "TimeStop",
    "SessionEnd",
    "OpposingLevel",
    "BreakevenAfterR",
    "AtrTrail",
    "CompositeExit",
]


@dataclass(frozen=True, slots=True)
class ExitContext:
    """Everything an exit policy may read, kept deliberately small.

    ``bars`` is truncated to timestamps ``<= now`` by the engine before it is
    handed to a policy -- an exit policy that reached past ``now`` would be
    exactly the lookahead bug the engine's own tests guard against, so the
    truncation happens once, upstream, rather than trusting every policy to
    slice correctly.
    """

    instrument: Instrument
    bars: pd.DataFrame  # index <= now, ascending
    now: pd.Timestamp


@dataclass(slots=True)
class PositionState:
    """Mutable state of one open position, as seen by exit policies.

    ``initial_risk_per_unit`` is fixed at entry (``|entry - initial stop|``)
    and never changes even if the stop is later moved -- R-multiples are
    always measured against the risk the strategy *intended* to take, per the
    contract on :class:`lab.core.types.Trade`.
    """

    symbol: str
    direction: Direction
    entry_ts: pd.Timestamp
    entry_price: float
    initial_qty: float
    remaining_qty: float
    stop: float
    initial_risk_per_unit: float
    targets: tuple[float, ...] = ()
    target_weights: tuple[float, ...] = ()
    targets_filled: tuple[bool, ...] = ()
    high_water: float = float("nan")  # best (favourable) price reached since entry
    low_water: float = float("nan")   # worst (adverse) price reached since entry
    bars_held: int = 0
    tag: str = ""
    meta: dict = field(default_factory=dict)

    def favourable_excursion(self) -> float:
        """Best move in the trade's favour so far, in price units, >= 0."""
        if self.direction > 0:
            return max(0.0, self.high_water - self.entry_price)
        return max(0.0, self.entry_price - self.low_water)

    def r_multiple_reached(self) -> float:
        if self.initial_risk_per_unit <= 0:
            return 0.0
        return self.favourable_excursion() / self.initial_risk_per_unit


@dataclass(frozen=True, slots=True)
class ExitDecision:
    """What an :class:`ExitPolicy` wants to happen after seeing one bar.

    A decision can carry an exit (``qty > 0``), a stop mutation
    (``new_stop`` set), or both -- a policy may simultaneously tighten a stop
    and close the position this same bar (e.g. an ATR trail whose new stop is
    immediately behind the current close). ``qty=None`` means "close all
    remaining size".
    """

    reason: ExitReason | None = None
    qty: float | None = None
    price: float | None = None  # None => engine fills at its own convention (market close)
    new_stop: float | None = None
    meta: dict = field(default_factory=dict)

    @property
    def is_exit(self) -> bool:
        return self.reason is not None and (self.qty is None or self.qty > 0)


class ExitPolicy(Protocol):
    """Contract every exit rule implements."""

    def initial_targets(
        self, signal: Signal, ctx: ExitContext
    ) -> tuple[tuple[float, ...], tuple[float, ...] | None]:
        """Return ``(targets, weights)`` to install at entry.

        Most policies that aren't about targets at all (``TimeStop``,
        ``SessionEnd``, ...) return ``((), None)``, meaning "I don't set
        targets" -- not "there are no targets", which is why
        :class:`CompositeExit` merges rather than overwrites.
        """
        ...

    def check(
        self,
        signal: Signal,
        position: PositionState,
        bar: pd.Series,
        ctx: ExitContext,
    ) -> ExitDecision | None:
        """Look at the latest bar and optionally act. Called once per open bar."""
        ...


# --------------------------------------------------------------------------
# Target-setting policies
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixedR(object):
    """Single target at ``r`` R-multiples from entry."""

    r: float

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (signal.r_multiple_price(self.r),), (1.0,)

    def check(self, signal, position, bar, ctx):
        return None  # target fill is engine-native


@dataclass(frozen=True, slots=True)
class MultiTargetR(object):
    """Scale out across several R-multiples with explicit weights.

    ``weights`` must sum to 1.0 (validated at construction, same rule
    :class:`~lab.core.types.Signal` enforces for ``target_weights``) so the
    reader never has to wonder whether the ladder accounts for 100% of size.
    """

    rs: tuple[float, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.rs) != len(self.weights):
            raise ValueError("rs and weights must be the same length")
        if not self.rs:
            raise ValueError("MultiTargetR needs at least one target")
        if abs(sum(self.weights) - 1.0) > 1e-9:
            raise ValueError(f"weights must sum to 1.0, got {sum(self.weights)}")

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        targets = tuple(signal.r_multiple_price(r) for r in self.rs)
        return targets, self.weights

    def check(self, signal, position, bar, ctx):
        return None  # target fills are engine-native


# --------------------------------------------------------------------------
# Time / calendar policies
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TimeStop(object):
    """Close whatever remains once ``minutes`` have elapsed since *fill*.

    Fires on the first bar whose timestamp is ``>= entry_ts + minutes``, and
    closes at that bar's close -- the honest "we decided to get out now, at
    the next price we can see" convention used throughout this module. It
    pays slippage like any market exit.
    """

    minutes: float

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (), None

    def check(self, signal, position, bar, ctx):
        elapsed = ctx.now - position.entry_ts
        if elapsed >= pd.Timedelta(minutes=self.minutes):
            return ExitDecision(reason=ExitReason.TIME_STOP, qty=None, price=float(bar["close"]))
        return None


@dataclass(frozen=True, slots=True)
class SessionEnd(object):
    """Flatten at or after a named session window's end.

    ``window`` is a :class:`lab.core.sessions.SessionWindow`; the policy
    closes on the first bar whose timestamp is ``>= window end`` for the
    *entry's* trading day (computed once via
    :func:`lab.core.sessions.window_bounds`, not recomputed per bar, so a
    trade that spans a trading-day roll still flattens against the day it was
    opened on).
    """

    window: object  # lab.core.sessions.SessionWindow, kept loosely typed to avoid an import cycle at module load

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (), None

    def check(self, signal, position, bar, ctx):
        from lab.core.sessions import trading_day, window_bounds  # local: avoid import cycle

        day = trading_day(position.entry_ts)
        _, end = window_bounds(self.window, day)
        if ctx.now >= end:
            return ExitDecision(reason=ExitReason.SESSION_END, qty=None, price=float(bar["close"]))
        return None


# --------------------------------------------------------------------------
# Level-based policy
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpposingLevel(object):
    """Exit when price reaches a level computed fresh each bar.

    ``level_fn(signal, ctx)`` returns the price (e.g. the opposite side of the
    Asia range, or the prior day's high/low) -- it is re-evaluated every bar
    so it can depend on data revealed since entry, but for the levels this lab
    actually uses (Asia range, prior-day levels) it is constant for the whole
    trading day.

    Fill convention: if the bar's high/low reaches the level, fill *at the
    level* (limit-style, no slippage) -- unless the bar's open already gapped
    through it in the trade's favour, in which case fill at the open, matching
    the engine's own gap-handling rule so this policy can't invent better fills
    than the native target logic would. Known limitation: unlike the engine's
    native stop/target handling, this check does not consult ``finer_bars``
    when the same bar also touches the stop, so an ambiguous bar here is always
    resolved pessimistically by :class:`CompositeExit` (stop wins) rather than
    by tick-level replay.
    """

    level_fn: Callable[[Signal, ExitContext], float]

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (), None

    def check(self, signal, position, bar, ctx):
        level = self.level_fn(signal, ctx)
        d = position.direction
        reached = (d > 0 and bar["high"] >= level) or (d < 0 and bar["low"] <= level)
        if not reached:
            return None
        gapped_through = (d > 0 and bar["open"] >= level) or (d < 0 and bar["open"] <= level)
        price = float(bar["open"]) if gapped_through else float(level)
        return ExitDecision(
            reason=ExitReason.OPPOSING_LEVEL, qty=None, price=price, meta={"level": float(level)}
        )


# --------------------------------------------------------------------------
# Stop-mutating policies
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreakevenAfterR(object):
    """Move the stop to entry once ``r`` R of favourable excursion is reached.

    Only ever tightens: if the current stop is already better than breakeven
    (e.g. a prior :class:`AtrTrail` already moved it further), this is a
    no-op, enforced in :meth:`check` rather than left to the caller.
    """

    r: float

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (), None

    def check(self, signal, position, bar, ctx):
        if position.r_multiple_reached() < self.r:
            return None
        be = position.entry_price
        improves = (position.direction > 0 and be > position.stop) or (
            position.direction < 0 and be < position.stop
        )
        if not improves:
            return None
        return ExitDecision(new_stop=be, meta={"trigger": "breakeven"})


@dataclass(frozen=True, slots=True)
class AtrTrail(object):
    """Trail the stop ``mult`` ATRs behind the best price reached.

    ATR is computed from ``ctx.bars`` (already truncated to ``<= now`` by the
    engine) over the trailing ``period`` bars using the standard
    high-low/high-prevclose/low-prevclose true range, simple-averaged. Only
    tightens the stop, never loosens it, so a volatility spike right after
    entry can't widen risk back out.
    """

    mult: float
    period: int = 14

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (), None

    def _atr(self, ctx: ExitContext) -> float | None:
        bars = ctx.bars
        if len(bars) < 2:
            return None
        window = bars.iloc[-(self.period + 1) :]
        prev_close = window["close"].shift(1)
        tr = pd.concat(
            [
                window["high"] - window["low"],
                (window["high"] - prev_close).abs(),
                (window["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        tr = tr.dropna()
        if tr.empty:
            return None
        return float(tr.mean())

    def check(self, signal, position, bar, ctx):
        atr = self._atr(ctx)
        if atr is None or not np.isfinite(atr) or atr <= 0:
            return None
        if position.direction > 0:
            candidate = position.high_water - self.mult * atr
            improves = candidate > position.stop
        else:
            candidate = position.low_water + self.mult * atr
            improves = candidate < position.stop
        if not improves:
            return None
        return ExitDecision(new_stop=candidate, meta={"trigger": "atr_trail", "atr": atr})


# --------------------------------------------------------------------------
# Composite
# --------------------------------------------------------------------------


class CompositeExit:
    """Combine several policies with deterministic conflict resolution.

    See the module docstring for the precedence rule. Construction order is
    priority order among non-stop exits; this is stated once here so it does
    not have to be reverse-engineered from behaviour.
    """

    def __init__(self, policies: list[ExitPolicy]):
        if not policies:
            raise ValueError("CompositeExit needs at least one policy")
        self.policies = list(policies)

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        for p in self.policies:
            targets, weights = p.initial_targets(signal, ctx)
            if targets:
                return targets, weights
        return (), None

    def check(self, signal: Signal, position: PositionState, bar: pd.Series, ctx: ExitContext) -> ExitDecision | None:
        decisions: list[ExitDecision] = []
        for p in self.policies:
            d = p.check(signal, position, bar, ctx)
            if d is not None:
                decisions.append(d)
        if not decisions:
            return None

        # Merge stop mutations: keep the tightest (most protective) new_stop.
        stop_mutations = [d.new_stop for d in decisions if d.new_stop is not None]
        merged_stop: float | None = None
        if stop_mutations:
            if position.direction > 0:
                merged_stop = max(stop_mutations)
            else:
                merged_stop = min(stop_mutations)

        exits = [d for d in decisions if d.is_exit]
        if not exits:
            return ExitDecision(new_stop=merged_stop) if merged_stop is not None else None

        stop_side = [d for d in exits if d.reason == ExitReason.STOP]
        winner = stop_side[0] if stop_side else exits[0]
        if merged_stop is not None and winner.new_stop is None:
            winner = ExitDecision(
                reason=winner.reason, qty=winner.qty, price=winner.price,
                new_stop=merged_stop, meta=winner.meta,
            )
        return winner
