"""The post-session review: what was planned, what happened, what to change.

Deliberately narrow in what it lets a reader conclude. It states, in the
report itself, the two standing rules that keep a journal from turning into
after-the-fact storytelling:

* Only **one** rule may change per strategy version. A session review that
  proposes three fixes at once makes it impossible to attribute the next
  N trades' results to any one of them.
* Old results are never retroactively rewritten. If today changes a rule,
  that is a new version (see :mod:`lab.journal.journal`'s append-only
  contract) -- yesterday's numbers stay yesterday's numbers.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from lab.core.types import Signal, TradeList
from lab.journal.adherence import (
    MatchTolerance,
    adherence_score,
    hesitation_analysis,
    reconcile,
    slippage_report,
)
from lab.reports.render import markdown_table, section, verdict_box

__all__ = ["build_session_review"]

#: Adherence below this overall rate fails the verdict box outright.
_ADHERENCE_PASS_THRESHOLD = 0.85


def _trades_table(executed_trades: TradeList) -> pd.DataFrame:
    if not executed_trades:
        return pd.DataFrame(
            columns=["symbol", "direction", "entry_ts", "entry_price", "exit_ts", "exit_price",
                     "qty", "pnl", "mfe", "mae", "exit_reason", "tag"]
        )
    return pd.DataFrame(
        [
            {
                "symbol": t.symbol, "direction": "long" if t.direction > 0 else "short",
                "entry_ts": t.entry_ts, "entry_price": t.entry_price,
                "exit_ts": t.exit_ts, "exit_price": t.exit_price,
                "qty": t.qty, "pnl": t.pnl, "mfe": t.mfe, "mae": t.mae,
                "exit_reason": t.exit_reason.value, "tag": t.tag,
            }
            for t in executed_trades
        ]
    )


def build_session_review(
    day: "Any",
    journal_rows: pd.DataFrame,
    executed_trades: TradeList,
    expected_signals: Sequence[Signal],
    account_state: Mapping[str, Any] | None = None,
    tolerance: MatchTolerance = MatchTolerance(),
) -> str:
    """Build the post-session review as markdown.

    Parameters
    ----------
    day:
        The CME trading day this review is for.
    journal_rows:
        The subset of :meth:`~lab.journal.journal.Journal.load` covering this
        day (e.g. ``journal.query(start=day, end=day)``), used for skipped
        setups and :func:`~lab.journal.adherence.hesitation_analysis`.
    executed_trades, expected_signals:
        Reconciled via :func:`~lab.journal.adherence.reconcile` to produce the
        matched/unplanned/skipped verdict and slippage numbers.
    account_state:
        Optional ``{"equity": float, "drawdown_headroom": float,
        "qualifying_days": int, ...}`` from ``lab.risk``'s account simulator.
        When absent the report says so plainly rather than guessing.
    """
    day_str = pd.Timestamp(day).date().isoformat()
    result = reconcile(executed_trades, expected_signals, tolerance)
    score = adherence_score(result)
    slip_df = slippage_report(result.matched)

    parts: list[str] = [f"# Session review -- {day_str}\n"]

    # ---- planned vs. happened ------------------------------------------
    plan_rows = pd.DataFrame(
        [
            {"bucket": "matched (taken as planned)", "n": score.matched},
            {"bucket": "unplanned (taken, no signal)", "n": score.unplanned},
            {"bucket": "skipped (signalled, not taken)", "n": score.skipped},
        ]
    )
    parts.append(section("Planned vs. happened", markdown_table(plan_rows)))

    # ---- every trade -----------------------------------------------
    trades_df = _trades_table(executed_trades)
    if not slip_df.empty:
        trades_df = trades_df.merge(
            slip_df[["entry_ts", "slippage_ticks", "slippage_dollars"]],
            on="entry_ts", how="left",
        )
    parts.append(section("Every trade", markdown_table(
        trades_df, formats={"pnl": ",.2f", "mfe": ",.2f", "mae": ",.2f",
                             "slippage_ticks": "+.1f", "slippage_dollars": "+,.2f"}
    )))

    # ---- adherence verdict -------------------------------------------
    overall = score.overall
    passed = (overall == overall) and overall >= _ADHERENCE_PASS_THRESHOLD  # NaN-safe
    parts.append(
        verdict_box(
            "plan adherence",
            passed=bool(passed),
            detail=(
                f"taken-rate {score.taken_rate:.0%}, discipline-rate {score.discipline_rate:.0%}, "
                f"overall {overall:.0%} (threshold {_ADHERENCE_PASS_THRESHOLD:.0%})"
                if overall == overall else "no signals or trades to score"
            ),
        )
        + "\n"
    )

    # ---- skipped setups ---------------------------------------------
    if result.skipped:
        skip_rows = pd.DataFrame(
            [
                {"symbol": s.symbol, "direction": "long" if s.direction > 0 else "short",
                 "ts": s.ts, "entry": s.entry, "tag": s.tag}
                for s in result.skipped
            ]
        )
        parts.append(section("Skipped setups (signalled, no matching execution)", markdown_table(skip_rows)))
    else:
        parts.append(section("Skipped setups", "_none -- every signal was either taken or unplanned_"))

    if not journal_rows.empty:
        journal_skips = journal_rows[journal_rows["status"] == "skipped"]
        if not journal_skips.empty:
            parts.append(section(
                "Skipped setups logged directly in the journal",
                markdown_table(journal_skips[["trading_day", "symbol", "tag", "notes"]]),
            ))
        hesitation = hesitation_analysis(journal_rows)
        parts.append(section(
            "Hesitation check",
            f"Skip rate immediately after a loss: {hesitation['skip_rate_after_loss']:.0%} "
            f"(n={hesitation['n_events_after_loss']}) vs. after a win/flat: "
            f"{hesitation['skip_rate_after_win_or_flat']:.0%} "
            f"(n={hesitation['n_events_after_other']}).\n\n**{hesitation['verdict']}**"
            if hesitation["n_events_after_loss"] or hesitation["n_events_after_other"]
            else "Not enough events today to compare skip rates after a loss vs. after a win.",
        ))

    # ---- running account state -----------------------------------
    if account_state:
        acct_rows = pd.DataFrame([{"metric": k, "value": v} for k, v in account_state.items()])
        parts.append(section("Running account state", markdown_table(acct_rows)))
    else:
        parts.append(section(
            "Running account state",
            "_not supplied -- pass `account_state` from lab.risk's account simulator to show "
            "equity, drawdown headroom and qualifying days here_",
        ))

    # ---- one thing to change -----------------------------------------
    parts.append(section(
        "One thing to change",
        "Standing rule: only **one** rule may change per strategy version, and old "
        "results are never retroactively rewritten -- a rule change starts a new "
        "version going forward, it does not reinterpret what already happened.\n\n"
        "What is the single highest-leverage change suggested by today's session "
        "(a rule, a size, a setup to drop -- not three at once)?\n\n"
        "- [ ] ________________________________________",
    ))

    return "\n".join(parts)
