"""Trade and equity statistics.

Every function here takes a possibly-empty list of :class:`~lab.core.types.Trade`
and must never raise on empty input -- a strategy that fired zero times in a
window is a valid, common research outcome (a filtered date range, a strict
regime gate) and the reporting layer downstream should see a well-formed
all-NaN/zero dict, not a stack trace. Every division in this module is guarded
for that reason; look for the ``_safe_div`` helper rather than a bare ``/``.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from lab.core.sessions import trading_day
from lab.core.types import TradeList, trades_to_frame

__all__ = ["daily_pnl", "equity_curve", "compute_stats", "empty_stats"]

_TRADING_DAYS_PER_YEAR = 252


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if den == 0 or not np.isfinite(den):
        return default
    out = num / den
    return out if np.isfinite(out) else default


def daily_pnl(trades: TradeList) -> pd.Series:
    """Net PnL summed by CME trading day (see :mod:`lab.core.sessions`).

    Grouping is on the trade's *exit* day -- PnL realises when a position
    closes, not when it opens, which matters for trades that span a session
    roll (an overnight London-sweep hold, for instance).
    """
    df = trades_to_frame(trades)
    if df.empty:
        return pd.Series(dtype="float64", name="daily_pnl")
    days = trading_day(pd.DatetimeIndex(df["exit_ts"]))
    out = df.groupby(days)["pnl"].sum()
    out.index.name = "trading_day"
    out.name = "daily_pnl"
    return out.sort_index()


def equity_curve(trades: TradeList) -> pd.Series:
    """Cumulative net PnL indexed by ``exit_ts``. See ``BacktestResult.equity``."""
    df = trades_to_frame(trades)
    if df.empty:
        empty = pd.Series(dtype="float64", name="equity")
        empty.index = pd.DatetimeIndex([], tz="UTC", name="exit_ts")
        return empty
    curve = df["pnl"].cumsum()
    curve.name = "equity"
    return curve


def _max_drawdown(curve: pd.Series) -> tuple[float, pd.Timedelta | None]:
    """Peak-to-trough drawdown in dollars, and the longest underwater span.

    An underwater span that never recovers by the end of ``curve`` still
    counts, measured through to the last point -- an unrecovered drawdown is
    not a shorter one just because the data ran out.
    """
    if curve.empty:
        return 0.0, None
    running_max = curve.cummax()
    dd = curve - running_max
    max_dd = float(dd.min()) if len(dd) else 0.0

    longest = pd.Timedelta(0)
    peak_ts = curve.index[0]
    peak_val = curve.iloc[0]
    for ts, val in curve.items():
        if val >= peak_val:
            peak_val = val
            peak_ts = ts
        else:
            span = ts - peak_ts
            if span > longest:
                longest = span
    return max_dd, longest


def _longest_losing_streak(pnls: pd.Series) -> int:
    longest = streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return longest


def _sharpe_sortino(daily: pd.Series) -> tuple[float, float]:
    if daily.empty or len(daily) < 2:
        return float("nan"), float("nan")
    mean = daily.mean()
    std = daily.std(ddof=1)
    sharpe = _safe_div(mean, std, default=float("nan")) * np.sqrt(_TRADING_DAYS_PER_YEAR)
    downside = daily[daily < 0]
    down_std = downside.std(ddof=1) if len(downside) >= 2 else np.nan
    sortino = _safe_div(mean, down_std, default=float("nan")) * np.sqrt(_TRADING_DAYS_PER_YEAR)
    return float(sharpe), float(sortino)


def empty_stats() -> dict[str, Any]:
    """All-zero/NaN stats dict with the full key set, for empty trade lists."""
    return {
        "n_trades": 0,
        "n_wins": 0,
        "n_losses": 0,
        "win_rate": float("nan"),
        "expectancy_dollars": float("nan"),
        "expectancy_r": float("nan"),
        "profit_factor": float("nan"),
        "payoff_ratio": float("nan"),
        "avg_r": float("nan"),
        "median_r": float("nan"),
        "gross_pnl": 0.0,
        "net_pnl": 0.0,
        "total_commission": 0.0,
        "total_slippage_cost": 0.0,
        "cost_drag": float("nan"),
        "sharpe_daily": float("nan"),
        "sortino_daily": float("nan"),
        "max_drawdown_dollars": 0.0,
        "max_drawdown_duration": None,
        "longest_losing_streak": 0,
        "trades_per_day": float("nan"),
        "exposure": float("nan"),
        "exit_reason_breakdown": {},
        "by_tag": {},
        "by_weekday": {},
        "mfe_summary": {},
        "mae_summary": {},
    }


def _dist_summary(s: pd.Series) -> dict[str, float]:
    if s.empty:
        return {"mean": float("nan"), "median": float("nan"), "p25": float("nan"), "p75": float("nan"), "max": float("nan"), "min": float("nan")}
    return {
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "max": float(s.max()),
        "min": float(s.min()),
    }


def compute_stats(
    trades: TradeList,
    equity: pd.Series | None = None,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> Mapping[str, Any]:
    """Full stats dict for one :class:`~lab.core.types.BacktestResult`.

    ``equity`` (trade-resolution cumulative PnL) drives the drawdown metrics;
    if omitted it is derived from ``trades`` via :func:`equity_curve`.
    Sharpe/Sortino are computed on *daily* PnL regardless, per CME trading
    day, because trade-level returns are not IID and annualising them
    directly overstates significance.

    ``start``/``end`` (the backtest's bar-frame bounds, not just the trade
    span) sharpen ``exposure`` and ``trades_per_day`` -- without them these
    fall back to the trade span itself, which understates the denominator
    whenever the strategy sat out part of the window entirely.
    """
    if not trades:
        return empty_stats()

    df = trades_to_frame(trades)
    if equity is None:
        equity = equity_curve(trades)

    pnl = df["pnl"]
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    n = len(df)

    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())  # positive number
    gross_pnl = float((pnl + df["commission"] + df["slippage_cost"]).sum())
    net_pnl = float(pnl.sum())
    total_costs = float(df["commission"].sum() + df["slippage_cost"].sum())

    r = df["r_multiple"]
    max_dd, dd_duration = _max_drawdown(equity)
    daily = daily_pnl(trades)
    sharpe, sortino = _sharpe_sortino(daily)

    span_start = start if start is not None else df["entry_ts"].min()
    span_end = end if end is not None else df["exit_ts"].max()
    span_days = max((span_end - span_start) / pd.Timedelta(days=1), 0.0) if pd.notna(span_start) and pd.notna(span_end) else 0.0
    held = (df["exit_ts"] - df["entry_ts"]).sum()
    exposure = _safe_div(held / pd.Timedelta(days=1), span_days, default=float("nan"))

    by_tag = {
        tag: {
            "n_trades": int(len(g)),
            "win_rate": _safe_div(int((g["pnl"] > 0).sum()), len(g), default=float("nan")),
            "expectancy_r": float(g["r_multiple"].mean()),
            "net_pnl": float(g["pnl"].sum()),
        }
        for tag, g in df.groupby("tag")
    }
    weekday_names = pd.DatetimeIndex(df["exit_ts"]).day_name()
    by_weekday = {
        day: {
            "n_trades": int(len(g)),
            "win_rate": _safe_div(int((g["pnl"] > 0).sum()), len(g), default=float("nan")),
            "net_pnl": float(g["pnl"].sum()),
        }
        for day, g in df.groupby(weekday_names)
    }
    exit_reason_breakdown = {
        reason: int(count) for reason, count in df["exit_reason"].value_counts().items()
    }

    return {
        "n_trades": n,
        "n_wins": int(len(wins)),
        "n_losses": int(len(losses)),
        "win_rate": _safe_div(len(wins), n, default=float("nan")),
        "expectancy_dollars": _safe_div(net_pnl, n, default=float("nan")),
        "expectancy_r": float(r.mean()) if n else float("nan"),
        "profit_factor": _safe_div(gross_profit, gross_loss, default=float("nan")),
        "payoff_ratio": _safe_div(
            _safe_div(gross_profit, len(wins), default=0.0),
            _safe_div(gross_loss, len(losses), default=0.0),
            default=float("nan"),
        ),
        "avg_r": float(r.mean()) if n else float("nan"),
        "median_r": float(r.median()) if n else float("nan"),
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "total_commission": float(df["commission"].sum()),
        "total_slippage_cost": float(df["slippage_cost"].sum()),
        "cost_drag": _safe_div(total_costs, gross_pnl, default=float("nan")),
        "sharpe_daily": sharpe,
        "sortino_daily": sortino,
        "max_drawdown_dollars": max_dd,
        "max_drawdown_duration": dd_duration,
        "longest_losing_streak": _longest_losing_streak(pnl),
        "trades_per_day": _safe_div(n, span_days, default=float("nan")),
        "exposure": exposure,
        "exit_reason_breakdown": exit_reason_breakdown,
        "by_tag": by_tag,
        "by_weekday": by_weekday,
        "mfe_summary": _dist_summary(df["mfe"]),
        "mae_summary": _dist_summary(df["mae"]),
    }
