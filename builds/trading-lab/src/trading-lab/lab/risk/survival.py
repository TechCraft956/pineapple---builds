"""The questions a trader actually wants answered, each as a tidy DataFrame.

Every function here takes a completed trade sequence (and an
:class:`~lab.risk.rules.AccountRules`) and returns a
:class:`pandas.DataFrame` -- no plotting, no report formatting, that lives in
``scripts/simulate_account.py``. Functions that need a *distribution* of
outcomes (survival probability, sessions-to-payout) run
:func:`lab.risk.montecarlo.simulate_paths` under the hood and are therefore
seeded and reproducible; functions that describe one concrete history
(consistency, daily-stop sweep, size comparison) run
:class:`~lab.risk.account.AccountSimulator` directly on the trades given, with
no randomness at all.

As with every other module in :mod:`lab.risk`, treat every dollar figure
these functions produce (payout thresholds, consistency caps, daily loss
limits) as only as current as the :class:`~lab.risk.rules.AccountRules`
instance's ``source_note`` and ``rules_as_of`` say it is.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

import numpy as np
import pandas as pd

from lab.core.types import Trade
from lab.risk.account import AccountSimulator
from lab.risk.montecarlo import BootstrapMethod, simulate_paths
from lab.risk.rules import AccountRules, PayoutPathKind

__all__ = [
    "survival_curve",
    "sessions_to_payout",
    "post_payout_buffer",
    "daily_stop_sweep",
    "frequency_analysis",
    "consecutive_loss_analysis",
    "account_size_comparison",
    "consistency_analysis",
]


def survival_curve(
    trades: Sequence[Trade],
    rules: AccountRules,
    horizons: Sequence[int] = (20, 40, 60),
    *,
    n_paths: int = 1000,
    method: BootstrapMethod = "block",
    seed: int = 0,
    block_size: int | None = None,
) -> pd.DataFrame:
    """Probability of surviving (not breaching) through each horizon, in sessions.

    Opinionated wrapper over :func:`lab.risk.montecarlo.simulate_paths` --
    read that function's docstring for exactly what "survived", "breached"
    and "censored" mean, and check the ``censored`` column before trusting a
    probability computed from a trade history much shorter than the horizon.
    """
    mc = simulate_paths(
        trades, rules, n_paths, method=method, seed=seed, block_size=block_size, horizons=horizons,
    )
    out = mc.survival_curve.copy()
    out.insert(0, "account", rules.name)
    return out


def sessions_to_payout(
    trades: Sequence[Trade],
    rules: AccountRules,
    *,
    n_paths: int = 1000,
    method: BootstrapMethod = "block",
    seed: int = 0,
    block_size: int | None = None,
) -> pd.DataFrame:
    """Distribution of sessions-to-first-eligibility, per payout path, across bootstrap paths.

    One row per (Monte Carlo path, payout path) pair -- long/tidy format so
    ``groupby("payout_path")["sessions_to_eligibility"]`` gets you the
    distribution directly. Empty (with the right columns) when ``rules`` has
    no ``payout_paths`` at all (e.g. an evaluation/Combine account).
    """
    cols = ["account", "path_id", "payout_path", "eligible", "sessions_to_eligibility"]
    if not rules.payout_paths:
        return pd.DataFrame(columns=cols)
    mc = simulate_paths(
        trades, rules, n_paths, method=method, seed=seed, block_size=block_size, keep_runs=True,
    )
    rows = [
        {
            "account": rules.name,
            "path_id": pid,
            "payout_path": name,
            "eligible": elig.eligible,
            "sessions_to_eligibility": elig.sessions_to_eligibility,
        }
        for pid, run in enumerate(mc.runs)
        for name, elig in run.payout_eligibility.items()
    ]
    return pd.DataFrame(rows, columns=cols)


def post_payout_buffer(trades: Sequence[Trade], rules: AccountRules, payout_amount: float | None = None) -> pd.DataFrame:
    """How much profit to leave in so a withdrawal doesn't itself trip the MLL.

    **Modelling assumption** (no firm rule was supplied for this): a
    withdrawal reduces realised equity going forward but does **not** reduce
    the trailing MLL threshold -- the threshold reflects a high-water mark
    already reached, and prop firms do not claw back trailing progress just
    because a payout was taken. Under that assumption, the largest safe
    payout at any point is exactly the headroom at that point:
    ``equity - mll_threshold``. Pass ``payout_amount`` to also see the
    resulting cushion (or shortfall, if negative) after taking that specific
    amount out. One row per eligible payout path; ``eligible=False`` rows
    carry no dollar figures because "when" is undefined.
    """
    run = AccountSimulator(rules).run(trades)
    rows = []
    for name, elig in run.payout_eligibility.items():
        if not elig.eligible or elig.eligible_on is None:
            rows.append({
                "account": rules.name, "payout_path": name, "eligible": False,
                "eligible_on": None, "equity": None, "mll_threshold": None,
                "headroom": None, "max_safe_payout": None,
                "requested_payout": payout_amount, "post_payout_headroom": None,
            })
            continue
        d = elig.eligible_on
        equity = float(run.equity_curve.loc[d])
        threshold = float(run.mll_threshold.loc[d])
        headroom = equity - threshold
        post = None if payout_amount is None else headroom - payout_amount
        rows.append({
            "account": rules.name, "payout_path": name, "eligible": True,
            "eligible_on": d, "equity": equity, "mll_threshold": threshold,
            "headroom": headroom, "max_safe_payout": max(headroom, 0.0),
            "requested_payout": payout_amount, "post_payout_headroom": post,
        })
    return pd.DataFrame(rows)


def daily_stop_sweep(trades: Sequence[Trade], rules: AccountRules, stops: Sequence[float]) -> pd.DataFrame:
    """Deterministic replay of the *same* trade history under each candidate personal daily stop.

    The point is to pick a stop from evidence: this is not a Monte Carlo --
    it answers "given exactly what happened, would this stop have helped or
    hurt", for each candidate in ``stops``, plus a baseline row using
    ``rules.personal_daily_stop`` unchanged (``None`` if the rule set does not
    set one) so the sweep is directly comparable to doing nothing.
    """
    def _row(stop: float | None) -> dict:
        r = rules if stop == rules.personal_daily_stop else rules.with_(personal_daily_stop=stop)
        run = AccountSimulator(r).run(trades)
        return {
            "account": rules.name,
            "personal_daily_stop": stop,
            "is_baseline": stop == rules.personal_daily_stop,
            "breached": run.breached,
            "days_survived": run.days_survived,
            "trades_taken": run.trades_taken,
            "trades_skipped": run.trades_skipped,
            "final_equity": run.final_equity,
            "net_pnl": run.net_pnl,
            "min_mll_headroom": run.min_mll_headroom,
            "max_intraday_drawdown": run.max_intraday_drawdown,
        }

    rows = [_row(rules.personal_daily_stop)]
    rows += [_row(float(stop)) for stop in stops if float(stop) != rules.personal_daily_stop]
    return pd.DataFrame(rows)


def _scale_trade_frequency(trades: Sequence[Trade], multiplier: float, extra_commission: float) -> list[Trade]:
    """Synthesize a higher/lower-frequency version of the same edge.

    A deliberate simplification, not a re-simulation of a different strategy
    (that would require re-running the backtest, out of this module's remit):
    for ``multiplier >= 1`` each trade is repeated ``round(multiplier)``
    times, with every repeat past the first paying one extra
    ``extra_commission`` round-turn that the original trade did not pay --
    modelling "took this same setup more often" without inventing new signal.
    For ``multiplier < 1``, trades are thinned systematically (every
    ``round(1/multiplier)``-th trade kept), not randomly dropped, so the
    comparison stays deterministic.
    """
    if multiplier <= 0:
        raise ValueError("multiplier must be > 0")
    ordered = sorted(trades, key=lambda t: (t.exit_ts, t.entry_ts))
    if multiplier >= 1:
        reps = max(1, round(multiplier))
        out: list[Trade] = []
        for t in ordered:
            for k in range(reps):
                extra = extra_commission if k > 0 else 0.0
                out.append(replace(t, pnl=t.pnl - extra, commission=t.commission + extra))
        return out
    stride = max(1, round(1 / multiplier))
    return [t for i, t in enumerate(ordered) if i % stride == 0]


def frequency_analysis(
    trades: Sequence[Trade],
    rules: AccountRules,
    multipliers: Sequence[float],
    *,
    commission_per_rt: float | None = None,
) -> pd.DataFrame:
    """Does trading more (or less) actually help, net of commission and slippage?

    ``multipliers`` are frequency scale factors (``2.0`` = twice as many
    trades, ``0.5`` = half). See :func:`_scale_trade_frequency` for exactly
    how "more trades" is synthesized -- it is a simplification, flagged as
    such. ``commission_per_rt`` overrides ``rules.commission_per_rt`` (itself
    a symbol-agnostic placeholder -- pass in the real instrument's
    ``commission_round_turn`` for an honest answer).
    """
    commission = rules.commission_per_rt if commission_per_rt is None else commission_per_rt
    rows = []
    for m in multipliers:
        synth = _scale_trade_frequency(trades, float(m), commission)
        run = AccountSimulator(rules).run(synth)
        n = run.trades_taken
        rows.append({
            "account": rules.name,
            "multiplier": m,
            "n_trades": len(synth),
            "trades_taken": n,
            "trades_skipped": run.trades_skipped,
            "breached": run.breached,
            "final_equity": run.final_equity,
            "net_pnl": run.net_pnl,
            "expectancy_per_trade": (run.net_pnl / n) if n else float("nan"),
            "total_commission_est": float(sum(t.commission for t in synth)),
            "days_survived": run.days_survived,
        })
    return pd.DataFrame(rows)


def consecutive_loss_analysis(trades: Sequence[Trade], rules: AccountRules, n: int = 5) -> pd.DataFrame:
    """Account state after N straight losing trades: observed, and projected.

    Two complementary views, since a real N-in-a-row cluster may simply not
    have occurred in the sample even though the edge's loss distribution makes
    one plausible (for a distributional answer to "how likely is an N-loss
    streak", use :mod:`lab.risk.montecarlo` instead):

    * ``kind="historical"`` rows -- every point in the actual, chronological,
      *executed* trade sequence (lockout-skipped trades excluded, since they
      never touched the account) where at least ``n`` consecutive trades lost
      money, reporting equity/threshold/headroom immediately after the
      ``n``-th loss.
    * ``kind="projected_avg_loss"`` / ``"projected_worst_loss"`` rows -- a
      forward stress test from the account's actual final state: if the next
      ``n`` trades were all losers of the historically typical (mean) or
      worst-observed size, would that breach? Uses the final, already-trailed
      threshold with no further trailing applied during the hypothetical
      streak -- a deliberately conservative snapshot, not a full replay.
    """
    if n <= 0:
        raise ValueError("n must be > 0")
    run = AccountSimulator(rules).run(trades)
    trace = run.trade_trace
    rows: list[dict] = []

    if len(trace) >= n:
        is_loss = (trace["pnl"] < 0).to_numpy()
        streak = 0
        for i in range(len(trace)):
            streak = streak + 1 if is_loss[i] else 0
            if streak >= n:
                row = trace.iloc[i]
                rows.append({
                    "account": rules.name,
                    "kind": "historical",
                    "ends_at": row["exit_ts"],
                    "streak_length": int(streak),
                    "equity_after": float(row["equity_after"]),
                    "mll_threshold_active": float(row["mll_threshold_active"]),
                    "headroom": float(row["headroom"]),
                    "would_breach": bool(row["headroom"] < 0),
                })

    losers = [t.pnl for t in trades if t.pnl < 0]
    if losers:
        final_equity = run.final_equity
        final_threshold = (
            float(run.mll_threshold.iloc[-1]) if len(run.mll_threshold) else rules.initial_threshold
        )
        for label, loss in (("projected_avg_loss", float(np.mean(losers))), ("projected_worst_loss", float(np.min(losers)))):
            projected_equity = final_equity + n * loss
            headroom = projected_equity - final_threshold
            rows.append({
                "account": rules.name,
                "kind": label,
                "ends_at": None,
                "streak_length": n,
                "equity_after": projected_equity,
                "mll_threshold_active": final_threshold,
                "headroom": headroom,
                "would_breach": headroom < 0,
            })

    return pd.DataFrame(rows)


def account_size_comparison(trades: Sequence[Trade], presets: Sequence[AccountRules]) -> pd.DataFrame:
    """Same trade sequence, replayed once per account preset (e.g. 50K/100K/150K)."""
    rows = []
    for rules in presets:
        run = AccountSimulator(rules).run(trades)
        rows.append({
            "account": rules.name,
            "starting_balance": rules.starting_balance,
            "max_loss_limit": rules.max_loss_limit,
            "breached": run.breached,
            "breach_ts": run.breach_ts,
            "days_survived": run.days_survived,
            "trades_taken": run.trades_taken,
            "trades_skipped": run.trades_skipped,
            "final_equity": run.final_equity,
            "net_pnl": run.net_pnl,
            "max_intraday_drawdown": run.max_intraday_drawdown,
            "min_mll_headroom": run.min_mll_headroom,
            "consistency_ratio": run.consistency_ratio,
        })
    return pd.DataFrame(rows)


def consistency_analysis(trades: Sequence[Trade], rules: AccountRules) -> pd.DataFrame:
    """Can this trade distribution even satisfy the consistency payout path,
    and what would capping the biggest day(s) cost?

    "Cost to comply" iteratively caps the current largest day's realised
    profit at ``share * running_total`` and re-sums -- capping a big day
    shrinks the total, which shrinks the cap in turn, so this is a small
    fixed-point search rather than a single subtraction (bounded at 200
    iterations, which converges for any real trade distribution long before
    that). The result is a hypothetical "what if you had stopped each of
    those big days early" total, not investment advice about which trades to
    have skipped.
    """
    run = AccountSimulator(rules).run(trades)
    daily = run.daily_pnl.copy()
    total = float(daily.sum()) if not daily.empty else 0.0

    consistency_paths = [p for p in rules.payout_paths if p.kind is PayoutPathKind.CONSISTENCY]
    share = (
        rules.resolve_max_single_day_share(consistency_paths[0])
        if consistency_paths else rules.consistency_max_day_share
    )
    min_days = max(rules.min_trading_days, consistency_paths[0].min_trading_days if consistency_paths else 0)

    if daily.empty or total <= 0:
        return pd.DataFrame([{
            "account": rules.name, "n_days": int(len(daily)), "total_profit": total,
            "largest_day": float(daily.max()) if not daily.empty else None,
            "largest_day_share": None, "max_allowed_share": share,
            "satisfies_consistency": False, "meets_min_days": len(daily) >= min_days,
            "capped_total_profit": total, "cost_to_comply": 0.0,
        }])

    largest = float(daily.max())
    ratio = max(largest, 0.0) / total
    satisfies = ratio <= share and len(daily) >= min_days

    capped = daily.copy()
    for _ in range(200):
        cur_total = float(capped.sum())
        if cur_total <= 0:
            break
        cap_value = share * cur_total
        biggest_idx = capped.idxmax()
        if capped.loc[biggest_idx] <= cap_value + 1e-9:
            break
        capped.loc[biggest_idx] = cap_value
    capped_total = float(capped.sum())

    return pd.DataFrame([{
        "account": rules.name,
        "n_days": int(len(daily)),
        "total_profit": total,
        "largest_day": largest,
        "largest_day_share": ratio,
        "max_allowed_share": share,
        "satisfies_consistency": satisfies,
        "meets_min_days": len(daily) >= min_days,
        "capped_total_profit": capped_total,
        "cost_to_comply": total - capped_total,
    }])
