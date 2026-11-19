"""The account risk engine: would this strategy have survived the prop-firm rules?

**Read this before trusting any number this package produces.** Prop-firm
rules change without notice. Every rule this module knows about is a field on
:class:`~lab.risk.rules.AccountRules`, every preset carries a ``source_note``
explaining exactly which numbers were supplied by the user and which are
unverified placeholders, and :data:`lab.risk.rules.RULES_AS_OF` stamps the
vintage. Re-verify against the firm's current rulebook before trusting a
breach probability, a payout-eligibility claim, or a sizing recommendation
derived from these presets.

Submodules
----------
:mod:`lab.risk.rules`
    Rule definitions and presets (``AccountRules``, ``PayoutPath``, Topstep
    Combine/Funded/Express Funded presets at 50K/100K/150K).
:mod:`lab.risk.account`
    :class:`~lab.risk.account.AccountSimulator` -- the deterministic
    trade-by-trade state machine (trailing MLL, unrealised-drawdown breach,
    daily lockout, payout eligibility).
:mod:`lab.risk.sizing`
    Contracts from a risk budget, MLL-aware position caps, and the inverse
    question: how large can risk-per-trade be before N losses in a row
    breach the account.
:mod:`lab.risk.montecarlo`
    Deterministic (seeded) bootstrap resampling -- iid/block/stationary --
    replayed through :class:`~lab.risk.account.AccountSimulator`.
:mod:`lab.risk.survival`
    The questions a trader actually asks, each as a tidy
    :class:`pandas.DataFrame`: survival curves, sessions-to-payout, daily-stop
    sweeps, consecutive-loss stress tests, account-size comparisons, and
    whether the trade distribution can even satisfy the consistency payout
    rule.

This package only depends on :mod:`lab.core` (``Trade``, ``trading_day``).
It does not import :mod:`lab.backtest` or :mod:`lab.strategies` at module
scope, so it can be tested and used against any trade sequence -- hand-built,
backtested, or from the live journal -- independently of how that sequence
was produced.
"""

from __future__ import annotations

from lab.risk.account import AccountRun, AccountSimulator, PayoutEligibility, SkippedTrade
from lab.risk.montecarlo import (
    BootstrapMethod,
    MonteCarloResult,
    bootstrap_trades,
    permute_order,
    simulate_paths,
)
from lab.risk.rules import (
    PRESETS,
    RULES_AS_OF,
    AccountRules,
    LockAt,
    PayoutPath,
    PayoutPathKind,
    TOPSTEP_COMBINE_50K,
    TOPSTEP_COMBINE_100K,
    TOPSTEP_COMBINE_150K,
    TOPSTEP_EXPRESS_FUNDED_50K,
    TOPSTEP_EXPRESS_FUNDED_100K,
    TOPSTEP_EXPRESS_FUNDED_150K,
    TOPSTEP_FUNDED_50K,
    TOPSTEP_FUNDED_100K,
    TOPSTEP_FUNDED_150K,
    TrailOn,
    get_preset,
)
from lab.risk.sizing import (
    SizingResult,
    contracts_from_risk_budget,
    fixed_contracts,
    fixed_fractional_contracts,
    max_safe_risk,
    mll_aware_cap,
)
from lab.risk.survival import (
    account_size_comparison,
    consecutive_loss_analysis,
    consistency_analysis,
    daily_stop_sweep,
    frequency_analysis,
    post_payout_buffer,
    sessions_to_payout,
    survival_curve,
)

__all__ = [
    # rules
    "RULES_AS_OF",
    "TrailOn",
    "LockAt",
    "PayoutPathKind",
    "PayoutPath",
    "AccountRules",
    "PRESETS",
    "get_preset",
    "TOPSTEP_COMBINE_50K",
    "TOPSTEP_COMBINE_100K",
    "TOPSTEP_COMBINE_150K",
    "TOPSTEP_FUNDED_50K",
    "TOPSTEP_FUNDED_100K",
    "TOPSTEP_FUNDED_150K",
    "TOPSTEP_EXPRESS_FUNDED_50K",
    "TOPSTEP_EXPRESS_FUNDED_100K",
    "TOPSTEP_EXPRESS_FUNDED_150K",
    # account
    "AccountSimulator",
    "AccountRun",
    "PayoutEligibility",
    "SkippedTrade",
    # sizing
    "SizingResult",
    "contracts_from_risk_budget",
    "fixed_fractional_contracts",
    "fixed_contracts",
    "mll_aware_cap",
    "max_safe_risk",
    # montecarlo
    "BootstrapMethod",
    "MonteCarloResult",
    "bootstrap_trades",
    "permute_order",
    "simulate_paths",
    # survival
    "survival_curve",
    "sessions_to_payout",
    "post_payout_buffer",
    "daily_stop_sweep",
    "frequency_analysis",
    "consecutive_loss_analysis",
    "account_size_comparison",
    "consistency_analysis",
]
