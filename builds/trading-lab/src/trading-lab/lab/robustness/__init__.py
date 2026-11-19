"""Robustness checks: sensitivity to parameters/costs, drop-the-best, and regime stability.

These are the checks that answer "would I still trust this if I were a
little bit wrong" -- about the exact parameters chosen
(:mod:`lab.robustness.sensitivity`), about whether a few outlier trades or
days are carrying the headline number (:mod:`lab.robustness.dropn`), and
about whether the edge holds across regime, session, volatility and
instrument or only in one lucky slice of the data
(:mod:`lab.robustness.regimes`).

Nothing in this package imports :mod:`lab.backtest` or :mod:`lab.strategies`
at module scope -- every function takes ``Trade``/``BacktestResult`` objects
or an injected ``run_fn`` callable as input, and the one place that does want
``lab.backtest.metrics.compute_stats`` (:mod:`lab.robustness._common`)
imports it lazily with a graceful fallback.
"""

from __future__ import annotations

from lab.robustness.dropn import DropBestResult, drop_best
from lab.robustness.regimes import (
    RegimeComparison,
    StabilityVerdict,
    compare_regimes,
    stability_verdict,
)
from lab.robustness.sensitivity import (
    FragilityScore,
    fragility_score,
    parameter_sweep,
    stress_costs,
)

__all__ = [
    "DropBestResult",
    "drop_best",
    "RegimeComparison",
    "StabilityVerdict",
    "compare_regimes",
    "stability_verdict",
    "FragilityScore",
    "fragility_score",
    "parameter_sweep",
    "stress_costs",
]
