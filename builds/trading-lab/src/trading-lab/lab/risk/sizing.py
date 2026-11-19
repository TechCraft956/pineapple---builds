"""Position sizing: how many contracts, and how much risk-per-trade is safe.

Two directions of the same question live here. The forward direction --
"given a risk budget, how many contracts" -- is :func:`contracts_from_risk_budget`,
:func:`fixed_fractional_contracts`, :func:`fixed_contracts` and
:func:`mll_aware_cap`. The inverse direction -- "given the drawdown I have
left, how large can my risk-per-trade be before a bad streak breaches the
account" -- is :func:`max_safe_risk`, and it is the more useful question in
practice: most blown accounts were sized for the *average* trade, not for the
five-in-a-row losing streak that showed up in month two.

Every function here is a pure calculation. None of them touch
:mod:`lab.risk.account` -- sizing decisions are an input to a backtest/live
strategy, not an output of the account simulator, even though
:func:`mll_aware_cap` is meant to be fed live headroom numbers
(:data:`~lab.risk.account.AccountRun.min_mll_headroom` or a point-in-time
headroom you compute yourself) at the point where you decide *this* trade's
size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lab.risk.rules import AccountRules

__all__ = [
    "SizingResult",
    "contracts_from_risk_budget",
    "fixed_fractional_contracts",
    "fixed_contracts",
    "mll_aware_cap",
    "max_safe_risk",
]


@dataclass(frozen=True, slots=True)
class SizingResult:
    """Contract count plus the arithmetic that produced it, for auditability.

    ``capped_by`` is ``None`` when the risk budget divided evenly (or the
    scheme has no notion of a budget, e.g. :func:`fixed_contracts`),
    ``"rounding"`` when whole-contract flooring left budget unused, and
    ``"mll_headroom"`` when :func:`mll_aware_cap` reduced an uncapped request.
    """

    contracts: int
    risk_dollars_per_contract: float
    risk_dollars_requested: float
    risk_dollars_used: float
    capped_by: str | None

    @property
    def was_capped(self) -> bool:
        return self.capped_by is not None


def contracts_from_risk_budget(
    risk_budget_dollars: float, risk_per_contract_dollars: float,
) -> SizingResult:
    """How many whole contracts a flat dollar risk budget buys.

    ``risk_per_contract_dollars`` is the dollar loss for *one* contract if the
    stop is hit -- typically ``instrument.dollars(stop_distance_points)``.
    Floors down: a budget that does not divide evenly leaves the remainder
    unspent rather than rounding up into more risk than requested.
    """
    if risk_per_contract_dollars <= 0:
        raise ValueError("risk_per_contract_dollars must be > 0")
    if risk_budget_dollars < 0:
        raise ValueError("risk_budget_dollars must be >= 0")
    n = int(risk_budget_dollars // risk_per_contract_dollars)
    used = n * risk_per_contract_dollars
    capped = "rounding" if used < risk_budget_dollars else None
    return SizingResult(n, risk_per_contract_dollars, risk_budget_dollars, used, capped)


def fixed_fractional_contracts(
    equity: float, fraction: float, risk_per_contract_dollars: float,
) -> SizingResult:
    """Risk a fixed fraction of *current* equity per trade.

    Re-derive the budget from live equity on every call -- this scheme is
    fixed-*fractional*, not fixed-dollar, so the contract count shrinks as
    equity draws down and grows as it compounds up.
    """
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    if equity < 0:
        raise ValueError("equity must be >= 0")
    return contracts_from_risk_budget(equity * fraction, risk_per_contract_dollars)


def fixed_contracts(n: int) -> SizingResult:
    """Trivial scheme: always trade exactly ``n`` contracts, no risk math at all.

    Exists so callers can swap sizing schemes without an if/else at the call
    site -- every scheme in this module returns the same :class:`SizingResult`
    shape.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    return SizingResult(
        contracts=n,
        risk_dollars_per_contract=math.nan,
        risk_dollars_requested=math.nan,
        risk_dollars_used=math.nan,
        capped_by=None,
    )


def mll_aware_cap(
    headroom_dollars: float,
    max_pct_of_headroom: float,
    risk_per_contract_dollars: float,
    *,
    uncapped: SizingResult | None = None,
) -> SizingResult:
    """Never risk more than ``max_pct_of_headroom`` of remaining MLL cushion.

    ``headroom_dollars`` is current equity minus the currently active MLL
    threshold -- a live version of ``AccountRun.min_mll_headroom``, computed
    at the moment sizing decision is made (negative headroom, i.e. already
    breached, floors the budget to zero rather than raising).

    If ``uncapped`` is supplied (e.g. the output of
    :func:`fixed_fractional_contracts`), returns whichever of the two is
    smaller, tagging the result ``"mll_headroom"`` only when this cap actually
    bound. Called on its own (no ``uncapped``), it just returns the MLL-derived
    cap directly.
    """
    if not 0 < max_pct_of_headroom <= 1:
        raise ValueError("max_pct_of_headroom must be in (0, 1]")
    if risk_per_contract_dollars <= 0:
        raise ValueError("risk_per_contract_dollars must be > 0")
    budget = max(headroom_dollars, 0.0) * max_pct_of_headroom
    capped_n = int(budget // risk_per_contract_dollars)

    if uncapped is None:
        used = capped_n * risk_per_contract_dollars
        return SizingResult(
            capped_n, risk_per_contract_dollars, budget, used,
            "rounding" if used < budget else None,
        )
    if capped_n < uncapped.contracts:
        used = capped_n * risk_per_contract_dollars
        return SizingResult(
            capped_n, risk_per_contract_dollars, uncapped.risk_dollars_requested, used,
            "mll_headroom",
        )
    return uncapped


def max_safe_risk(
    rules: AccountRules,
    headroom_dollars: float,
    worst_case_R: float,
    *,
    n_consecutive_losses: int = 5,
    commission_per_rt: float | None = None,
) -> float:
    """The inverse sizing question: what risk-per-trade survives a bad streak?

    Given the drawdown cushion left (``headroom_dollars``) and an assumption
    that ``n_consecutive_losses`` trades in a row each lose
    ``worst_case_R * risk_per_trade`` plus one round-turn of commission, solve
    for the largest ``risk_per_trade`` (in dollars) that still leaves the
    account inside its threshold after the streak.

    ``worst_case_R`` is a multiple of the *intended* risk: 1.0 models a clean
    stop-out, > 1.0 stress-tests slippage/gap-through-stop beyond the intended
    stop (which is exactly the situation ``Trade.r_multiple`` on a real losing
    trade already captures -- feed it the worst observed |r_multiple| among
    losers for a data-driven answer instead of a guess).

    This is a closed-form estimate for *sizing before the fact*, not a
    simulation -- for "did this specific historical sequence survive N losses
    in a row", use :func:`lab.risk.survival.consecutive_loss_analysis` instead.
    Returns 0.0 (not negative) when the streak's commission drag alone would
    already exceed available headroom.
    """
    if n_consecutive_losses <= 0:
        raise ValueError("n_consecutive_losses must be > 0")
    if worst_case_R <= 0:
        raise ValueError("worst_case_R must be > 0")
    commission = rules.commission_per_rt if commission_per_rt is None else commission_per_rt
    commission_drag = n_consecutive_losses * commission
    available = max(headroom_dollars, 0.0) - commission_drag
    if available <= 0:
        return 0.0
    return available / (n_consecutive_losses * worst_case_R)
