"""Tests for lab.backtest.engine.BacktestEngine.

These are the tests that decide whether any number this lab produces can be
trusted: no-lookahead invariance, honest gap handling, ambiguous-bar
resolution, cost arithmetic to the cent, the "a slipped stop is worse than
-1R" accounting invariant, limit-order expiry, partial scale-outs, the daily
attempts cap, and sizing that skips rather than forces an undersized signal.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lab.backtest.costs import CostModel
from lab.backtest.engine import BacktestEngine, fixed_contracts, risk_based
from lab.backtest.exits import ExitContext, ExitDecision, ExitPolicy, MultiTargetR, PositionState
from lab.core.config import LabConfig
from lab.core.instruments import get_instrument
from lab.core.types import LONG, SHORT, ExitReason, Signal

_INST = get_instrument("ES")  # tick_size 0.25, tick_value 12.50 -> point_value 50.0


class NoOpExit:
    """An ExitPolicy that never sets targets and never acts -- lets a test
    control entry/stop/target prices entirely through the Signal itself and
    isolate pure engine fill mechanics."""

    def initial_targets(self, signal: Signal, ctx: ExitContext):
        return (), None

    def check(self, signal: Signal, position: PositionState, bar: pd.Series, ctx: ExitContext):
        return None


def _bars(rows: list[tuple[str, float, float, float, float, float]]) -> pd.DataFrame:
    """rows: (ts, open, high, low, close, volume), ts a bare 'HH:MM' on 2024-01-02 UTC."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"2024-01-02 {r[0]}", tz="UTC") for r in rows], name="ts")
    df = pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [r[5] for r in rows],
        },
        index=idx,
    )
    return df


def _engine(cost_model: CostModel | None = None, *, pessimistic: bool = True, **kwargs) -> BacktestEngine:
    cfg = LabConfig(pessimistic_intrabar=pessimistic)
    cm = cost_model or CostModel(commission_round_turn=4.0, slippage_ticks=1.0)
    return BacktestEngine(_INST, cm, cfg, **kwargs)


def _sig(ts, direction, entry, stop, **kwargs) -> Signal:
    return Signal(ts=pd.Timestamp(f"2024-01-02 {ts}", tz="UTC"), direction=direction, entry=entry, stop=stop,
                  symbol="ES", strategy="t", **kwargs)


# --------------------------------------------------------------------------
# No-lookahead invariance -- the most important test in the repo
# --------------------------------------------------------------------------


def test_no_lookahead_invariance_appending_future_bars_does_not_change_trades() -> None:
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),  # decision bar
        ("09:01", 4800, 4801, 4799, 4800, 500),  # entry fill bar (market)
        ("09:02", 4805, 4812, 4804, 4811, 500),  # touches target (4810)
        ("09:03", 4811, 4813, 4809, 4812, 500),
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market", targets=(4810.0,))
    engine = _engine()

    result1 = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    assert len(result1.trades) == 1
    assert result1.trades[0].exit_reason == ExitReason.TARGET

    # Append bars far beyond where the trade already resolved -- including
    # ones that, if the engine leaked forward, could plausibly change
    # something (a big adverse move well after the target already filled).
    future = _bars([
        ("09:04", 4812, 4813, 3000, 4812, 500),  # absurd low, must be irrelevant: position is closed
        ("09:05", 4812, 4900, 4800, 4850, 500),
    ])
    extended = pd.concat([bars, future])
    result2 = engine.run(extended, [sig], NoOpExit(), fixed_contracts(1), strategy="t")

    assert len(result2.trades) == len(result1.trades) == 1
    t1, t2 = result1.trades[0], result2.trades[0]
    assert t1.entry_ts == t2.entry_ts
    assert t1.entry_price == t2.entry_price
    assert t1.exit_ts == t2.exit_ts
    assert t1.exit_price == t2.exit_price
    assert t1.pnl == pytest.approx(t2.pnl)
    assert t1.exit_reason == t2.exit_reason


# --------------------------------------------------------------------------
# Gap handling
# --------------------------------------------------------------------------


def test_gap_through_stop_fills_at_open_not_stop_price() -> None:
    cm = CostModel(commission_round_turn=4.0, slippage_ticks=0.0)  # isolate the gap rule from slippage
    engine = _engine(cm)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),  # entry fill bar
        ("09:02", 4785, 4786, 4784, 4785, 500),  # gaps straight through the 4790 stop
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market")
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == ExitReason.STOP
    assert trade.exit_price == pytest.approx(4785.0)  # the bar's open, not 4790.0


def test_ordinary_stop_touch_fills_at_stop_price_not_open() -> None:
    cm = CostModel(commission_round_turn=4.0, slippage_ticks=0.0)
    engine = _engine(cm)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4796, 4797, 4789, 4795, 500),  # open above stop, low touches it intrabar
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market")
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    trade = result.trades[0]
    assert trade.exit_reason == ExitReason.STOP
    assert trade.exit_price == pytest.approx(4790.0)  # exactly the stop, no slippage configured


