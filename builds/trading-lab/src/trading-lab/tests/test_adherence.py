"""Tests for lab.journal.adherence (reconcile/adherence/hesitation/slippage)
and lab.journal.costs_measure (which consumes reconcile's matched pairs)."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.core.types import LONG, SHORT, ExitReason, Signal, Trade
from lab.journal.adherence import (
    MatchTolerance,
    adherence_score,
    hesitation_analysis,
    reconcile,
    slippage_report,
)
from lab.journal.costs_measure import build_cost_overrides_yaml, measure_costs


def _signal(ts, entry, stop, direction=LONG, symbol="ES", tag="t", entry_type="market") -> Signal:
    return Signal(ts=ts, direction=direction, entry=entry, stop=stop, symbol=symbol, tag=tag,
                  strategy="asia_sweep", entry_type=entry_type)


def _trade(entry_ts, entry_price, exit_price, direction=LONG, symbol="ES", qty=1.0,
           commission=4.0, pnl=None) -> Trade:
    exit_ts = entry_ts + pd.Timedelta(minutes=15)
    if pnl is None:
        pnl = direction * (exit_price - entry_price) * 50.0 * qty - commission
    return Trade(
        symbol=symbol, strategy="asia_sweep", direction=direction, entry_ts=entry_ts,
        entry_price=entry_price, exit_ts=exit_ts, exit_price=exit_price, qty=qty, pnl=pnl,
        commission=commission, slippage_cost=0.0, risk_dollars=100.0,
        exit_reason=ExitReason.TARGET,
    )


# ---------------------------------------------------------------------------
# reconcile: the three buckets
# ---------------------------------------------------------------------------


def test_reconcile_produces_matched_unplanned_and_skipped():
    t0 = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")

    sig_matched = _signal(t0, entry=4500.00, stop=4495.00, tag="taken")
    sig_skipped = _signal(t0 + pd.Timedelta(hours=1), entry=4520.00, stop=4515.00, tag="passed")

    trade_matched = _trade(t0 + pd.Timedelta(minutes=2), entry_price=4500.50, exit_price=4505.00)
    trade_unplanned = _trade(t0 + pd.Timedelta(hours=3), entry_price=4530.00, exit_price=4528.00)

    result = reconcile(
        executed_trades=[trade_matched, trade_unplanned],
        expected_signals=[sig_matched, sig_skipped],
        tolerance=MatchTolerance(time=pd.Timedelta(minutes=10), price_ticks=5),
    )

    assert len(result.matched) == 1
    assert result.matched[0].signal is sig_matched
    assert result.matched[0].trade is trade_matched
    assert result.unplanned == [trade_unplanned]
    assert result.skipped == [sig_skipped]


def test_reconcile_respects_price_tolerance():
    t0 = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")
    sig = _signal(t0, entry=4500.00, stop=4495.00)
    # filled 10 ticks away (2.5 pts) -- outside a 3-tick tolerance
    trade = _trade(t0 + pd.Timedelta(minutes=1), entry_price=4502.50, exit_price=4505.00)

    result = reconcile([trade], [sig], tolerance=MatchTolerance(time=pd.Timedelta(minutes=10), price_ticks=3))
    assert result.matched == []
    assert result.unplanned == [trade]
    assert result.skipped == [sig]


def test_matched_pair_slippage_is_signed_adverse_positive():
    t0 = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")
    sig = _signal(t0, entry=4500.00, stop=4495.00, direction=LONG)
    # long filled 1 tick worse (higher) than planned -> adverse -> positive slippage
    trade = _trade(t0 + pd.Timedelta(minutes=1), entry_price=4500.25, exit_price=4505.00, direction=LONG)

    result = reconcile([trade], [sig], tolerance=MatchTolerance(time=pd.Timedelta(minutes=10), price_ticks=5))
    assert len(result.matched) == 1
    assert result.matched[0].slippage_ticks == pytest.approx(1.0)
    assert result.matched[0].slippage_dollars > 0


# ---------------------------------------------------------------------------
# adherence_score
# ---------------------------------------------------------------------------


def test_adherence_score_ratios():
    t0 = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")
    sig1 = _signal(t0, entry=4500.00, stop=4495.00, tag="a")
    sig2 = _signal(t0 + pd.Timedelta(hours=1), entry=4510.00, stop=4505.00, tag="b")  # skipped
    trade1 = _trade(t0, entry_price=4500.00, exit_price=4505.00)
    trade2 = _trade(t0 + pd.Timedelta(hours=2), entry_price=4530.00, exit_price=4528.00)  # unplanned

    result = reconcile([trade1, trade2], [sig1, sig2])
    score = adherence_score(result)
    assert score.matched == 1 and score.skipped == 1 and score.unplanned == 1
    assert score.taken_rate == pytest.approx(0.5)      # 1 matched of 2 signals
    assert score.discipline_rate == pytest.approx(0.5)  # 1 matched of 2 trades
    assert score.overall == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# hesitation_analysis: skip rate rising after a loss
# ---------------------------------------------------------------------------


def _journal_frame(rows: list[dict]) -> pd.DataFrame:
    from lab.journal.journal import JOURNAL_COLUMNS

    df = pd.DataFrame(rows)
    for col in JOURNAL_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def test_hesitation_analysis_detects_skip_rate_rising_after_a_loss():
    base = pd.Timestamp("2026-08-03 13:00", tz="UTC")
    rows = [
        {"status": "executed", "entry_ts": base, "signal_ts": base, "pnl": -100.0},
        {"status": "skipped", "signal_ts": base + pd.Timedelta(minutes=10)},  # after loss -> skipped
        {"status": "executed", "entry_ts": base + pd.Timedelta(minutes=20),
         "signal_ts": base + pd.Timedelta(minutes=20), "pnl": 150.0},
        {"status": "executed", "entry_ts": base + pd.Timedelta(minutes=30),
         "signal_ts": base + pd.Timedelta(minutes=30), "pnl": -50.0},
        {"status": "skipped", "signal_ts": base + pd.Timedelta(minutes=40)},  # after loss -> skipped
        {"status": "executed", "entry_ts": base + pd.Timedelta(minutes=50),
         "signal_ts": base + pd.Timedelta(minutes=50), "pnl": 80.0},
        {"status": "executed", "entry_ts": base + pd.Timedelta(minutes=60),
         "signal_ts": base + pd.Timedelta(minutes=60), "pnl": 90.0},  # after win -> taken
    ]
    # "after a loss" persists across every event until the next executed trade
    # closes: events 2 (skip), 3 (executed) and 5 (skip), 6 (executed) all fall
    # while the most recently completed trade was a loss -- 4 events, 2 skips.
    result = hesitation_analysis(_journal_frame(rows))
    assert result["n_events_after_loss"] == 4
    assert result["skip_rate_after_loss"] == pytest.approx(0.5)
    assert result["n_events_after_other"] == 2  # events 4 and 7, following wins
    assert result["skip_rate_after_win_or_flat"] == pytest.approx(0.0)
    assert result["delta"] == pytest.approx(0.5)
    assert "hesitation detected" in result["verdict"]


def test_hesitation_analysis_handles_no_events():
    from lab.journal.journal import JOURNAL_COLUMNS

    empty = pd.DataFrame(columns=list(JOURNAL_COLUMNS))
    result = hesitation_analysis(empty)
    assert result["verdict"] == "insufficient data"


# ---------------------------------------------------------------------------
# slippage_report
# ---------------------------------------------------------------------------


def test_slippage_report_columns_and_values():
    t0 = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")
    sig = _signal(t0, entry=4500.00, stop=4495.00)
    trade = _trade(t0 + pd.Timedelta(minutes=1), entry_price=4500.50, exit_price=4505.00)
    result = reconcile([trade], [sig], tolerance=MatchTolerance(time=pd.Timedelta(minutes=10), price_ticks=5))

    report = slippage_report(result.matched)
    assert not report.empty
    assert set(["symbol", "theoretical_entry", "actual_entry", "slippage_ticks", "slippage_dollars"]).issubset(report.columns)
    assert report.iloc[0]["slippage_ticks"] == pytest.approx(2.0)  # 0.50 / 0.25 tick size


def test_slippage_report_empty_input():
    report = slippage_report([])
    assert report.empty


# ---------------------------------------------------------------------------
# costs_measure: refuses small samples, otherwise emits a pasteable block
# ---------------------------------------------------------------------------


def _matched_pairs(n: int, symbol="ES", slip_ticks=1.0, commission=4.0, entry_type="market") -> list:
    t0 = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")
    pairs = []
    for i in range(n):
        sig = _signal(t0 + pd.Timedelta(minutes=i), entry=4500.00, stop=4495.00,
                       symbol=symbol, entry_type=entry_type)
        trade = _trade(t0 + pd.Timedelta(minutes=i), entry_price=4500.00 + slip_ticks * 0.25,
                        exit_price=4505.00, symbol=symbol, commission=commission)
        result = reconcile([trade], [sig], tolerance=MatchTolerance(time=pd.Timedelta(minutes=5), price_ticks=5))
        pairs.extend(result.matched)
    return pairs


def test_measure_costs_computes_stats_regardless_of_sample_size():
    pairs = _matched_pairs(5)
    estimates = measure_costs(pairs)
    assert "ES" in estimates
    est = estimates["ES"]
    assert est.n == 5
    assert est.commission_median == pytest.approx(4.0)
    assert est.slippage_ticks_p80_abs == pytest.approx(1.0)


def test_build_cost_overrides_refuses_small_sample():
    pairs = _matched_pairs(6)  # well under the default minimum of 50
    estimates = measure_costs(pairs)
    with pytest.raises(ValueError, match="50"):
        build_cost_overrides_yaml(estimates)


def test_build_cost_overrides_emits_yaml_with_enough_samples():
    pairs = _matched_pairs(60)
    estimates = measure_costs(pairs)
    yaml_block = build_cost_overrides_yaml(estimates, min_samples=50)
    assert "cost_overrides:" in yaml_block
    assert "ES:" in yaml_block
    assert "commission_round_turn: 4.0" in yaml_block
    assert "default_slippage_ticks: 1.0" in yaml_block


def test_build_cost_overrides_honours_custom_min_samples():
    pairs = _matched_pairs(10)
    estimates = measure_costs(pairs)
    yaml_block = build_cost_overrides_yaml(estimates, min_samples=5)
    assert "ES:" in yaml_block
