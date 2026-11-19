"""Backtest engine: cost model, exit policies, execution engine, metrics."""

from lab.backtest.costs import CostModel, SlippageContext, SlippageFn, default_slippage_fn
from lab.backtest.engine import BacktestEngine, SizingFn, fixed_contracts, risk_based
from lab.backtest.exits import (
    AtrTrail,
    BreakevenAfterR,
    CompositeExit,
    ExitContext,
    ExitDecision,
    ExitPolicy,
    FixedR,
    MultiTargetR,
    OpposingLevel,
    PositionState,
    SessionEnd,
    TimeStop,
)
from lab.backtest.metrics import compute_stats, daily_pnl, empty_stats, equity_curve

__all__ = [
    "CostModel", "SlippageContext", "SlippageFn", "default_slippage_fn",
    "BacktestEngine", "SizingFn", "fixed_contracts", "risk_based",
    "AtrTrail", "BreakevenAfterR", "CompositeExit", "ExitContext", "ExitDecision",
    "ExitPolicy", "FixedR", "MultiTargetR", "OpposingLevel", "PositionState",
    "SessionEnd", "TimeStop",
    "compute_stats", "daily_pnl", "empty_stats", "equity_curve",
]