def test_favourable_gap_through_target_fills_at_open_not_target_price() -> None:
    cm = CostModel(commission_round_turn=4.0, slippage_ticks=0.0)
    engine = _engine(cm)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4815, 4820, 4813, 4818, 500),  # opens above the 4810 target
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market", targets=(4810.0,))
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    trade = result.trades[0]
    assert trade.exit_reason == ExitReason.TARGET
    assert trade.exit_price == pytest.approx(4815.0)  # the open (better than the stated target), not 4810.0


# --------------------------------------------------------------------------
# Ambiguous bars: stop and target both in range
# --------------------------------------------------------------------------


def test_ambiguous_bar_resolves_stop_first_under_pessimistic_default() -> None:
    engine = _engine(pessimistic=True)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4800, 4815, 4785, 4800, 500),  # spans both stop (4790) and target (4810)
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market", targets=(4810.0,))
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == ExitReason.STOP
    assert result.stats["ambiguous_bars_total"] == 1
    assert result.stats["ambiguous_bars_resolved_by_pessimistic_default"] == 1
    assert result.stats["ambiguous_bars_resolved_by_finer_bars"] == 0


def test_ambiguous_bar_resolves_via_finer_bars_when_they_prove_target_first() -> None:
    engine = _engine(pessimistic=True)  # pessimistic default would say stop -- finer_bars should override
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4800, 4815, 4785, 4800, 500),  # same ambiguous coarse bar as above
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market", targets=(4810.0,))
    # sub-bars inside [09:02, 09:03): target touched first, stop only afterwards
    finer = _bars([
        ("09:02", 4800, 4812, 4799, 4810, 100),  # touches the 4810 target, stop untouched
        ("09:02", 4810, 4811, 4784, 4790, 100),  # (same coarse minute) then drops through the stop
    ])
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), finer, strategy="t")
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == ExitReason.TARGET
    assert trade.exit_price == pytest.approx(4810.0)
    assert result.stats["ambiguous_bars_resolved_by_finer_bars"] == 1
    assert result.stats["ambiguous_bars_resolved_by_pessimistic_default"] == 0
    assert result.stats["ambiguous_bars_total"] == 1


# --------------------------------------------------------------------------
# Cost arithmetic to the cent, on one known ES trade
# --------------------------------------------------------------------------


def test_cost_arithmetic_to_the_cent_on_one_es_trade() -> None:
    cm = CostModel(commission_round_turn=4.0, slippage_ticks=1.0)
    engine = _engine(cm)
    bars = _bars([
        ("09:00", 4799, 4801, 4798, 4800, 500),  # decision bar
        ("09:01", 4802, 4803, 4801, 4802.5, 500),  # entry fill bar (market): open 4802.00
        ("09:02", 4805, 4813.00, 4804, 4810, 500),  # touches the 4812.25 target
    ])
    sig = _sig("09:00", LONG, 4802.0, 4790.0, entry_type="market", targets=(4812.25,))
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    assert len(result.trades) == 1
    trade = result.trades[0]

    # entry: market fill at bar open (4802.00) + 1 tick adverse slippage (buy -> higher)
    expected_entry = 4802.00 + 1 * 0.25
    assert trade.entry_price == pytest.approx(expected_entry, abs=1e-9)
    assert trade.entry_price == pytest.approx(4802.25, abs=1e-9)

    # exit: target fill at the exact stated price, no slippage
    assert trade.exit_price == pytest.approx(4812.25, abs=1e-9)
    assert trade.exit_reason == ExitReason.TARGET

    gross = (trade.exit_price - trade.entry_price) * 1 * 50.0  # point_value = 50
    assert gross == pytest.approx(500.00, abs=1e-9)

    assert trade.commission == pytest.approx(4.00, abs=1e-9)  # 1 contract, full round turn
    # entry paid 1 tick of slippage; target exit pays none
    assert trade.slippage_cost == pytest.approx(0.25 * 50.0, abs=1e-9)  # 12.50
    assert trade.slippage_cost == pytest.approx(12.50, abs=1e-9)

    expected_pnl = gross - trade.commission
    assert trade.pnl == pytest.approx(496.00, abs=1e-9)
    assert trade.pnl == pytest.approx(expected_pnl, abs=1e-9)

    # risk_dollars is computed from the *signal's* nominal entry/stop (4802/4790 -> 12 pts)
    assert trade.risk_dollars == pytest.approx(12.0 * 1 * 50.0, abs=1e-9)
    assert trade.risk_dollars == pytest.approx(600.00, abs=1e-9)
    assert trade.r_multiple == pytest.approx(496.00 / 600.00, abs=1e-9)


