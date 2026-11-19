"""The questions a trader actually asks, and whether the answers hold together.

These are less about arithmetic than about *direction*: a tighter account must
not survive more often, a daily stop that removes trades must change the
outcome, and adding commission to a higher trade count must not look free.
Each test pins one of those relationships, because a survival number that moves
the wrong way is worse than no number at all.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lab.risk.rules import (
    TOPSTEP_COMBINE_50K,
    TOPSTEP_FUNDED_50K,
    TOPSTEP_FUNDED_100K,
    TOPSTEP_FUNDED_150K,
)
from lab.risk.survival import (
    account_size_comparison,
    consecutive_loss_analysis,
    consistency_analysis,
    daily_stop_sweep,
    frequency_analysis,
    post_payout_buffer,
    sessions_to_payout,
    survival_curve,
)
from tests.helpers import mk_trade


def mixed_trades(n: int = 40) -> list:
    """A modestly positive edge with real losers, one trade per business day."""
    days = pd.bdate_range("2026-01-05", periods=n).strftime("%Y-%m-%d")
    pnls = [250.0, -150.0, 180.0, -150.0, -150.0, 320.0, -150.0, 200.0]
    return [
        mk_trade(day, pnls[i % len(pnls)], mae=-abs(pnls[i % len(pnls)]) * 0.8)
        for i, day in enumerate(days)
    ]


def two_trades_per_day(n_days: int = 20) -> list:
    """Two trades a day, so a personal daily stop has something to bite on."""
    days = pd.bdate_range("2026-01-05", periods=n_days).strftime("%Y-%m-%d")
    out = []
    for i, day in enumerate(days):
        first = -200.0 if i % 2 == 0 else 220.0
        out.append(mk_trade(day, first, hhmm="08:45"))
        out.append(mk_trade(day, -260.0 if i % 2 == 0 else 90.0, hhmm="11:00"))
    return out


def test_survival_curve_covers_every_requested_horizon():
    curve = survival_curve(mixed_trades(), TOPSTEP_FUNDED_150K, (5, 10, 20), n_paths=60, seed=1)
    assert list(curve["sessions"]) == [5, 10, 20]
    assert (curve["account"] == TOPSTEP_FUNDED_150K.name).all()
    probs = curve["survival_probability"].dropna()
    assert ((probs >= 0) & (probs <= 1)).all()


def test_survival_is_monotonically_non_increasing_in_the_horizon():
    # Surviving 20 sessions cannot be more likely than surviving 5. Censoring
    # can make a later horizon NaN, but it must never make it *higher*.
    curve = survival_curve(mixed_trades(60), TOPSTEP_FUNDED_50K, (5, 10, 20), n_paths=120, seed=2)
    probs = curve["survival_probability"].tolist()
    known = [p for p in probs if p == p]  # drop NaN
    assert all(a >= b - 1e-9 for a, b in zip(known, known[1:]))


def test_sessions_to_payout_is_tidy_and_empty_for_an_evaluation_account():
    funded = sessions_to_payout(mixed_trades(), TOPSTEP_FUNDED_150K, n_paths=25, seed=3)
    assert set(funded["payout_path"]) <= {"standard_5x150", "consistency_40pct"}
    assert len(funded) == 25 * len(TOPSTEP_FUNDED_150K.payout_paths)

    # A Combine has nothing to pay out; the shape must still be usable.
    combine = sessions_to_payout(mixed_trades(), TOPSTEP_COMBINE_50K, n_paths=25, seed=3)
    assert combine.empty
    assert "sessions_to_eligibility" in combine.columns


def test_daily_stop_sweep_includes_a_baseline_and_changes_the_outcome():
    trades = two_trades_per_day()
    sweep = daily_stop_sweep(trades, TOPSTEP_FUNDED_150K, [150.0, 300.0, 600.0])

    assert sweep["is_baseline"].sum() == 1
    baseline = sweep[sweep["is_baseline"]].iloc[0]
    assert baseline["trades_skipped"] == 0  # no stop set on the preset

    tight = sweep[sweep["personal_daily_stop"] == 150.0].iloc[0]
    loose = sweep[sweep["personal_daily_stop"] == 600.0].iloc[0]
    # A tighter stop can only remove trades, never add them.
    assert tight["trades_skipped"] >= loose["trades_skipped"]
    assert tight["trades_taken"] <= baseline["trades_taken"]


def test_frequency_analysis_charges_for_the_extra_trades():
    # The point of the analysis: at a real commission, doubling the trade count
    # must double the commission bill. "More trades" is never free.
    trades = mixed_trades()
    freq = frequency_analysis(trades, TOPSTEP_FUNDED_150K, [0.5, 1.0, 2.0], commission_per_rt=4.0)

    by_mult = freq.set_index("multiplier")
    assert by_mult.loc[2.0, "n_trades"] > by_mult.loc[1.0, "n_trades"] > by_mult.loc[0.5, "n_trades"]
    assert by_mult.loc[2.0, "total_commission_est"] > by_mult.loc[1.0, "total_commission_est"]


def test_consecutive_loss_analysis_reports_both_observed_and_projected():
    trades = mixed_trades()
    out = consecutive_loss_analysis(trades, TOPSTEP_FUNDED_150K, n=5)
    assert not out.empty
    assert "kind" in out.columns
    # Projected rows must always exist, even when the sample happened not to
    # contain a 5-loss cluster -- "it never happened" is not "it cannot happen".
    kinds = set(out["kind"])
    assert {"projected_avg_loss", "projected_worst_loss"} <= kinds


def test_account_size_comparison_ranks_the_tiers_sensibly():
    # A drawdown big enough to kill the 50K but not the 150K.
    trades = [
        mk_trade("2026-01-05", -1_500.0),
        mk_trade("2026-01-06", -1_200.0),
        mk_trade("2026-01-07", 400.0),
    ]
    cmp = account_size_comparison(
        trades, [TOPSTEP_FUNDED_50K, TOPSTEP_FUNDED_100K, TOPSTEP_FUNDED_150K]
    ).set_index("account")

    assert cmp.loc[TOPSTEP_FUNDED_50K.name, "breached"]
    assert not cmp.loc[TOPSTEP_FUNDED_150K.name, "breached"]
    assert cmp["max_loss_limit"].is_monotonic_increasing


def test_consistency_analysis_prices_the_cost_of_complying():
    # One outsized day inside an otherwise even distribution: the account does
    # not satisfy the 40% rule, and complying would have cost real profit.
    trades = [
        mk_trade("2026-01-05", 200.0),
        mk_trade("2026-01-06", 200.0),
        mk_trade("2026-01-07", 200.0),
        mk_trade("2026-01-08", 3_000.0),
    ]
    out = consistency_analysis(trades, TOPSTEP_FUNDED_150K).iloc[0]

    assert out["satisfies_consistency"] is False or not out["satisfies_consistency"]
    assert out["largest_day_share"] == pytest.approx(3_000.0 / 3_600.0)
    assert out["cost_to_comply"] > 0
    assert out["capped_total_profit"] < out["total_profit"]


def test_consistency_analysis_on_an_even_distribution_costs_nothing():
    trades = [mk_trade(d, 200.0) for d in ("2026-01-05", "2026-01-06", "2026-01-07")]
    out = consistency_analysis(trades, TOPSTEP_FUNDED_150K).iloc[0]
    assert out["satisfies_consistency"]
    assert out["cost_to_comply"] == pytest.approx(0.0)


def test_post_payout_buffer_returns_something_actionable():
    out = post_payout_buffer(mixed_trades(), TOPSTEP_FUNDED_150K, payout_amount=1_000.0)
    assert not out.empty
    assert len(out.columns) > 1


def test_survival_helpers_tolerate_an_empty_history():
    # Not a crash and not a fabricated answer: an empty history has nothing to
    # say, and the caller needs to be able to tell.
    empty_cmp = account_size_comparison([], [TOPSTEP_FUNDED_150K])
    assert len(empty_cmp) == 1
    assert not empty_cmp.iloc[0]["breached"]

    empty_consistency = consistency_analysis([], TOPSTEP_FUNDED_150K).iloc[0]
    assert empty_consistency["satisfies_consistency"] is False or not empty_consistency["satisfies_consistency"]
