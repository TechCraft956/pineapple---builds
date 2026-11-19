"""Trade journal: importing executions, recording intent-vs-reality, and
turning measured fills back into research cost assumptions.

See the individual modules for the detail:

* :mod:`lab.journal.importer` -- platform CSV/Excel/Parquet/JSON export -> Trades.
* :mod:`lab.journal.journal` -- the append-only ledger.
* :mod:`lab.journal.adherence` -- reconcile signals against executions.
* :mod:`lab.journal.costs_measure` -- realised commission/slippage -> config override.
"""

from __future__ import annotations

from lab.journal.adherence import (
    AdherenceScore,
    MatchedPair,
    MatchTolerance,
    ReconcileResult,
    adherence_score,
    hesitation_analysis,
    reconcile,
    slippage_report,
)
from lab.journal.costs_measure import (
    CostEstimate,
    build_cost_overrides_yaml,
    measure_costs,
)
from lab.journal.importer import ImportResult, import_executions, normalise_symbol
from lab.journal.journal import JOURNAL_COLUMNS, Journal

__all__ = [
    "AdherenceScore",
    "MatchedPair",
    "MatchTolerance",
    "ReconcileResult",
    "adherence_score",
    "hesitation_analysis",
    "reconcile",
    "slippage_report",
    "CostEstimate",
    "build_cost_overrides_yaml",
    "measure_costs",
    "ImportResult",
    "import_executions",
    "normalise_symbol",
    "JOURNAL_COLUMNS",
    "Journal",
]