# --------------------------------------------------------------------------
# The honest-accounting invariant: a slipped stop is worse than -1R
# --------------------------------------------------------------------------


def test_slipped_stop_produces_r_multiple_worse_than_minus_one() -> None:
    cm = CostModel(commission_round_turn=4.0, slippage_ticks=2.0)
    engine = _engine(cm)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),  # entry fill bar (limit @ 4800, touched, no slip)
        ("09:02", 4785, 4786, 4784, 4785, 500),  # gaps through the 4790 stop
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="limit")
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    trade = result.trades[0]

    assert trade.entry_price == pytest.approx(4800.00, abs=1e-9)  # limit: exact price, no slip
    assert trade.exit_reason == ExitReason.STOP
    # gapped stop: base = bar open (4785.00), then 2 ticks adverse slippage (sell -> lower)
    expected_exit = 4785.00 - 2 * 0.25
    assert trade.exit_price == pytest.approx(expected_exit, abs=1e-9)  # 4784.50

    gross = (trade.exit_price - trade.entry_price) * 1 * 50.0
    assert gross == pytest.approx(-775.00, abs=1e-9)
    expected_pnl = gross - trade.commission
    assert trade.pnl == pytest.approx(-779.00, abs=1e-9)
    assert trade.pnl == pytest.approx(expected_pnl, abs=1e-9)

    assert trade.risk_dollars == pytest.approx(10.0 * 1 * 50.0, abs=1e-9)  # 500.00, from nominal 4800/4790
    assert trade.r_multiple == pytest.approx(-779.00 / 500.00, abs=1e-9)
    assert trade.r_multiple < -1.0  # the honest-accounting invariant


# --------------------------------------------------------------------------
# Limit entries: never trade through, never fill; expire into `skipped`
# --------------------------------------------------------------------------


def test_limit_entry_that_never_trades_through_expires_unfilled() -> None:
    engine = _engine()
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4801, 4802, 4799.5, 4800, 500),  # low never reaches the 4750 limit
        ("09:03", 4800, 4801, 4799, 4800, 500),
    ])
    sig = _sig("09:00", LONG, 4750.0, 4740.0, entry_type="limit", valid_until=pd.Timestamp("2024-01-02 09:02", tz="UTC"))
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0]["reason"] == "expired_unfilled"
    assert result.skipped[0]["signal_ts"] == sig.ts


def test_limit_entry_that_trades_through_does_fill() -> None:
    engine = _engine(CostModel(commission_round_turn=4.0, slippage_ticks=0.0))
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4796, 4797, 4794, 4795, 500),  # low (4794) reaches the 4795 limit
    ])
    sig = _sig("09:00", LONG, 4795.0, 4785.0, entry_type="limit", valid_until=pd.Timestamp("2024-01-02 09:05", tz="UTC"))
    result = engine.run(bars, [sig], NoOpExit(), fixed_contracts(1), strategy="t")
    assert result.skipped == []
    assert len(result.trades) == 1  # position still open -> closes at DATA_END
    assert result.trades[0].entry_price == pytest.approx(4795.0)
    assert result.trades[0].exit_reason == ExitReason.DATA_END


# --------------------------------------------------------------------------
# Partial scale-outs across a MultiTargetR ladder
# --------------------------------------------------------------------------


def test_partial_scale_out_multi_target_ladder_remainder_exits_on_stop() -> None:
    cm = CostModel(commission_round_turn=4.0, slippage_ticks=0.0)
    engine = _engine(cm)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),  # entry fill bar (limit @ 4800, exact)
        ("09:02", 4805, 4812, 4804, 4811, 500),  # touches target 1 (4810) only
        ("09:03", 4795, 4796, 4785, 4790, 500),  # then the remainder stops out at 4790 (no gap)
    ])
    sig = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="limit")
    ladder = MultiTargetR(rs=(1.0, 2.0), weights=(0.5, 0.5))  # targets at 4810 and 4820
    result = engine.run(bars, [sig], ladder, fixed_contracts(4), strategy="t")

    assert len(result.trades) == 2
    leg1, leg2 = result.trades
    assert leg1.exit_reason == ExitReason.TARGET
    assert leg1.qty == pytest.approx(2.0)
    assert leg1.exit_price == pytest.approx(4810.0)
    assert leg1.commission == pytest.approx(8.0)  # 4.0 * 2 contracts
    assert leg1.pnl == pytest.approx((4810.0 - 4800.0) * 2 * 50.0 - 8.0)  # 992.00
    assert leg1.risk_dollars == pytest.approx(10.0 * 2 * 50.0)  # 1000.00

    assert leg2.exit_reason == ExitReason.STOP
    assert leg2.qty == pytest.approx(2.0)
    assert leg2.exit_price == pytest.approx(4790.0)
    assert leg2.commission == pytest.approx(8.0)
    assert leg2.pnl == pytest.approx((4790.0 - 4800.0) * 2 * 50.0 - 8.0)  # -1008.00

    # total commission across every slice of the position must equal
    # commission_round_turn * total contracts, regardless of how many
    # pieces the exit took.
    total_commission = leg1.commission + leg2.commission
    assert total_commission == pytest.approx(cm.commission_round_turn * 4.0)  # 16.00

    assert leg1.pnl + leg2.pnl == pytest.approx(992.00 - 1008.00)  # -16.00 net


