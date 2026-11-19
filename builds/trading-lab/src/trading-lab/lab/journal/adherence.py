"""Reconcile intent (signals) against reality (executed trades).

A backtest only tells you what the rules would have produced. Whether the
edge survives contact with a human depends on three separate questions this
module answers:

1. Did executed trades actually correspond to the signals the strategy
   produced (:func:`reconcile`)?
2. Of the trades that were plan-conformant, how much did the fill itself cost
   versus the plan (:func:`slippage_report`)?
3. Is there a systematic pattern to the setups that got skipped -- in
   particular, does the skip rate rise right after a loss, which is the
   single most common way a working system quietly stops working
   (:func:`hesitation_analysis`)?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

from lab.core.instruments import get_instrument
from lab.core.types import Signal, Trade, TradeList

__all__ = [
    "MatchTolerance",
    "MatchedPair",
    "ReconcileResult",
    "AdherenceScore",
    "reconcile",
    "adherence_score",
    "hesitation_analysis",
    "slippage_report",
]


@dataclass(frozen=True, slots=True)
class MatchTolerance:
    """How close an execution must be to a signal to count as "the same trade".

    Both bounds must hold: entry within ``time`` of the signal timestamp, and
    entry price within ``price_ticks`` of the signal's intended entry.
    """

    time: pd.Timedelta = pd.Timedelta(minutes=10)
    price_ticks: float = 3.0


@dataclass(frozen=True, slots=True)
class MatchedPair:
    """One signal reconciled against the trade it produced."""

    signal: Signal
    trade: Trade
    entry_delay: pd.Timedelta  # execution ts - signal ts, always >= 0 by construction
    slippage_ticks: float  # signed: positive = adverse, matches Instrument.slip's convention
    slippage_dollars: float


@dataclass(slots=True)
class ReconcileResult:
    matched: list[MatchedPair] = field(default_factory=list)
    unplanned: list[Trade] = field(default_factory=list)  # executed with no matching signal
    skipped: list[Signal] = field(default_factory=list)  # signal with no matching execution


def _signed_slippage(signal: Signal, trade: Trade) -> tuple[float, float]:
    """Ticks and dollars of adverse slippage, signed so positive always means worse.

    For a long, filling *above* the intended entry is adverse; for a short,
    filling *below* is adverse. Both collapse to
    ``direction * (actual - theoretical)``.
    """
    inst = get_instrument(trade.symbol)
    price_slip = trade.direction * (trade.entry_price - signal.entry)
    return inst.ticks(price_slip), inst.dollars(price_slip, trade.qty)


def reconcile(
    executed_trades: TradeList,
    expected_signals: Sequence[Signal],
    tolerance: MatchTolerance = MatchTolerance(),
) -> ReconcileResult:
    """Bucket executions and signals into matched / unplanned / skipped.

    Matching is greedy nearest-neighbour: every (signal, trade) pair sharing a
    symbol and direction, within tolerance, is a candidate; candidates are
    consumed in order of increasing time delay (ties broken by price
    proximity), and each signal/trade is used at most once. This is not
    globally optimal bipartite matching, but for the small, mostly-unambiguous
    daily counts a discretionary trader produces it gives the same answer at a
    fraction of the complexity, and ties almost never occur in practice.
    """
    signals = list(expected_signals)
    trades = list(executed_trades)

    candidates: list[tuple[pd.Timedelta, float, int, int]] = []
    for s_idx, sig in enumerate(signals):
        for t_idx, tr in enumerate(trades):
            if tr.symbol != sig.symbol or tr.direction != sig.direction:
                continue
            delay = tr.entry_ts - sig.ts
            if delay < pd.Timedelta(0) or delay > tolerance.time:
                continue
            try:
                inst = get_instrument(tr.symbol)
                ticks = abs(inst.ticks(tr.entry_price - sig.entry))
            except KeyError:
                ticks = abs(tr.entry_price - sig.entry)
            if ticks > tolerance.price_ticks:
                continue
            candidates.append((delay, ticks, s_idx, t_idx))

    candidates.sort(key=lambda c: (c[0], c[1]))
    used_signals: set[int] = set()
    used_trades: set[int] = set()
    matched: list[MatchedPair] = []
    for delay, _ticks, s_idx, t_idx in candidates:
        if s_idx in used_signals or t_idx in used_trades:
            continue
        used_signals.add(s_idx)
        used_trades.add(t_idx)
        sig, tr = signals[s_idx], trades[t_idx]
        slip_ticks, slip_dollars = _signed_slippage(sig, tr)
        matched.append(
            MatchedPair(
                signal=sig, trade=tr, entry_delay=delay,
                slippage_ticks=slip_ticks, slippage_dollars=slip_dollars,
            )
        )

    unplanned = [tr for i, tr in enumerate(trades) if i not in used_trades]
    skipped = [sig for i, sig in enumerate(signals) if i not in used_signals]
    return ReconcileResult(matched=matched, unplanned=unplanned, skipped=skipped)


@dataclass(frozen=True, slots=True)
class AdherenceScore:
    """Three different ratios, because "adherence" conflates two failure modes.

    ``taken_rate`` -- of the valid setups the strategy produced, how many were
    actually taken (low = hesitation). ``discipline_rate`` -- of the trades
    actually taken, how many were plan-conformant (low = overtrading /
    freelancing). ``overall`` blends both into one number for a scoreboard,
    but the two component rates are what you act on.
    """

    matched: int
    skipped: int
    unplanned: int
    taken_rate: float
    discipline_rate: float
    overall: float


def adherence_score(result: ReconcileResult) -> AdherenceScore:
    m, s, u = len(result.matched), len(result.skipped), len(result.unplanned)
    return AdherenceScore(
        matched=m, skipped=s, unplanned=u,
        taken_rate=(m / (m + s)) if (m + s) else float("nan"),
        discipline_rate=(m / (m + u)) if (m + u) else float("nan"),
        overall=(m / (m + s + u)) if (m + s + u) else float("nan"),
    )


def hesitation_analysis(journal: pd.DataFrame) -> dict[str, Any]:
    """Does the skip rate rise immediately after a loss?

    ``journal`` is a :class:`~lab.journal.journal.Journal` history (or any
    frame with the same ``status``/``entry_ts``/``signal_ts``/``pnl``
    columns). Events (executed trades and skipped setups) are ordered
    chronologically; for every event we look at the P&L of the most recently
    *executed* trade before it and bucket the event as "immediately after a
    loss" or "after a win/flat/no prior trade". The skip rate in each bucket
    is compared -- a materially higher rate after a loss is the fingerprint of
    a system whose rules are sound but whose operator is not following them
    once it hurts, which is the single most common way a working edge stops
    working in practice, silently, long before the equity curve confesses it.
    """
    df = journal[journal["status"].isin(["executed", "skipped"])].copy()
    if df.empty:
        return {
            "n_events_after_loss": 0, "n_events_after_other": 0,
            "skip_rate_after_loss": float("nan"), "skip_rate_after_win_or_flat": float("nan"),
            "delta": float("nan"), "verdict": "insufficient data",
        }

    df["event_ts"] = df["entry_ts"].where(df["status"] == "executed", df["signal_ts"])
    df = df.dropna(subset=["event_ts"]).sort_values("event_ts", kind="stable")

    last_trade_pnl: float | None = None
    after_loss = {"skip": 0, "total": 0}
    after_other = {"skip": 0, "total": 0}
    for _, row in df.iterrows():
        if last_trade_pnl is not None:
            bucket = after_loss if last_trade_pnl < 0 else after_other
            bucket["total"] += 1
            if row["status"] == "skipped":
                bucket["skip"] += 1
        if row["status"] == "executed" and pd.notna(row.get("pnl")):
            last_trade_pnl = float(row["pnl"])

    rate_loss = (after_loss["skip"] / after_loss["total"]) if after_loss["total"] else float("nan")
    rate_other = (after_other["skip"] / after_other["total"]) if after_other["total"] else float("nan")
    delta = (rate_loss - rate_other) if pd.notna(rate_loss) and pd.notna(rate_other) else float("nan")

    if pd.isna(delta):
        verdict = "insufficient data to judge (need events both after a loss and after a win/flat)"
    elif delta > 0.10:
        verdict = "hesitation detected: skip rate rises after a loss"
    else:
        verdict = "no material hesitation pattern detected"

    return {
        "n_events_after_loss": after_loss["total"],
        "n_events_after_other": after_other["total"],
        "skip_rate_after_loss": rate_loss,
        "skip_rate_after_win_or_flat": rate_other,
        "delta": delta,
        "verdict": verdict,
    }


def slippage_report(matched: Sequence[MatchedPair]) -> pd.DataFrame:
    """Theoretical vs. actual entry for every matched trade, in ticks and dollars."""
    columns = [
        "symbol", "strategy", "tag", "signal_ts", "entry_ts", "entry_delay_s",
        "theoretical_entry", "actual_entry", "slippage_ticks", "slippage_dollars",
    ]
    if not matched:
        return pd.DataFrame(columns=columns)
    rows = [
        {
            "symbol": mp.signal.symbol,
            "strategy": mp.signal.strategy,
            "tag": mp.signal.tag,
            "signal_ts": mp.signal.ts,
            "entry_ts": mp.trade.entry_ts,
            "entry_delay_s": mp.entry_delay.total_seconds(),
            "theoretical_entry": mp.signal.entry,
            "actual_entry": mp.trade.entry_price,
            "slippage_ticks": mp.slippage_ticks,
            "slippage_dollars": mp.slippage_dollars,
        }
        for mp in matched
    ]
    return pd.DataFrame(rows, columns=columns)
