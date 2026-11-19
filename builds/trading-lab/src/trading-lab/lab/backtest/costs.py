"""Execution cost model: commission, slippage and the hooks to stress both.

A backtest is only as trustworthy as its cost assumptions. This module keeps
them in one small, inspectable place so a reader can audit exactly what every
fill paid, and so a sensitivity run (:meth:`CostModel.stress`) never has to
touch strategy or engine code.

Modelling assumption -- read before trusting a number
-------------------------------------------------------
Market and stop orders are assumed to *cross the spread and walk the book* on
every fill, so they always pay slippage. Limit orders are assumed to rest in
the book and only pay the exchange's queue-priority tax, which we approximate
as zero: a limit fills at exactly its stated price, never better. This is
optimistic for a limit that only fills because price *traded through* it (a
fast, thin market can blow through a resting limit and never actually give you
a fill at that price, or give you a worse one via slippage on the exchange's
matching engine) -- see :mod:`lab.backtest.engine` for exactly when a limit is
deemed "filled by trade-through" versus "touched but not filled". The lab
treats every trade-through as a full fill at the limit price with no slippage,
which biases small-edge, high-frequency limit strategies to look better than
they will trade live. If a strategy's edge is thin and mostly limit-filled,
rerun it with ``stress(extra_slip_ticks=...)`` applied to limit-adjacent
scenarios before trusting the number, or treat limit fills as market fills in
a dedicated pessimistic pass.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

__all__ = ["SlippageContext", "SlippageFn", "CostModel", "default_slippage_fn"]


@dataclass(frozen=True, slots=True)
class SlippageContext:
    """Everything a custom slippage function is allowed to condition on.

    Kept narrow and serialisable on purpose -- a slippage model that needs more
    than "what kind of order, how wide/fast is the tape, what time is it" is
    almost certainly overfitting to the backtest rather than modelling the
    market.
    """

    order_type: str  # "market" | "stop" | "limit" (limit is passed for completeness; unused by default)
    bar_range: float  # high - low of the fill bar, in price units
    atr: float | None  # instrument ATR at fill time, price units, if known
    time_of_day: object  # datetime.time in the instrument's session_tz


class SlippageFn(Protocol):
    def __call__(self, ctx: SlippageContext, base_ticks: float) -> float:
        """Return the number of ticks of adverse slippage to apply."""
        ...


def default_slippage_fn(ctx: SlippageContext, base_ticks: float) -> float:
    """Flat slippage: ``base_ticks`` regardless of context.

    The honest default. Anything fancier (range- or time-of-day-scaled
    slippage) is opt-in via :attr:`CostModel.slippage_fn` so a reader always
    knows whether a run used the flat assumption or a stressed one.
    """
    return base_ticks


@dataclass(frozen=True, slots=True)
class CostModel:
    """Commission and slippage assumptions applied by the backtest engine.

    Attributes
    ----------
    commission_round_turn:
        All-in dollars per contract for one full round turn (open + close).
        Charged once per contract when a trade fully closes; on a partial
        scale-out the *fraction of the round turn* corresponding to the
        contracts leaving is charged at that exit (see engine for the split),
        so total commission on a trade always sums to
        ``commission_round_turn * qty`` regardless of how many exits it took.
    slippage_ticks:
        Base adverse slippage, in ticks, applied to *each side* (entry and
        exit) of a market or stop fill. Limit fills pay zero slippage by
        construction -- see module docstring.
    slippage_fn:
        Hook to make slippage a function of order type, bar range/ATR and
        time of day, for stress runs (e.g. wider slippage around news, on
        thin overnight bars, or on stop orders vs market orders). Defaults to
        :func:`default_slippage_fn`, which ignores context and returns
        ``slippage_ticks`` unchanged.
    """

    commission_round_turn: float
    slippage_ticks: float = 1.0
    slippage_fn: SlippageFn = default_slippage_fn

    def slippage_ticks_for(self, ctx: SlippageContext) -> float:
        """Ticks of adverse slippage for one fill, given ``ctx``."""
        return self.slippage_fn(ctx, self.slippage_ticks)

    def commission_for_qty(self, qty: float, total_qty: float) -> float:
        """Commission charged when ``qty`` of ``total_qty`` contracts exit.

        ``commission_round_turn`` is already a *per-contract* figure (see the
        attribute docstring), so a slice's commission is simply
        ``commission_round_turn * qty`` -- summed across however many partial
        exits a position took, that always totals
        ``commission_round_turn * total_qty``, exactly the invariant this
        method exists to guarantee. ``total_qty`` is taken only to validate
        that a real position exists (guarding the zero/negative case below),
        not as a divisor -- dividing by it here would collapse every trade's
        total commission to a flat ``commission_round_turn`` regardless of
        contract count, which is not what "per-contract" means.
        """
        if total_qty <= 0:
            return 0.0
        return self.commission_round_turn * qty

    def stress(self, commission_mult: float = 1.0, extra_slip_ticks: float = 0.0) -> "CostModel":
        """Return a modified copy for sensitivity testing.

        ``commission_mult`` scales commission; ``extra_slip_ticks`` is added on
        top of the base ``slippage_ticks`` (not multiplied), so a stress run
        reads as "N extra ticks of adverse fill" regardless of the base.
        """
        return replace(
            self,
            commission_round_turn=self.commission_round_turn * commission_mult,
            slippage_ticks=self.slippage_ticks + extra_slip_ticks,
        )