# --------------------------------------------------------------------------
# max_attempts_per_day (engine-level, against the CME trading day)
# --------------------------------------------------------------------------


def test_max_attempts_per_day_blocks_a_second_fill_same_trading_day() -> None:
    engine = _engine(max_concurrent=2, max_attempts_per_day=1)
    bars = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),  # sig1 decision
        ("09:01", 4800, 4801, 4799, 4800, 500),  # sig1 fills here (market)
        ("09:02", 4800, 4801, 4799, 4800, 500),  # sig2 decision (also fills, if allowed, next bar)
        ("09:03", 4800, 4801, 4799, 4800, 500),  # sig2 would fill here -- but attempts are exhausted
        ("09:04", 4800, 4801, 4799, 4800, 500),
    ])
    sig1 = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market", tag="a")
    sig2 = _sig("09:02", LONG, 4800.0, 4790.0, entry_type="market", tag="b")
    result = engine.run(bars, [sig1, sig2], NoOpExit(), fixed_contracts(1), strategy="t")

    assert len(result.trades) == 1  # only sig1 filled
    assert len(result.skipped) == 1
    assert result.skipped[0]["reason"] == "max_attempts_per_day"
    assert result.skipped[0]["signal_ts"] == sig2.ts


def test_max_attempts_per_day_resets_on_a_new_trading_day() -> None:
    engine = _engine(max_concurrent=2, max_attempts_per_day=1)
    bars = pd.concat([
        _bars([
            ("09:00", 4800, 4801, 4799, 4800, 500),
            ("09:01", 4800, 4801, 4799, 4800, 500),
        ]),
        pd.DataFrame(
            {"open": [4800, 4800], "high": [4801, 4801], "low": [4799, 4799], "close": [4800, 4800], "volume": [500, 500]},
            index=pd.DatetimeIndex(
                [pd.Timestamp("2024-01-03 09:00", tz="UTC"), pd.Timestamp("2024-01-03 09:01", tz="UTC")], name="ts"
            ),
        ),
    ])
    sig1 = Signal(ts=pd.Timestamp("2024-01-02 09:00", tz="UTC"), direction=LONG, entry=4800.0, stop=4790.0,
                  entry_type="market", symbol="ES", strategy="t")
    sig2 = Signal(ts=pd.Timestamp("2024-01-03 09:00", tz="UTC"), direction=LONG, entry=4800.0, stop=4790.0,
                  entry_type="market", symbol="ES", strategy="t")
    result = engine.run(bars, [sig1, sig2], NoOpExit(), fixed_contracts(1), strategy="t")
    assert len(result.trades) == 2  # different CME trading days -> both attempts allowed
    assert result.skipped == []


# --------------------------------------------------------------------------
# risk_based sizing: skip (not force) a signal too wide to size at 1 contract
# --------------------------------------------------------------------------


def test_risk_based_sizing_skips_when_too_wide_sizes_normally_otherwise() -> None:
    engine = _engine()
    sizing = risk_based(risk_dollars=400.0)  # ES point_value = 50

    bars_wide = _bars([
        ("09:00", 4800, 4801, 4799, 4800, 500),
        ("09:01", 4800, 4801, 4799, 4800, 500),
        ("09:02", 4800, 4801, 4799, 4800, 500),
    ])
    # risk_per_unit 10 pts -> $500/contract > $400 budget -> floor(400/500) = 0
    sig_wide = _sig("09:00", LONG, 4800.0, 4790.0, entry_type="market")
    result_wide = engine.run(bars_wide, [sig_wide], NoOpExit(), sizing, strategy="t")
    assert result_wide.trades == []
    assert len(result_wide.skipped) == 1
    assert result_wide.skipped[0]["reason"] == "sizing_zero_qty"

    # risk_per_unit 5 pts -> $250/contract <= $400 budget -> floor(400/250) = 1
    sig_ok = _sig("09:00", LONG, 4800.0, 4795.0, entry_type="market")
    result_ok = engine.run(bars_wide, [sig_ok], NoOpExit(), sizing, strategy="t")
    assert len(result_ok.trades) == 1
    assert result_ok.trades[0].qty == pytest.approx(1.0)
    assert result_ok.skipped == []
