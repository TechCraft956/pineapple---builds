"""Tests for lab.backtest.exits: each policy exercised directly against a
PositionState/bar built for it, plus CompositeExit's documented conflict
resolution (protective-side always wins, then list order, then stop
mutations are never dropped)."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.backtest.exits import (
    AtrTrail,
    BreakevenAfterR,
    CompositeExit,
    ExitContext,
    ExitDecision,
    FixedR,
    MultiTargetR,
    OpposingLevel,
    PositionState,
    SessionEnd,
    TimeStop,
)
from lab.core.instruments import get_instrument
from lab.core.sessions import NY_RTH, window_bounds
from lab.core.types import LONG, SHORT, ExitReason, Signal

_INST = get_instrument("ES")


def _bar(ts: pd.Timestamp, o: float, h: float, l: float, c: float, v: float = 500.0) -> pd.Series:
    return pd.Series({"open": o, "high": h, "low": l, "close": c, "volume": v}, name=ts)


def _signal(direction: int, entry: float = 4800.0, stop: float | None = None) -> Signal:
    if stop is None:
        stop = 4790.0 if direction == LONG else 4810.0
    return Signal(
        ts=pd.Timestamp("2024-01-02 15:00", tz="UTC"),
        direction=direction, entry=entry, stop=stop, symbol="ES", strategy="t",
    )


def _empty_ctx(now: pd.Timestamp) -> ExitContext:
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty.index = pd.DatetimeIndex([], tz="UTC", name="ts")
    return ExitContext(instrument=_INST, bars=empty, now=now)


def _position(
    direction: int,
    *,
    entry_ts: pd.Timestamp,
    entry_price: float = 4800.0,
    stop: float = 4790.0,
    initial_risk_per_unit: float = 10.0,
    high_water: float | None = None,
    low_water: float | None = None,
) -> PositionState:
    return PositionState(
        symbol="ES", direction=direction, entry_ts=entry_ts, entry_price=entry_price,
        initial_qty=1.0, remaining_qty=1.0, stop=stop, initial_risk_per_unit=initial_risk_per_unit,
        high_water=entry_price if high_water is None else high_water,
        low_water=entry_price if low_water is None else low_water,
    )


def _ctx(bars: pd.DataFrame, now: pd.Timestamp) -> ExitContext:
    return ExitContext(instrument=_INST, bars=bars.loc[bars.index <= now], now=now)


# --------------------------------------------------------------------------
# Target-setting policies
# --------------------------------------------------------------------------


def test_fixed_r_sets_single_target_at_r_multiple() -> None:
    sig = _signal(LONG, entry=4800.0, stop=4790.0)  # risk_per_unit = 10
    targets, weights = FixedR(1.5).initial_targets(sig, _empty_ctx(sig.ts))
    assert targets == (4815.0,)  # 4800 + 1.5*10
    assert weights == (1.0,)


def test_multi_target_r_validates_and_computes_ladder() -> None:
    sig = _signal(SHORT, entry=4800.0, stop=4810.0)  # risk_per_unit = 10
    ladder = MultiTargetR(rs=(1.0, 2.0), weights=(0.5, 0.5))
    targets, weights = ladder.initial_targets(sig, _empty_ctx(sig.ts))
    assert targets == (4790.0, 4780.0)
    assert weights == (0.5, 0.5)

    with pytest.raises(ValueError):
        MultiTargetR(rs=(1.0, 2.0), weights=(0.5, 0.6))  # doesn't sum to 1.0
    with pytest.raises(ValueError):
        MultiTargetR(rs=(), weights=())  # needs at least one target


# --------------------------------------------------------------------------
# TimeStop
# --------------------------------------------------------------------------


def test_time_stop_fires_exactly_at_elapsed_minutes_not_before() -> None:
    entry_ts = pd.Timestamp("2024-01-02 15:00", tz="UTC")
    pos = _position(LONG, entry_ts=entry_ts)
    policy = TimeStop(minutes=30)

    before = entry_ts + pd.Timedelta(minutes=29)
    bar_before = _bar(before, 4801, 4802, 4800, 4801)
    bars = pd.DataFrame([bar_before])
    assert policy.check(_signal(LONG), pos, bar_before, _ctx(bars, before)) is None

    at_deadline = entry_ts + pd.Timedelta(minutes=30)
    bar_at = _bar(at_deadline, 4803, 4804, 4802, 4803.5)
    decision = policy.check(_signal(LONG), pos, bar_at, _ctx(bars, at_deadline))
    assert decision is not None
    assert decision.reason == ExitReason.TIME_STOP
    assert decision.price == pytest.approx(4803.5)  # the bar's close
    assert decision.qty is None  # close everything remaining


# --------------------------------------------------------------------------
# SessionEnd
# --------------------------------------------------------------------------


def test_session_end_flattens_at_window_end_of_the_entry_trading_day() -> None:
    day = pd.Timestamp("2024-01-02").date()
    _, rth_end = window_bounds(NY_RTH, day)  # 15:00 CT that day, in UTC
    entry_ts = rth_end - pd.Timedelta(hours=2)
    pos = _position(LONG, entry_ts=entry_ts)
    policy = SessionEnd(NY_RTH)

    before_close = rth_end - pd.Timedelta(minutes=1)
    bar_before = _bar(before_close, 4801, 4802, 4800, 4801)
    assert policy.check(_signal(LONG), pos, bar_before, _ctx(pd.DataFrame([bar_before]), before_close)) is None

    at_close = rth_end
    bar_at = _bar(at_close, 4802, 4803, 4801, 4802.25)
    decision = policy.check(_signal(LONG), pos, bar_at, _ctx(pd.DataFrame([bar_at]), at_close))
    assert decision is not None
    assert decision.reason == ExitReason.SESSION_END
    assert decision.price == pytest.approx(4802.25)


# --------------------------------------------------------------------------
# BreakevenAfterR
# --------------------------------------------------------------------------


def test_breakeven_after_r_moves_stop_to_entry_once_reached() -> None:
    entry_ts = pd.Timestamp("2024-01-02 15:00", tz="UTC")
    # entry 4800, stop 4790 -> risk 10; need +10 favourable excursion for 1R
    pos = _position(LONG, entry_ts=entry_ts, entry_price=4800.0, stop=4790.0, high_water=4802.0)
    policy = BreakevenAfterR(r=1.0)
    bar = _bar(entry_ts + pd.Timedelta(minutes=5), 4801, 4802, 4800, 4801.5)
    ctx = _ctx(pd.DataFrame([bar]), bar.name)

    # not yet at 1R (favourable excursion 2 of 10 needed)
    assert policy.check(_signal(LONG), pos, bar, ctx) is None

    pos.high_water = 4810.0  # exactly 1R favourable excursion
    decision = policy.check(_signal(LONG), pos, bar, ctx)
    assert decision is not None
    assert decision.new_stop == pytest.approx(4800.0)
    assert decision.is_exit is False  # a stop mutation only, not a close


def test_breakeven_after_r_never_loosens_an_already_better_stop() -> None:
    entry_ts = pd.Timestamp("2024-01-02 15:00", tz="UTC")
    # stop already at 4801, better than breakeven (4800) -- must be a no-op
    pos = _position(LONG, entry_ts=entry_ts, entry_price=4800.0, stop=4801.0, high_water=4815.0)
    policy = BreakevenAfterR(r=1.0)
    bar = _bar(entry_ts + pd.Timedelta(minutes=5), 4810, 4815, 4809, 4812)
    assert policy.check(_signal(LONG), pos, bar, _ctx(pd.DataFrame([bar]), bar.name)) is None


# --------------------------------------------------------------------------
# AtrTrail
# --------------------------------------------------------------------------


def test_atr_trail_computes_atr_by_hand_and_only_tightens() -> None:
    idx = pd.date_range("2024-01-02 15:00", periods=4, freq="1min", tz="UTC")
    bars = pd.DataFrame(
        {
            "open":  [100.0, 100.0, 101.0, 102.0],
            "high":  [101.0, 102.0, 103.0, 105.0],
            "low":   [99.0,  99.0,  100.0, 101.0],
            "close": [100.0, 101.0, 102.0, 104.0],
            "volume": [500.0] * 4,
        },
        index=idx,
    )
    # true range per bar (high-low / |high-prevclose| / |low-prevclose|, max):
    # bar0 has no prev close, so only high-low is defined: 101-99 = 2
    # bar1: max(102-99=3, |102-100|=2, |99-100|=1)  = 3
    # bar2: max(103-100=3, |103-101|=2, |100-101|=1) = 3
    # bar3: max(105-101=4, |105-102|=3, |101-102|=1) = 4
    # ATR (period=3 -> a period+1=4 bar window, simple mean) = (2+3+3+4)/4 = 3.0
    entry_ts = idx[0]
    pos = _position(LONG, entry_ts=entry_ts, entry_price=100.0, stop=95.0, high_water=105.0)
    policy = AtrTrail(mult=2.0, period=3)
    ctx = _ctx(bars, idx[-1])

    decision = policy.check(_signal(LONG), pos, bars.iloc[-1], ctx)
    assert decision is not None
    expected_atr = 3.0
    assert decision.meta["atr"] == pytest.approx(expected_atr)
    expected_stop = 105.0 - 2.0 * expected_atr  # 99.0
    assert decision.new_stop == pytest.approx(expected_stop)
    assert decision.is_exit is False

    # a candidate that would *loosen* the stop must be rejected
    pos_tight = _position(LONG, entry_ts=entry_ts, entry_price=100.0, stop=99.5, high_water=105.0)
    decision2 = policy.check(_signal(LONG), pos_tight, bars.iloc[-1], ctx)
    assert decision2 is None  # candidate (99.0) is looser than the current stop (99.5)


# --------------------------------------------------------------------------
# OpposingLevel
# --------------------------------------------------------------------------


def test_opposing_level_fills_at_level_or_at_open_on_favourable_gap() -> None:
    level = 4790.0
    policy = OpposingLevel(level_fn=lambda signal, ctx: level)
    entry_ts = pd.Timestamp("2024-01-02 15:00", tz="UTC")
    pos = _position(SHORT, entry_ts=entry_ts, entry_price=4800.0, stop=4810.0)

    # ordinary touch: open above the level, low reaches it intrabar -> fill AT the level
    ts1 = entry_ts + pd.Timedelta(minutes=1)
    bar_touch = _bar(ts1, 4799.2, 4800.0, 4788.5, 4791.0)
    decision = policy.check(_signal(SHORT), pos, bar_touch, _ctx(pd.DataFrame([bar_touch]), ts1))
    assert decision is not None
    assert decision.reason == ExitReason.OPPOSING_LEVEL
    assert decision.price == pytest.approx(4790.0)  # exactly the level, no slippage

    # favourable gap: open already through the level -> fill at the open (better)
    ts2 = entry_ts + pd.Timedelta(minutes=2)
    bar_gap = _bar(ts2, 4785.0, 4786.0, 4783.0, 4784.0)
    decision2 = policy.check(_signal(SHORT), pos, bar_gap, _ctx(pd.DataFrame([bar_gap]), ts2))
    assert decision2 is not None
    assert decision2.price == pytest.approx(4785.0)  # the open, not the level

    # no touch at all -> None
    ts3 = entry_ts + pd.Timedelta(minutes=3)
    bar_none = _bar(ts3, 4800.0, 4801.0, 4795.0, 4799.0)
    assert policy.check(_signal(SHORT), pos, bar_none, _ctx(pd.DataFrame([bar_none]), ts3)) is None


# --------------------------------------------------------------------------
# CompositeExit
# --------------------------------------------------------------------------


class _FixedDecision:
    """Test double: a policy that always returns the same canned decision."""

    def __init__(self, decision: ExitDecision | None) -> None:
        self._decision = decision

    def initial_targets(self, signal, ctx):
        return (), None

    def check(self, signal, position, bar, ctx):
        return self._decision


def test_composite_exit_protective_side_always_wins_regardless_of_list_order() -> None:
    stop_side = _FixedDecision(ExitDecision(reason=ExitReason.STOP, qty=None, price=4790.0))
    profit_side = _FixedDecision(ExitDecision(reason=ExitReason.TARGET, qty=None, price=4830.0))
    bar = _bar(pd.Timestamp("2024-01-02 15:00", tz="UTC"), 4800, 4831, 4789, 4800)
    ctx = _ctx(pd.DataFrame([bar]), bar.name)
    pos = _position(LONG, entry_ts=bar.name)

    winner_a = CompositeExit([profit_side, stop_side]).check(_signal(LONG), pos, bar, ctx)
    winner_b = CompositeExit([stop_side, profit_side]).check(_signal(LONG), pos, bar, ctx)
    for winner in (winner_a, winner_b):
        assert winner is not None
        assert winner.reason == ExitReason.STOP
        assert winner.price == pytest.approx(4790.0)


def test_composite_exit_list_order_breaks_ties_among_non_stop_exits() -> None:
    first = _FixedDecision(ExitDecision(reason=ExitReason.TIME_STOP, qty=None, price=4801.0))
    second = _FixedDecision(ExitDecision(reason=ExitReason.SESSION_END, qty=None, price=4802.0))
    bar = _bar(pd.Timestamp("2024-01-02 15:00", tz="UTC"), 4800, 4805, 4799, 4801)
    ctx = _ctx(pd.DataFrame([bar]), bar.name)
    pos = _position(LONG, entry_ts=bar.name)

    winner_ab = CompositeExit([first, second]).check(_signal(LONG), pos, bar, ctx)
    assert winner_ab is not None and winner_ab.reason == ExitReason.TIME_STOP

    winner_ba = CompositeExit([second, first]).check(_signal(LONG), pos, bar, ctx)
    assert winner_ba is not None and winner_ba.reason == ExitReason.SESSION_END


def test_composite_exit_keeps_stop_tightening_even_when_another_policy_exits() -> None:
    trail = _FixedDecision(ExitDecision(new_stop=4795.0, meta={"trigger": "atr_trail"}))
    profit_side = _FixedDecision(ExitDecision(reason=ExitReason.TARGET, qty=None, price=4830.0))
    bar = _bar(pd.Timestamp("2024-01-02 15:00", tz="UTC"), 4800, 4831, 4794, 4800)
    ctx = _ctx(pd.DataFrame([bar]), bar.name)
    pos = _position(LONG, entry_ts=bar.name, stop=4790.0)

    winner = CompositeExit([profit_side, trail]).check(_signal(LONG), pos, bar, ctx)
    assert winner is not None
    assert winner.reason == ExitReason.TARGET  # the exit still wins
    assert winner.new_stop == pytest.approx(4795.0)  # but the tighter stop rides along

    # a pure stop-mutation with no exit anywhere returns a mutation-only decision
    winner2 = CompositeExit([trail]).check(_signal(LONG), pos, bar, ctx)
    assert winner2 is not None
    assert winner2.is_exit is False
    assert winner2.new_stop == pytest.approx(4795.0)
