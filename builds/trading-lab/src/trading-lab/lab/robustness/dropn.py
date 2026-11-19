"""Drop-the-best-N robustness check: is the headline number a few lucky prints?

A backtest's headline expectancy is a mean. A mean can be dominated by a
handful of outlier trades or a couple of outlier days -- a strategy that
looks great mostly because of two enormous winners is not the same thing as
one that is reliably good. :func:`drop_best` recomputes the headline stats
with the best ``n`` trades, or the best ``n`` trading days, excluded, so the
before/after comparison answers "how much of this is a few outliers" directly
instead of leaving it to be eyeballed off an equity curve.

This module does not import :mod:`lab.backtest` at module scope (the ground
rule for this package): ``lab.backtest.metrics.compute_stats`` is imported
lazily, inside :func:`lab.robustness._common.compute_stats`, with a graceful
fallback to a small self-contained stat function if that import fails --
which is also why this module's own tests never need ``lab.backtest`` to
exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pandas as pd

from lab.core.sessions import trading_day
from lab.core.types import Trade, TradeList, trades_to_frame
from lab.robustness._common import compute_stats

__all__ = ["DropBestResult", "drop_best"]


@dataclass(frozen=True, slots=True)
class DropBestResult:
    """Before/after headline stats with the best ``n`` trades or days removed.

    A strategy whose stats survive this comfortably is not being carried by
    a handful of outlier prints; one whose ``expectancy_r`` or ``net_pnl``
    collapses when its best few trades/days are excluded is telling you the
    backtest's headline number is mostly luck.
    """

    by: str
    n: int
    n_dropped_trades: int
    dropped_pnl: float
    before: Mapping[str, Any]
    after: Mapping[str, Any]

    def summary(self) -> str:
        return (
            f"drop_best(n={self.n}, by={self.by!r}): removed {self.n_dropped_trades} trade(s) "
            f"({self.dropped_pnl:+,.0f} of headline pnl) -- "
            f"net_pnl {self.before['net_pnl']:+,.0f} -> {self.after['net_pnl']:+,.0f}, "
            f"expectancy_r {self.before['expectancy_r']:+.3f} -> {self.after['expectancy_r']:+.3f}, "
            f"win_rate {self.before['win_rate']:.1%} -> {self.after['win_rate']:.1%}"
        )


def drop_best(
    result_or_trades: Any,
    n: int,
    by: str = "trade",
    *,
    key_fn: Callable[[Trade], float] | None = None,
) -> DropBestResult:
    """Recompute headline stats with the best ``n`` trades (or trading days) excluded.

    ``result_or_trades`` is anything with a ``.trades`` attribute (e.g. a
    :class:`~lab.core.types.BacktestResult`) or a plain sequence of
    :class:`~lab.core.types.Trade`.

    ``by="trade"`` drops the ``n`` individual trades with the highest
    ``key_fn`` value (default: realised dollar ``pnl``; pass e.g.
    ``key_fn=lambda t: t.r_multiple`` to rank by R instead).

    ``by="day"`` drops every trade whose *exit* trading day (see
    :mod:`lab.core.sessions`) falls among the ``n`` trading days with the
    highest total pnl. This can remove far more than ``n`` trades when a good
    day held several good trades -- which is the whole point of offering it
    as a separate mode from ``by="trade"``: a strategy that is fragile to
    "a few lucky days" fails this even when it survives dropping the same
    number of individually-best trades.
    """
    if by not in ("trade", "day"):
        raise ValueError(f"by must be 'trade' or 'day', got {by!r}")
    if n < 0:
        raise ValueError("n must be >= 0")

    trades: list[Trade] = list(getattr(result_or_trades, "trades", result_or_trades))
    before = compute_stats(trades)

    if n == 0 or not trades:
        return DropBestResult(by, n, 0, 0.0, before, before)

    key = key_fn or (lambda t: t.pnl)

    if by == "trade":
        ranked = sorted(trades, key=key, reverse=True)
        dropped = ranked[:n]
        dropped_ids = {id(t) for t in dropped}
        kept = [t for t in trades if id(t) not in dropped_ids]
    else:
        df = trades_to_frame(trades)
        days = trading_day(pd.DatetimeIndex(df["exit_ts"]))
        daily_pnl = df.groupby(days)["pnl"].sum().sort_values(ascending=False)
        drop_days = set(daily_pnl.index[:n])
        exit_days = pd.Series(days, index=df.index)
        drop_mask = exit_days.isin(drop_days)
        drop_exit_ts = set(df.index[drop_mask])
        dropped = [t for t in trades if t.exit_ts in drop_exit_ts]
        kept = [t for t in trades if t.exit_ts not in drop_exit_ts]

    after = compute_stats(kept)
    dropped_pnl = float(sum(t.pnl for t in dropped))
    return DropBestResult(by, n, len(dropped), dropped_pnl, before, after)
