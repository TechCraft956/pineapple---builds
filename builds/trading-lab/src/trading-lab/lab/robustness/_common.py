"""Private helpers shared by the robustness modules.

Nothing here is exported from :mod:`lab.robustness`; it exists only to avoid
duplicating the lazy, fallback-guarded import of
:func:`lab.backtest.metrics.compute_stats` between :mod:`lab.robustness.dropn`
and :mod:`lab.robustness.regimes`. See the module docstring on
:mod:`lab.robustness.dropn` for why the import happens lazily, inside a
function, rather than at module scope.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from lab.core.types import TradeList, trades_to_frame

__all__: list[str] = []


def _fallback_stats(trades: TradeList) -> Mapping[str, Any]:
    """Minimal stand-in for ``lab.backtest.metrics.compute_stats``, covering
    exactly the keys the robustness modules read. Used only if that module
    cannot be imported."""
    df = trades_to_frame(trades)
    if df.empty:
        return {
            "n_trades": 0, "win_rate": float("nan"), "expectancy_r": float("nan"),
            "net_pnl": 0.0, "max_drawdown_dollars": 0.0,
        }
    n = len(df)
    wins = int((df["pnl"] > 0).sum())
    equity = df["pnl"].cumsum()
    running_max = equity.cummax()
    max_dd = float((equity - running_max).min())
    return {
        "n_trades": n,
        "win_rate": wins / n,
        "expectancy_r": float(df["r_multiple"].mean()),
        "net_pnl": float(df["pnl"].sum()),
        "max_drawdown_dollars": max_dd,
    }


def compute_stats(trades: TradeList) -> Mapping[str, Any]:
    """``lab.backtest.metrics.compute_stats(trades)`` if importable, else a
    small self-contained fallback -- so this package never depends on
    ``lab.backtest`` at import time, and its tests never depend on it at all.
    """
    try:
        from lab.backtest.metrics import compute_stats as _compute_stats  # local: optional dep
    except Exception:
        return _fallback_stats(trades)
    return _compute_stats(trades)
