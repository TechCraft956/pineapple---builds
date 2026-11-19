"""Shared test builders. Kept deliberately dumb so a test reads as arithmetic."""

from __future__ import annotations

import pandas as pd

from lab.core.types import LONG, ExitReason, Trade


def ct(day: str, hhmm: str = "09:00") -> pd.Timestamp:
    """A UTC timestamp that lands on CME trading day ``day`` at Chicago ``hhmm``."""
    return (
        pd.Timestamp(f"{day} {hhmm}")
        .tz_localize("America/Chicago", nonexistent="shift_forward", ambiguous=True)
        .tz_convert("UTC")
    )


def mk_trade(
    day: str,
    pnl: float,
    *,
    hhmm: str = "09:00",
    mae: float = 0.0,
    mfe: float = 0.0,
    risk_dollars: float = 100.0,
    qty: float = 1.0,
    symbol: str = "ES",
    strategy: str = "test",
    tag: str = "",
    commission: float = 0.0,
    exit_reason: ExitReason = ExitReason.TARGET,
) -> Trade:
    """A Trade with only the fields the risk engine reads made meaningful.

    Prices are cosmetic here on purpose: the account simulator consumes ``pnl``,
    ``mae``, ``mfe`` and ``exit_ts``, and inventing self-consistent prices would
    only obscure the arithmetic each test is asserting.
    """
    entry = ct(day, hhmm)
    return Trade(
        symbol=symbol,
        strategy=strategy,
        direction=LONG,
        entry_ts=entry,
        entry_price=5000.0,
        exit_ts=entry + pd.Timedelta(minutes=15),
        exit_price=5000.0 + pnl / 50.0,
        qty=qty,
        pnl=pnl,
        commission=commission,
        slippage_cost=0.0,
        risk_dollars=risk_dollars,
        exit_reason=exit_reason,
        mfe=mfe,
        mae=mae,
        bars_held=15,
        tag=tag,
        signal_ts=entry,
    )
