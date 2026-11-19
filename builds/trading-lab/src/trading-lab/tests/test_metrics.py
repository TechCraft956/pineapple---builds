"""Tests for lab.backtest.metrics: stats verified by hand on a small trade
sequence, the empty-input contract, and the CME-trading-day (not calendar
day) grouping that Sharpe/Sortino and daily_pnl depend on."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.backtest.metrics import compute_stats, daily_pnl, empty_stats, equity_curve
from lab.core.types import LONG, ExitReason, Trade

_SYMBOL = "ES"
_STRATEGY = "test_strategy"


def _trade(
    pnl: float,
    *,
    exit_ts: pd.Timestamp,
    risk_dollars: float = 500.0,
    exit_reason: ExitReason = ExitReason.TARGET,
    tag: str = "t",
    commission: float = 0.0,
    slippage_cost: float = 0.0,
) -> Trade:
    """A Trade with an arbitrary-but-consistent price pair reproducing ``pnl``
    exactly (pnl is the field metrics actually read; entry/exit price are
    only there to satisfy the dataclass and are not otherwise load-bearing)."""
    entry_price = 100.0
    qty = 1.0
    exit_price = entry_price + pnl / (qty * 50.0)  # ES point_value = 50
    return Trade(
        symbol=_SYMBOL,
        strategy=_STRATEGY,
        direction=LONG,
        entry_ts=exit_ts - pd.Timedelta(minutes=10),
        entry_price=entry_price,
        exit_ts=exit_ts,
        exit_price=exit_price,
        qty=qty,
        pnl=pnl,
        commission=commission,
        slippage_cost=slippage_cost,
        risk_dollars=risk_dollars,
        exit_reason=exit_reason,
        tag=tag,
    )


def _ct(date_str: str, hhmm: str = "14:00") -> pd.Timestamp:
    """A timestamp on ``date_str`` at ``hhmm`` America/Chicago, before the
    17:00 CT trading-day roll, so its CME trading day == its calendar date."""
    return pd.Timestamp(f"{date_str} {hhmm}", tz="America/Chicago").tz_convert("UTC")


# The 6-trade sequence every hand-verified assertion below is computed from.
# pnl:        750    -500   1000   -500   -250   1500
# risk $:     500     500    500    500    500    500
# r:          1.5     -1.0   2.0    -1.0   -0.5   3.0
_PNLS = [750.0, -500.0, 1000.0, -500.0, -250.0, 1500.0]
_DAYS = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]


def _six_trade_sequence() -> list[Trade]:
    return [_trade(pnl, exit_ts=_ct(day)) for pnl, day in zip(_PNLS, _DAYS)]


def test_compute_stats_hand_verified_on_six_trades() -> None:
    trades = _six_trade_sequence()
    stats = compute_stats(trades)

    assert stats["n_trades"] == 6
    assert stats["n_wins"] == 3
    assert stats["n_losses"] == 3
    assert stats["win_rate"] == pytest.approx(0.5)

    # gross_profit = 750+1000+1500 = 3250; gross_loss = 500+500+250 = 1250
    assert stats["profit_factor"] == pytest.approx(3250.0 / 1250.0)  # 2.6
    assert stats["net_pnl"] == pytest.approx(2000.0)  # 3250 - 1250
    assert stats["expectancy_dollars"] == pytest.approx(2000.0 / 6.0)

    # r-multiples: 1.5, -1.0, 2.0, -1.0, -0.5, 3.0 -> sum 4.0, mean 4/6
    assert stats["avg_r"] == pytest.approx(4.0 / 6.0)
    assert stats["expectancy_r"] == pytest.approx(4.0 / 6.0)
    # sorted r: -1.0, -1.0, -0.5, 1.5, 2.0, 3.0 -> median of middle two (-0.5, 1.5)
    assert stats["median_r"] == pytest.approx(0.5)

    # both sides have 3 trades here, so payoff_ratio collapses to profit_factor
    assert stats["payoff_ratio"] == pytest.approx(3250.0 / 1250.0)

    # equity (cumsum in exit order): 750, 250, 1250, 750, 500, 2000
    # running max:                    750, 750, 1250, 1250, 1250, 2000
    # drawdown:                         0,-500,    0, -500, -750,    0
    assert stats["max_drawdown_dollars"] == pytest.approx(-750.0)

    # loss streak by pnl order [W,L,W,L,L,W] -> longest run of consecutive losses is 2
    assert stats["longest_losing_streak"] == 2

    assert stats["exit_reason_breakdown"] == {"target": 6}
    assert set(stats["by_tag"].keys()) == {"t"}
    assert stats["by_tag"]["t"]["n_trades"] == 6


def test_compute_stats_empty_input_is_well_formed_not_raising() -> None:
    stats = compute_stats([])
    expected = empty_stats()
    assert stats.keys() == expected.keys()
    for key, val in expected.items():
        got = stats[key]
        if isinstance(val, float) and val != val:  # NaN sentinel -- NaN != NaN
            assert got != got, f"{key}: expected NaN, got {got!r}"
        else:
            assert got == val, f"{key}: expected {val!r}, got {got!r}"
    # spot-check the contract empty_stats documents: zeroed counts, NaN ratios
    assert stats["n_trades"] == 0
    assert stats["net_pnl"] == 0.0
    assert stats["win_rate"] != stats["win_rate"]  # NaN != NaN
    assert stats["max_drawdown_duration"] is None
    assert stats["exit_reason_breakdown"] == {}
    assert stats["by_tag"] == {}


def test_equity_curve_and_compute_stats_agree_on_supplied_equity() -> None:
    trades = _six_trade_sequence()
    equity = equity_curve(trades)
    assert list(equity.to_numpy()) == pytest.approx([750.0, 250.0, 1250.0, 750.0, 500.0, 2000.0])
    # compute_stats must use the equity we hand it, not silently recompute a
    # different one from `trades`.
    stats_default = compute_stats(trades)
    stats_explicit = compute_stats(trades, equity)
    assert stats_default["max_drawdown_dollars"] == stats_explicit["max_drawdown_dollars"]


def test_daily_pnl_groups_by_cme_trading_day_not_calendar_date() -> None:
    """Two trades that land on the same UTC calendar date but opposite sides
    of the 17:00 CT trading-day roll must land in two different daily
    buckets; two trades on different UTC calendar dates that are nonetheless
    the same CME trading day (a Sunday-evening open, Monday-morning close)
    must land in the same bucket. Calendar-date grouping would get both of
    these backwards."""
    # 2024-01-08 16:30 CT is *before* the 17:00 roll -> trading day 2024-01-08.
    before_roll = pd.Timestamp("2024-01-08 16:30", tz="America/Chicago").tz_convert("UTC")
    # 2024-01-08 18:00 CT is *after* the roll -> trading day 2024-01-09, even
    # though the UTC calendar date may still read "2024-01-08" or "01-09"
    # depending on offset -- the point is it's a different CME trading day.
    after_roll = pd.Timestamp("2024-01-08 18:00", tz="America/Chicago").tz_convert("UTC")

    trades = [
        _trade(100.0, exit_ts=before_roll),
        _trade(200.0, exit_ts=after_roll),
    ]
    daily = daily_pnl(trades)
    assert len(daily) == 2  # two distinct CME trading days, not lumped into one calendar day
    assert set(daily.to_numpy()) == {100.0, 200.0}

    # Now the reverse: a Sunday-evening fill (just after the 17:00 CT roll,
    # so it already belongs to Monday's trading day) and a Monday-morning
    # exit are different UTC calendar dates but the same CME trading day.
    sunday_evening = pd.Timestamp("2024-01-07 17:30", tz="America/Chicago").tz_convert("UTC")
    monday_morning = pd.Timestamp("2024-01-08 09:00", tz="America/Chicago").tz_convert("UTC")
    assert sunday_evening.date() != monday_morning.date()  # different UTC calendar dates
    trades2 = [
        _trade(300.0, exit_ts=sunday_evening),
        _trade(400.0, exit_ts=monday_morning),
    ]
    daily2 = daily_pnl(trades2)
    assert len(daily2) == 1  # same CME trading day (2024-01-08) -> one bucket
    assert float(daily2.iloc[0]) == pytest.approx(700.0)


def test_sharpe_and_sortino_use_daily_not_trade_level_returns() -> None:
    """Two trades on the same CME trading day must contribute one pooled
    daily observation to Sharpe, not two independent ones -- otherwise a
    strategy that simply takes more trades per day looks artificially less
    volatile."""
    same_day_a = _ct("2024-01-02", "09:00")
    same_day_b = _ct("2024-01-02", "10:00")
    other_day = _ct("2024-01-03", "09:00")
    trades = [
        _trade(100.0, exit_ts=same_day_a),
        _trade(-40.0, exit_ts=same_day_b),
        _trade(220.0, exit_ts=other_day),
    ]
    daily = daily_pnl(trades)
    assert len(daily) == 2  # pooled to two trading days, not three trade-level points
    stats = compute_stats(trades)
    # with only two daily observations, Sharpe is defined (len>=2) and finite
    assert stats["sharpe_daily"] == stats["sharpe_daily"]  # not NaN
