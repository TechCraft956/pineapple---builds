"""Deterministic account state machine: replay trades, decide if you survive.

This is the module the whole risk engine exists for. It answers, trade by
trade, in chronological order: what is the account's equity, where does the
trailing Maximum Loss Limit (MLL) threshold currently sit, has it locked, did
today's realised loss trip a lockout, and -- the check that actually matters
-- did *open* drawdown on an in-flight trade touch the threshold even though
the trade went on to close for a profit?

That last question is why :class:`~lab.core.types.Trade` carries ``mae``
(worst unrealised excursion, <= 0): a strategy can look perfectly profitable
on closed-trade PnL and still have blown the account intrabar. When
``AccountRules.includes_unrealized`` is set, this simulator checks
``equity_before_trade + trade.mae`` against the *currently active* threshold
for every single trade, independent of how the trade eventually closed. Skip
that check and every other number this module produces is fiction.

See :mod:`lab.risk.rules` for what every field on :class:`AccountRules` means
and -- more importantly -- which of them are firm-supplied facts versus
unverified defaults you must confirm yourself.

Interpretation choices made here that are NOT firm-documented facts (surface
them in any report this feeds):

* Trades are grouped into a "trading day" by ``trading_day(trade.exit_ts)``
  (matching :func:`lab.core.types.trades_to_frame`'s own sort key), not by
  entry time. A trade opened one trading day and closed the next is booked,
  in full, on the day it closed.
* The trailing threshold only ever *moves* at end-of-day (whichever value
  ``trail_on`` says to feed it), but a breach can be *detected* intrabar via
  MAE against whatever threshold was already locked in at the start of that
  day. This matches the user's description ("includes unrealised P&L and
  trails based on end-of-day results") read as two separate mechanics rather
  than one.
* On an MAE breach, the account is force-closed at ``equity_before + mae``
  (the worst point reached), not at the trade's actual exit price -- a real
  broker liquidates you at the stop-out level, it does not let the position
  run to its planned exit once you are through the floor.
* Daily lockout (personal stop or firm daily loss limit) is evaluated on
  *realised* daily PnL only, even when ``includes_unrealized`` is true for
  the MLL itself. Open-trade drawdown can still breach the MLL on the same
  day; it just does not by itself trigger the *lockout* mechanic, which is
  about deciding whether to take the *next* trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Any, Mapping, Sequence

import pandas as pd

from lab.core.sessions import trading_day
from lab.core.types import Trade
from lab.risk.rules import AccountRules, LockAt, PayoutPath, PayoutPathKind, TrailOn

__all__ = [
    "SkippedTrade",
    "PayoutEligibility",
    "AccountRun",
    "AccountSimulator",
]


@dataclass(frozen=True, slots=True)
class SkippedTrade:
    """A trade that never touched the account because the day was locked out.

    ``reason`` is ``"personal_daily_stop"``, ``"daily_loss_limit"``, or both
    joined with ``"+"`` when they tripped on the same day.
    """

    trade: Trade
    trading_day: date_type
    reason: str


@dataclass(frozen=True, slots=True)
class PayoutEligibility:
    """Whether, and when, one :class:`~lab.risk.rules.PayoutPath` was met.

    Two different questions, deliberately both answered:

    ``eligible`` / ``eligible_on`` / ``sessions_to_eligibility``
        Was there *ever* a day on which a payout could have been requested, and
        which one? This is the planning number -- how long the strategy takes
        to reach a withdrawal.
    ``eligible_at_end``
        Does the account satisfy the path *as the run ends*? These come apart
        exactly where it matters: an account that met the 40% consistency rule
        on day 3 and then printed one outsized day is no longer eligible today,
        even though it once was. Reporting only first-eligibility would say the
        payout is available when it is not.
    """

    path_name: str
    eligible: bool
    eligible_on: date_type | None
    sessions_to_eligibility: int | None
    eligible_at_end: bool = False
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AccountRun:
    """Everything one deterministic replay of a trade sequence produced.

    ``daily_pnl``, ``mll_threshold`` and ``equity_curve`` are all
    :class:`pandas.Series` indexed by trading day (a plain ``datetime.date``,
    not a UTC timestamp -- daily aggregation is a CME-trading-day concept, see
    :mod:`lab.core.sessions`). ``trade_trace`` is a per-trade DataFrame handy
    for streak analysis (see :mod:`lab.risk.survival`).
    """

    rules: AccountRules
    final_equity: float
    breached: bool
    breach_ts: pd.Timestamp | None
    breach_reason: str | None
    days_survived: int
    trades_taken: int
    trades_skipped: int
    trades_total: int
    skipped_trades: list[SkippedTrade]
    daily_pnl: pd.Series
    mll_threshold: pd.Series
    equity_curve: pd.Series
    payout_eligibility: dict[str, PayoutEligibility]
    consistency_ratio: float | None
    max_intraday_drawdown: float
    min_mll_headroom: float
    trade_trace: pd.DataFrame

    @property
    def net_pnl(self) -> float:
        return self.final_equity - self.rules.starting_balance

    def summary(self) -> str:
        status = f"BREACHED at {self.breach_ts} ({self.breach_reason})" if self.breached else "survived"
        return (
            f"{self.rules.name}: {status} | days={self.days_survived} "
            f"trades={self.trades_taken}/{self.trades_total} "
            f"(skipped {self.trades_skipped}) | net_pnl=${self.net_pnl:,.2f} | "
            f"min_headroom=${self.min_mll_headroom:,.2f}"
        )


class AccountSimulator:
    """Steps a chronological trade sequence through one :class:`AccountRules`.

    Stateless between calls: construct with a rule set, call :meth:`run` with
    as many different trade sequences as you like (this is exactly what
    :mod:`lab.risk.montecarlo` does -- one simulator, many bootstrap paths).
    """

    def __init__(self, rules: AccountRules) -> None:
        self.rules = rules

    def run(self, trades: Sequence[Trade]) -> AccountRun:
        rules = self.rules
        ordered = sorted(trades, key=lambda t: (t.exit_ts, t.entry_ts))

        equity = rules.starting_balance
        peak = rules.starting_balance
        threshold = rules.initial_threshold
        locked = False

        breached = False
        breach_ts: pd.Timestamp | None = None
        breach_reason: str | None = None

        daily_pnl: dict[date_type, float] = {}
        threshold_series: dict[date_type, float] = {}
        equity_series: dict[date_type, float] = {}
        skipped: list[SkippedTrade] = []
        trade_trace_rows: list[dict[str, Any]] = []

        trades_taken = 0
        max_intraday_drawdown = 0.0
        min_headroom = rules.max_loss_limit  # headroom at t=0: starting_balance - initial_threshold

        current_day: date_type | None = None
        day_locked_out = False
        day_lockout_reason = ""
        day_realized = 0.0
        day_intraday_peak_equity = equity

        def close_out_day(do_trail: bool) -> None:
            nonlocal threshold, peak, locked
            if current_day is None:
                return
            if do_trail:
                threshold, peak, locked = _trail(
                    rules, peak, threshold, locked,
                    eod_close=equity, intraday_peak=day_intraday_peak_equity,
                )
            threshold_series[current_day] = threshold
            equity_series[current_day] = equity
            daily_pnl[current_day] = day_realized

        for t in ordered:
            d = trading_day(t.exit_ts)
            if d != current_day:
                close_out_day(do_trail=True)
                current_day = d
                day_locked_out = False
                day_lockout_reason = ""
                day_realized = 0.0
                day_intraday_peak_equity = equity

            if day_locked_out:
                skipped.append(SkippedTrade(trade=t, trading_day=d, reason=day_lockout_reason))
                continue

            equity_before = equity

            if rules.includes_unrealized:
                intraday_low = equity_before + t.mae  # mae <= 0
                headroom = intraday_low - threshold
                min_headroom = min(min_headroom, headroom)
                max_intraday_drawdown = max(max_intraday_drawdown, peak - intraday_low)
                if intraday_low < threshold:
                    breached = True
                    breach_ts = t.exit_ts
                    breach_reason = (
                        f"unrealised MAE breach during trade closing {t.exit_ts}: "
                        f"equity_before={equity_before:,.2f} + mae={t.mae:,.2f} = "
                        f"{intraday_low:,.2f} < threshold {threshold:,.2f}"
                    )
                    equity = intraday_low
                    trades_taken += 1
                    trade_trace_rows.append(_trace_row(t, d, equity_before, equity, threshold, breached=True))
                    break

            intraday_high = equity_before + t.mfe
            day_intraday_peak_equity = max(day_intraday_peak_equity, intraday_high)

            equity_after = equity_before + t.pnl
            headroom_realized = equity_after - threshold
            min_headroom = min(min_headroom, headroom_realized)
            max_intraday_drawdown = max(max_intraday_drawdown, peak - equity_after)

            if equity_after < threshold:
                breached = True
                breach_ts = t.exit_ts
                breach_reason = (
                    f"realised breach on trade closing {t.exit_ts}: equity "
                    f"{equity_after:,.2f} < threshold {threshold:,.2f}"
                )
                equity = equity_after
                trades_taken += 1
                trade_trace_rows.append(_trace_row(t, d, equity_before, equity, threshold, breached=True))
                break

            equity = equity_after
            day_realized += t.pnl
            trades_taken += 1
            trade_trace_rows.append(_trace_row(t, d, equity_before, equity, threshold, breached=False))

            reasons = []
            if rules.personal_daily_stop is not None and day_realized <= -abs(rules.personal_daily_stop):
                reasons.append("personal_daily_stop")
            if rules.daily_loss_limit is not None and day_realized <= -abs(rules.daily_loss_limit):
                reasons.append("daily_loss_limit")
            if reasons:
                day_locked_out = True
                day_lockout_reason = "+".join(reasons)

        close_out_day(do_trail=not breached)

        daily_pnl_series = _to_series(daily_pnl, "daily_pnl")
        threshold_ser = _to_series(threshold_series, "mll_threshold")
        equity_ser = _to_series(equity_series, "equity")
        trace_df = _to_trace_frame(trade_trace_rows)

        payout_eligibility = _evaluate_payout_paths(rules, daily_pnl_series)
        consistency_ratio = _consistency_ratio(daily_pnl_series)

        return AccountRun(
            rules=rules,
            final_equity=equity,
            breached=breached,
            breach_ts=breach_ts,
            breach_reason=breach_reason,
            days_survived=len(daily_pnl_series),
            trades_taken=trades_taken,
            trades_skipped=len(skipped),
            trades_total=len(ordered),
            skipped_trades=skipped,
            daily_pnl=daily_pnl_series,
            mll_threshold=threshold_ser,
            equity_curve=equity_ser,
            payout_eligibility=payout_eligibility,
            consistency_ratio=consistency_ratio,
            max_intraday_drawdown=max_intraday_drawdown,
            min_mll_headroom=min_headroom,
            trade_trace=trace_df,
        )


def _trail(
    rules: AccountRules,
    peak: float,
    threshold: float,
    locked: bool,
    *,
    eod_close: float,
    intraday_peak: float,
) -> tuple[float, float, bool]:
    """One end-of-day trailing update. See module docstring for the semantics."""
    if locked:
        return threshold, peak, locked
    candidate = eod_close if rules.trail_on is TrailOn.EOD_CLOSE else intraday_peak
    new_peak = max(peak, candidate)
    new_threshold = max(threshold, new_peak - rules.max_loss_limit)

    if rules.lock_at is LockAt.STARTING_BALANCE:
        if new_threshold >= rules.starting_balance:
            return rules.starting_balance, new_peak, True
    elif rules.lock_at is LockAt.PROFIT_TARGET:
        assert rules.profit_target is not None  # enforced in AccountRules.__post_init__
        if new_peak >= rules.profit_target:
            return new_threshold, new_peak, True
    # LockAt.NEVER (or not-yet-triggered STARTING_BALANCE/PROFIT_TARGET): keep trailing.
    return new_threshold, new_peak, False


def _trace_row(
    t: Trade, d: date_type, equity_before: float, equity_after: float, threshold: float, *, breached: bool,
) -> dict[str, Any]:
    return {
        "exit_ts": t.exit_ts,
        "trading_day": d,
        "pnl": t.pnl,
        "mae": t.mae,
        "mfe": t.mfe,
        "equity_before": equity_before,
        "equity_after": equity_after,
        "mll_threshold_active": threshold,
        "headroom": equity_after - threshold,
        "breached": breached,
    }


def _to_series(d: Mapping[date_type, float], name: str) -> pd.Series:
    if not d:
        return pd.Series(dtype="float64", name=name)
    idx = pd.Index(sorted(d), name="trading_day")
    return pd.Series([d[k] for k in idx], index=idx, name=name)


def _to_trace_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    cols = [
        "exit_ts", "trading_day", "pnl", "mae", "mfe", "equity_before",
        "equity_after", "mll_threshold_active", "headroom", "breached",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


def _evaluate_payout_paths(rules: AccountRules, daily_pnl: pd.Series) -> dict[str, PayoutEligibility]:
    """Walk the daily PnL series once per path, in day order, for first eligibility."""
    out: dict[str, PayoutEligibility] = {}
    days = list(daily_pnl.index)

    for path in rules.payout_paths:
        min_days = max(rules.min_trading_days, path.min_trading_days)
        eligible = False
        eligible_on: date_type | None = None
        sessions: int | None = None
        at_end = False
        detail: dict[str, Any] = {}

        if path.kind is PayoutPathKind.STANDARD:
            amount = rules.resolve_min_winning_day_amount(path)
            need = path.min_winning_days or 0
            winning = 0
            for i, day in enumerate(days, start=1):
                if daily_pnl.loc[day] >= amount:
                    winning += 1
                if winning >= need and i >= min_days:
                    eligible, eligible_on, sessions = True, day, i
                    break
            # Winning days only accumulate, so an account that ever cleared the
            # standard path still clears it at the end -- but count over the
            # whole series rather than stopping at first eligibility, since the
            # loop above breaks early.
            winning_total = int((daily_pnl >= amount).sum())
            at_end = winning_total >= need and len(days) >= min_days
            detail = {
                "min_winning_days": need,
                "min_winning_day_amount": amount,
                "winning_days_total": winning_total,
            }

        elif path.kind is PayoutPathKind.CONSISTENCY:
            share = rules.resolve_max_single_day_share(path)
            cum = 0.0
            best_day = float("-inf")
            for i, day in enumerate(days, start=1):
                cum += float(daily_pnl.loc[day])
                best_day = max(best_day, float(daily_pnl.loc[day]))
                if i >= min_days and cum > 0:
                    ratio = max(best_day, 0.0) / cum
                    if ratio <= share:
                        eligible, eligible_on, sessions = True, day, i
                        break
            total = float(daily_pnl.sum())
            largest = max(float(daily_pnl.max()), 0.0) if len(days) else 0.0
            end_ratio = largest / total if total > 0 else None
            at_end = (
                len(days) >= min_days
                and end_ratio is not None
                and end_ratio <= share
            )
            detail = {
                "max_single_day_share": share,
                "min_trading_days": min_days,
                "end_ratio": end_ratio,
            }
        else:  # pragma: no cover - exhaustive over PayoutPathKind
            raise ValueError(f"unknown payout path kind {path.kind!r}")

        out[path.name] = PayoutEligibility(
            path_name=path.name,
            eligible=eligible,
            eligible_on=eligible_on,
            sessions_to_eligibility=sessions,
            eligible_at_end=at_end,
            detail=detail,
        )
    return out


def _consistency_ratio(daily_pnl: pd.Series) -> float | None:
    """Largest single day's profit / total realised profit, over the full run.

    ``None`` when total realised profit is not positive (the ratio is not a
    meaningful "how compliant am I" number when there is no profit to share).
    """
    if daily_pnl.empty:
        return None
    total = float(daily_pnl.sum())
    if total <= 0:
        return None
    largest = float(daily_pnl.max())
    return max(largest, 0.0) / total
