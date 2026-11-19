"""The account state machine: trailing MLL, unrealised breach, lockout, payouts.

Every number asserted here is worked out by hand in the comments. That is the
point — the account simulator is the module whose output most directly changes
what a person risks, so its arithmetic should be checkable without running it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lab.risk.account import AccountSimulator
from lab.risk.rules import (
    LockAt,
    TOPSTEP_EXPRESS_FUNDED_50K,
    TOPSTEP_FUNDED_50K,
    TOPSTEP_FUNDED_150K,
    TrailOn,
)
from tests.helpers import mk_trade


def test_threshold_trails_equity_up_then_locks_at_starting_balance():
    # Funded 50K: start 50,000, MLL 2,000 -> initial threshold 48,000.
    # Day 1 +1,000 -> equity 51,000, threshold max(48,000, 49,000) = 49,000.
    # Day 2 +1,000 -> equity 52,000, threshold would be 50,000 == starting
    #                 balance, so it clamps there and locks forever.
    # Day 3 +5,000 -> equity 57,000, threshold stays 50,000 despite the profit.
    trades = [
        mk_trade("2026-01-05", 1_000.0),
        mk_trade("2026-01-06", 1_000.0),
        mk_trade("2026-01-07", 5_000.0),
    ]
    run = AccountSimulator(TOPSTEP_FUNDED_50K).run(trades)

    assert not run.breached
    assert run.final_equity == pytest.approx(57_000.0)
    assert list(run.mll_threshold) == pytest.approx([49_000.0, 50_000.0, 50_000.0])
    assert run.days_survived == 3


def test_locked_threshold_does_not_follow_a_later_new_peak():
    # Once locked, a subsequent drawdown must be measured against the locked
    # floor. A 6,000 give-back from 57,000 lands at 51,000 -- still above the
    # locked 50,000 floor, so the account survives. If the threshold had kept
    # trailing (55,500) this would have been a breach.
    trades = [
        mk_trade("2026-01-05", 1_000.0),
        mk_trade("2026-01-06", 1_000.0),
        mk_trade("2026-01-07", 5_000.0),
        mk_trade("2026-01-08", -6_000.0),
    ]
    run = AccountSimulator(TOPSTEP_FUNDED_50K).run(trades)
    assert not run.breached
    assert run.final_equity == pytest.approx(51_000.0)


def test_never_locking_rules_keep_trailing_and_breach_the_same_giveback():
    # Same trades, one rule changed: proves the lock behaviour is the thing
    # doing the work, not an accident of the numbers.
    rules = TOPSTEP_FUNDED_50K.with_(lock_at=LockAt.NEVER)
    trades = [
        mk_trade("2026-01-05", 1_000.0),
        mk_trade("2026-01-06", 1_000.0),
        mk_trade("2026-01-07", 5_000.0),  # threshold trails to 55,000
        mk_trade("2026-01-08", -6_000.0),  # equity 51,000 < 55,000 -> breach
    ]
    run = AccountSimulator(rules).run(trades)
    assert run.breached
    assert "realised breach" in run.breach_reason


def test_unrealised_drawdown_breaches_an_otherwise_winning_trade():
    # The headline case. Closed PnL is +500, so a realised-only model would
    # report a profitable day. But the position was 2,500 underwater at its
    # worst: 50,000 - 2,500 = 47,500, below the 48,000 floor. The account is
    # gone before the trade ever gets back to green.
    trade = mk_trade("2026-01-05", 500.0, mae=-2_500.0, mfe=800.0)
    run = AccountSimulator(TOPSTEP_FUNDED_50K).run([trade])

    assert run.breached
    assert "unrealised" in run.breach_reason
    assert run.final_equity == pytest.approx(47_500.0)
    assert run.trades_taken == 1


def test_the_same_trade_survives_when_the_rules_ignore_unrealised_pnl():
    rules = TOPSTEP_FUNDED_50K.with_(includes_unrealized=False)
    trade = mk_trade("2026-01-05", 500.0, mae=-2_500.0, mfe=800.0)
    run = AccountSimulator(rules).run([trade])

    assert not run.breached
    assert run.final_equity == pytest.approx(50_500.0)


def test_personal_daily_stop_removes_later_trades_that_day():
    # -200 then -150 crosses a -300 personal stop, so the third trade of the day
    # never happens. It is *removed*, not merely flagged: a simulator that let
    # it through would be answering a question about a discipline you did not
    # have. The next day trades normally.
    rules = TOPSTEP_FUNDED_50K.with_(personal_daily_stop=300.0)
    trades = [
        mk_trade("2026-01-05", -200.0, hhmm="08:45"),
        mk_trade("2026-01-05", -150.0, hhmm="09:15"),
        mk_trade("2026-01-05", -1_000.0, hhmm="10:00"),  # never taken
        mk_trade("2026-01-06", 400.0),
    ]
    run = AccountSimulator(rules).run(trades)

    assert run.trades_taken == 3
    assert run.trades_skipped == 1
    assert run.skipped_trades[0].reason == "personal_daily_stop"
    assert run.skipped_trades[0].trading_day.isoformat() == "2026-01-05"
    # 50,000 - 200 - 150 + 400
    assert run.final_equity == pytest.approx(50_050.0)


def test_firm_daily_loss_limit_and_personal_stop_report_together():
    rules = TOPSTEP_FUNDED_50K.with_(personal_daily_stop=300.0, daily_loss_limit=300.0)
    trades = [
        mk_trade("2026-01-05", -350.0, hhmm="08:45"),
        mk_trade("2026-01-05", -100.0, hhmm="09:45"),
    ]
    run = AccountSimulator(rules).run(trades)
    assert run.skipped_trades[0].reason == "personal_daily_stop+daily_loss_limit"


def test_express_funded_floor_sits_below_zero():
    # Starting balance 0, MLL 2,000 -> the floor is -2,000, not 48,000.
    run = AccountSimulator(TOPSTEP_EXPRESS_FUNDED_50K).run(
        [mk_trade("2026-01-05", -2_100.0)]
    )
    assert run.breached
    assert run.final_equity == pytest.approx(-2_100.0)

    survives = AccountSimulator(TOPSTEP_EXPRESS_FUNDED_50K).run(
        [mk_trade("2026-01-05", -1_900.0)]
    )
    assert not survives.breached


def test_standard_payout_path_can_pass_while_consistency_fails():
    # Four modest days plus one outsized day. Five winning days >= $150 clears
    # the standard path; the 2,000 day is 75.8% of the 2,640 total, so the 40%
    # consistency path does not. This is exactly why ten $30 trades are not
    # automatically better than one $300 trade -- the rules measure shape, not
    # effort.
    trades = [
        mk_trade("2026-01-05", 160.0),
        mk_trade("2026-01-06", 160.0),
        mk_trade("2026-01-07", 160.0),
        mk_trade("2026-01-08", 160.0),
        mk_trade("2026-01-09", 2_000.0),
    ]
    run = AccountSimulator(TOPSTEP_FUNDED_150K).run(trades)

    elig = run.payout_eligibility
    assert elig["standard_5x150"].eligible_at_end is True
    # The consistency path was briefly satisfiable on day 3, before the outsized
    # day arrived -- but it is not satisfiable now, and "now" is when a payout
    # would actually be requested.
    assert elig["consistency_40pct"].eligible is True
    assert elig["consistency_40pct"].eligible_at_end is False
    assert run.consistency_ratio == pytest.approx(2_000.0 / 2_640.0)


def test_consistency_path_can_pass_while_standard_fails():
    # Three even $100 days: nothing clears the $150 winning-day bar, so the
    # standard path fails, but the largest day is 33% of the total, inside 40%.
    trades = [
        mk_trade("2026-01-05", 100.0),
        mk_trade("2026-01-06", 100.0),
        mk_trade("2026-01-07", 100.0),
    ]
    run = AccountSimulator(TOPSTEP_FUNDED_150K).run(trades)

    assert run.payout_eligibility["standard_5x150"].eligible is False
    assert run.payout_eligibility["standard_5x150"].eligible_at_end is False
    assert run.payout_eligibility["consistency_40pct"].eligible is True
    assert run.payout_eligibility["consistency_40pct"].eligible_at_end is True
    assert run.payout_eligibility["consistency_40pct"].sessions_to_eligibility == 3


def test_trades_are_replayed_in_exit_order_regardless_of_input_order():
    ordered = [mk_trade("2026-01-05", 1_000.0), mk_trade("2026-01-06", -500.0)]
    shuffled = list(reversed(ordered))
    a = AccountSimulator(TOPSTEP_FUNDED_50K).run(ordered)
    b = AccountSimulator(TOPSTEP_FUNDED_50K).run(shuffled)
    assert a.final_equity == b.final_equity
    assert list(a.mll_threshold) == list(b.mll_threshold)


def test_headroom_records_the_worst_moment_not_the_final_state():
    # Equity ends up healthy, but a mid-run trade came within 200 of the floor.
    # Reporting only the final headroom would hide the near-death experience.
    trades = [
        mk_trade("2026-01-05", -1_800.0),  # equity 48,200, threshold 48,000
        mk_trade("2026-01-06", 3_000.0),
    ]
    run = AccountSimulator(TOPSTEP_FUNDED_50K).run(trades)
    assert not run.breached
    assert run.min_mll_headroom == pytest.approx(200.0)


def test_simulation_stops_at_the_breach():
    # Nothing after a breach is real: the account no longer exists.
    trades = [
        mk_trade("2026-01-05", -2_500.0),
        mk_trade("2026-01-06", 10_000.0),
    ]
    run = AccountSimulator(TOPSTEP_FUNDED_50K).run(trades)
    assert run.breached
    assert run.trades_taken == 1
    assert run.final_equity == pytest.approx(47_500.0)
    assert isinstance(run.breach_ts, pd.Timestamp)


def test_empty_trade_sequence_is_well_formed():
    run = AccountSimulator(TOPSTEP_FUNDED_50K).run([])
    assert not run.breached
    assert run.days_survived == 0
    assert run.final_equity == pytest.approx(50_000.0)
    assert run.trade_trace.empty


def test_intraday_peak_trailing_is_stricter_than_eod_trailing():
    # A day that spikes +3,000 and closes +500. Under EOD trailing the peak is
    # the close; under intraday-peak trailing the spike ratchets the floor up
    # by 3,000. Same trades, different survival -- which is why the mechanic is
    # a configuration field and not an assumption.
    trades = [
        mk_trade("2026-01-05", 500.0, mfe=3_000.0),
        mk_trade("2026-01-06", -1_800.0),
    ]
    eod = AccountSimulator(TOPSTEP_FUNDED_50K).run(trades)
    intraday = AccountSimulator(
        TOPSTEP_FUNDED_50K.with_(trail_on=TrailOn.INTRADAY_PEAK, lock_at=LockAt.NEVER)
    ).run(trades)

    assert not eod.breached
    assert intraday.breached
