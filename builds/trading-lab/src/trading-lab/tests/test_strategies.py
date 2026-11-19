"""Tests for the concrete strategies: each fires exactly once on a frame
built for its textbook setup, and does not fire when one precondition is
removed. Every bar frame below is constructed so the exact trigger bar is
known in advance -- assertions check the resulting Signal's prices and meta
against values computed directly from the bars we chose, not against
independently-guessed numbers (in particular, ATR-dependent thresholds are
always given a wide enough margin that the exact ATR value cannot matter)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.core.instruments import get_instrument
from lab.core.sessions import ASIA, CL_RTH, LONDON, window_bounds
from lab.core.types import LONG, SHORT
from lab.strategies.base import build_session_context
from lab.strategies.cl_opening_range import ClOpeningRange, ClOpeningRangeParams
from lab.strategies.es_london_sweep import EsLondonSweep, EsLondonSweepParams

_ES = get_instrument("ES")
_CL = get_instrument("CL")


# ==========================================================================
# ES London Sweep
# ==========================================================================

_ES_DAY = pd.Timestamp("2024-01-09").date()  # an ordinary Tuesday


def _es_frame(
    *,
    sweep_high: float = 4804.0,
    do_reclaim: bool = True,
    do_displace: bool = True,
    add_long_setup: bool = False,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """One CME trading day of 5-minute ES bars: a flat Asia session (high
    4802 / low 4790) followed by a flat London session, with a short
    asia-high-sweep setup carved in at London bars 20/21/22 (sweep / reclaim
    / displacement), optionally also a symmetric long asia-low-sweep setup
    at London bars 35/36/37."""
    a_start, a_end = window_bounds(ASIA, _ES_DAY)
    l_start, l_end = window_bounds(LONDON, _ES_DAY)
    idx = pd.date_range(a_start, l_end, freq="5min", tz="UTC", inclusive="left")
    n = len(idx)
    bars = pd.DataFrame(
        {"open": 4796.0, "high": 4797.0, "low": 4795.0, "close": 4796.0, "volume": 500.0},
        index=idx,
    )
    col = bars.columns.get_loc

    asia_idx = np.where((idx >= a_start) & (idx < a_end))[0]
    bars.iloc[asia_idx[5], col("high")] = 4802.0  # asia_high
    bars.iloc[asia_idx[10], col("low")] = 4790.0  # asia_low

    london_idx = np.where((idx >= l_start) & (idx < l_end))[0]
    for j in london_idx:
        bars.iloc[j, [col("open"), col("high"), col("low"), col("close")]] = [4800.5, 4801.0, 4800.0, 4800.5]

    sweep_pos, reclaim_pos = 20, 21
    sweep_i, reclaim_i = london_idx[sweep_pos], london_idx[reclaim_pos]
    disp_i = london_idx[sweep_pos + 2]

    bars.iloc[sweep_i, [col("open"), col("high"), col("low"), col("close")]] = [4801.0, sweep_high, 4800.0, 4802.5]

    if do_reclaim:
        bars.iloc[reclaim_i, [col("open"), col("high"), col("low"), col("close")]] = [4802.0, 4802.5, 4800.5, 4801.0]
        if do_displace:
            # displaced_close (4790.0) is 10+ points below prior_swing (4800.0);
            # far beyond any plausible 0.5*ATR threshold given ~1pt bar ranges.
            bars.iloc[disp_i, [col("open"), col("high"), col("low"), col("close")]] = [4801.0, 4801.5, 4789.5, 4790.0]
        else:
            for k in range(reclaim_pos, sweep_pos + 1 + 6):
                ii = london_idx[k]
                bars.iloc[ii, [col("open"), col("high"), col("low"), col("close")]] = [4801.5, 4802.0, 4801.0, 4801.5]
    else:
        for k in range(sweep_pos + 1, sweep_pos + 1 + 6):
            ii = london_idx[k]
            bars.iloc[ii, [col("open"), col("high"), col("low"), col("close")]] = [4803.0, 4804.0, 4802.5, 4803.0]

    if add_long_setup:
        si, ri, di = london_idx[35], london_idx[36], london_idx[37]
        bars.iloc[si, [col("open"), col("high"), col("low"), col("close")]] = [4800.0, 4801.0, 4788.5, 4798.0]
        bars.iloc[ri, [col("open"), col("high"), col("low"), col("close")]] = [4798.0, 4799.0, 4790.5, 4791.0]
        bars.iloc[di, [col("open"), col("high"), col("low"), col("close")]] = [4791.0, 4812.5, 4790.5, 4812.0]

    return bars, idx


def _es_ctx(bars, news_windows=()):
    return build_session_context(_ES_DAY, bars, "ES", _ES, news_windows=news_windows)


def test_es_london_sweep_short_fires_once_on_textbook_setup() -> None:
    bars, idx = _es_frame()
    ctx = _es_ctx(bars)
    strat = EsLondonSweep(EsLondonSweepParams(), _ES)
    sigs = strat.generate(_ES_DAY, bars, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == SHORT
    assert sig.tag == "asia_high_sweep"
    assert sig.symbol == "ES"
    assert sig.meta["sweep_extreme"] == pytest.approx(4804.0)
    assert sig.meta["prior_swing"] == pytest.approx(4800.0)
    assert sig.meta["displacement_close"] == pytest.approx(4790.0)

    # entry = displaced_close + retrace_pct * (sweep_extreme - displaced_close)
    expected_entry = 4790.0 + 0.5 * (4804.0 - 4790.0)  # 4797.0
    assert sig.entry == pytest.approx(expected_entry)
    # stop = sweep_extreme + stop_buffer_ticks * tick_size
    expected_stop = 4804.0 + 3 * 0.25  # 4804.75
    assert sig.stop == pytest.approx(expected_stop)
    assert sig.entry_type == "limit"


def _es_long_only_frame() -> pd.DataFrame:
    """A standalone symmetric mirror of ``_es_frame``'s short setup: only an
    asia-low-sweep long setup is carved in, nothing at the short setup's
    London bars, so the short-side lookback windows can't be contaminated
    by leftover short-setup bars."""
    a_start, a_end = window_bounds(ASIA, _ES_DAY)
    l_start, l_end = window_bounds(LONDON, _ES_DAY)
    idx = pd.date_range(a_start, l_end, freq="5min", tz="UTC", inclusive="left")
    bars = pd.DataFrame(
        {"open": 4796.0, "high": 4797.0, "low": 4795.0, "close": 4796.0, "volume": 500.0},
        index=idx,
    )
    col = bars.columns.get_loc
    asia_idx = np.where((idx >= a_start) & (idx < a_end))[0]
    bars.iloc[asia_idx[5], col("high")] = 4802.0
    bars.iloc[asia_idx[10], col("low")] = 4790.0
    london_idx = np.where((idx >= l_start) & (idx < l_end))[0]
    for j in london_idx:
        bars.iloc[j, [col("open"), col("high"), col("low"), col("close")]] = [4800.5, 4801.0, 4800.0, 4800.5]
    si, ri, di = london_idx[20], london_idx[21], london_idx[22]
    bars.iloc[si, [col("open"), col("high"), col("low"), col("close")]] = [4800.0, 4801.0, 4788.5, 4798.0]
    bars.iloc[ri, [col("open"), col("high"), col("low"), col("close")]] = [4798.0, 4799.0, 4790.5, 4791.0]
    bars.iloc[di, [col("open"), col("high"), col("low"), col("close")]] = [4791.0, 4812.5, 4790.5, 4812.0]
    return bars


def test_es_london_sweep_long_fires_once_symmetric() -> None:
    bars2 = _es_long_only_frame()
    ctx = _es_ctx(bars2)
    strat = EsLondonSweep(EsLondonSweepParams(), _ES)
    sigs = strat.generate(_ES_DAY, bars2, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == LONG
    assert sig.tag == "asia_low_sweep"
    assert sig.meta["sweep_extreme"] == pytest.approx(4788.5)
    assert sig.meta["prior_swing"] == pytest.approx(4801.0)
    assert sig.meta["displacement_close"] == pytest.approx(4812.0)
    expected_entry = 4812.0 + 0.5 * (4788.5 - 4812.0)
    assert sig.entry == pytest.approx(expected_entry)
    expected_stop = 4788.5 - 3 * 0.25
    assert sig.stop == pytest.approx(expected_stop)


def test_es_london_sweep_no_signal_when_sweep_too_shallow() -> None:
    bars, _ = _es_frame(sweep_high=4802.5)  # only 0.5 ticks beyond asia_high; need >= 4
    ctx = _es_ctx(bars)
    sigs = EsLondonSweep(EsLondonSweepParams(), _ES).generate(_ES_DAY, bars, ctx)
    assert sigs == []


def test_es_london_sweep_no_signal_when_no_reclaim() -> None:
    bars, _ = _es_frame(do_reclaim=False)
    ctx = _es_ctx(bars)
    sigs = EsLondonSweep(EsLondonSweepParams(), _ES).generate(_ES_DAY, bars, ctx)
    assert sigs == []


def test_es_london_sweep_no_signal_when_no_displacement() -> None:
    bars, _ = _es_frame(do_displace=False)
    ctx = _es_ctx(bars)
    sigs = EsLondonSweep(EsLondonSweepParams(), _ES).generate(_ES_DAY, bars, ctx)
    assert sigs == []


def test_es_london_sweep_no_signal_inside_news_block() -> None:
    bars, idx = _es_frame()
    l_start, l_end = window_bounds(LONDON, _ES_DAY)
    london_idx = np.where((idx >= l_start) & (idx < l_end))[0]
    disp_ts = idx[london_idx[22]]
    news = [(disp_ts - pd.Timedelta(minutes=1), disp_ts + pd.Timedelta(minutes=1))]
    ctx = _es_ctx(bars, news_windows=news)
    sigs = EsLondonSweep(EsLondonSweepParams(), _ES).generate(_ES_DAY, bars, ctx)
    assert sigs == []


def test_es_london_sweep_max_attempts_per_day_caps_both_directions() -> None:
    bars, _ = _es_frame(add_long_setup=True)  # both short and long setups complete
    ctx = _es_ctx(bars)

    sigs_default = EsLondonSweep(EsLondonSweepParams(), _ES).generate(_ES_DAY, bars, ctx)
    assert len(sigs_default) == 1  # default max_attempts_per_day = 1
    assert sigs_default[0].direction == SHORT  # the earlier (short) setup wins

    sigs_two = EsLondonSweep(EsLondonSweepParams(max_attempts_per_day=2), _ES).generate(_ES_DAY, bars, ctx)
    assert len(sigs_two) == 2
    assert {s.direction for s in sigs_two} == {LONG, SHORT}
    assert sigs_two[0].ts < sigs_two[1].ts  # chronological


# ==========================================================================
# CL Opening Range
# ==========================================================================

_CL_DAY = pd.Timestamp("2024-03-05").date()
_CL_START, _CL_END = window_bounds(CL_RTH, _CL_DAY)
_CL_PRIOR_DAY = pd.Timestamp("2024-03-04").date()
_CL_PRIOR_START, _CL_PRIOR_END = window_bounds(CL_RTH, _CL_PRIOR_DAY)


def _cl_base_bars() -> pd.DataFrame:
    """One RTH session of 1-minute CL bars. The first 15 rows (the OR window
    for or_minutes=15) set OR high=80.02 / low=79.98; every bar after that
    defaults strictly *inside* that range (80.01/79.99) so nothing triggers
    a breakout unless a test explicitly carves one in."""
    idx = pd.date_range(_CL_START, _CL_END, freq="1min", tz="UTC", inclusive="left")
    n = len(idx)
    high = np.full(n, 80.01)
    low = np.full(n, 79.99)
    high[:15] = 80.02
    low[:15] = 79.98
    return pd.DataFrame(
        {"open": 80.00, "high": high, "low": low, "close": 80.00, "volume": 500.0}, index=idx
    )


def _cl_prior_day_bars(volume: float = 300.0) -> pd.DataFrame:
    """A quiet prior trading day, same shape, used only to give
    ``same_time_of_day_volume`` a median to compare against."""
    idx = pd.date_range(_CL_PRIOR_START, _CL_PRIOR_END, freq="1min", tz="UTC", inclusive="left")
    n = len(idx)
    return pd.DataFrame(
        {"open": 80.00, "high": 80.01, "low": 79.99, "close": 80.00, "volume": volume}, index=idx
    )


def _cl_ctx(bars, news_windows=(), with_prior_day=False):
    full = pd.concat([_cl_prior_day_bars(), bars]) if with_prior_day else bars
    return build_session_context(_CL_DAY, full, "CL", _CL, news_windows=news_windows)


# --- breakout --------------------------------------------------------------


def test_cl_breakout_long_fires_once_on_trade_through() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10  # trades through OR high (80.02)
    ctx = _cl_ctx(bars)
    strat = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL)
    sigs = strat.generate(_CL_DAY, bars, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == LONG
    assert sig.entry_type == "stop"
    assert sig.entry == pytest.approx(80.02)
    assert sig.stop == pytest.approx(79.98)  # opposite_edge default
    assert sig.meta["or_width"] == pytest.approx(0.04)
    assert sig.meta["variant"] == "breakout"


def test_cl_breakout_short_fires_once_symmetric() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("low")] = 79.90
    ctx = _cl_ctx(bars)
    strat = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL)
    sigs = strat.generate(_CL_DAY, bars, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == SHORT
    assert sig.entry == pytest.approx(79.98)
    assert sig.stop == pytest.approx(80.02)


def test_cl_breakout_no_signal_when_no_trade_through() -> None:
    bars = _cl_base_bars()
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


def test_cl_breakout_stop_mode_buffer_uses_ticks_beyond_entry() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    ctx = _cl_ctx(bars)
    params = ClOpeningRangeParams(or_minutes=15, variant="breakout", stop_mode="buffer", stop_buffer_ticks=10)
    sigs = ClOpeningRange(params, _CL).generate(_CL_DAY, bars, ctx)
    assert len(sigs) == 1
    # stop = entry - stop_buffer_ticks * tick_size = 80.02 - 10*0.01
    assert sigs[0].stop == pytest.approx(80.02 - 0.10)


def test_cl_breakout_max_attempts_per_day_caps_both_directions() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10  # long trigger, earlier
    bars.iloc[20, bars.columns.get_loc("low")] = 79.90  # short trigger, later
    ctx = _cl_ctx(bars)

    sigs_default = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert len(sigs_default) == 1
    assert sigs_default[0].direction == LONG  # earlier trigger wins

    sigs_two = ClOpeningRange(
        ClOpeningRangeParams(or_minutes=15, variant="breakout", max_attempts_per_day=2), _CL
    ).generate(_CL_DAY, bars, ctx)
    assert len(sigs_two) == 2
    assert {s.direction for s in sigs_two} == {LONG, SHORT}


def test_cl_breakout_no_signal_after_entry_deadline() -> None:
    bars = _cl_base_bars()
    bars.iloc[125, bars.columns.get_loc("high")] = 80.10  # well past default 120-minute deadline
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


def test_cl_breakout_no_signal_inside_news_block() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    trigger_ts = bars.index[15]
    news = [(trigger_ts - pd.Timedelta(minutes=1), trigger_ts + pd.Timedelta(minutes=1))]
    ctx = _cl_ctx(bars, news_windows=news)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


def test_cl_signal_tags_news_day_even_when_trigger_bar_is_clean() -> None:
    """meta['news_day'] flags the whole session, not just the entry bar, so
    inventory-report days can be sliced out even for entries that landed
    outside the blocked window itself."""
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    far_ts = bars.index[200]
    news = [(far_ts, far_ts + pd.Timedelta(minutes=5))]
    ctx = _cl_ctx(bars, news_windows=news)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert len(sigs) == 1
    assert sigs[0].meta["news_day"] is True


def test_cl_volume_filter_blocks_low_volume_and_passes_elevated_volume() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    params = ClOpeningRangeParams(or_minutes=15, variant="breakout", volume_filter=True, vol_mult=1.5)
    strat = ClOpeningRange(params, _CL)

    low_vol = bars.copy()
    low_vol.iloc[15, low_vol.columns.get_loc("volume")] = 400.0  # prior-day median is 300 -> 400 <= 1.5*300
    ctx_low = _cl_ctx(low_vol, with_prior_day=True)
    assert strat.generate(_CL_DAY, low_vol, ctx_low) == []

    high_vol = bars.copy()
    high_vol.iloc[15, high_vol.columns.get_loc("volume")] = 500.0  # 500 > 1.5*300 = 450
    ctx_high = _cl_ctx(high_vol, with_prior_day=True)
    sigs = strat.generate(_CL_DAY, high_vol, ctx_high)
    assert len(sigs) == 1
    assert sigs[0].meta["volume_ratio"] == pytest.approx(500.0 / 300.0)


def test_cl_volume_filter_blocks_when_no_prior_history_available() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    params = ClOpeningRangeParams(or_minutes=15, variant="breakout", volume_filter=True)
    ctx = _cl_ctx(bars)  # no prior day in history -> same_time_of_day_volume is None
    assert ClOpeningRange(params, _CL).generate(_CL_DAY, bars, ctx) == []


def test_cl_max_range_atr_pct_skips_day_when_or_too_wide() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    bars.iloc[5, bars.columns.get_loc("high")] = 81.00  # blow the OR wide open
    ctx = _cl_ctx(bars, with_prior_day=True)
    params = ClOpeningRangeParams(or_minutes=15, variant="breakout", max_range_atr_pct=0.1)
    assert ClOpeningRange(params, _CL).generate(_CL_DAY, bars, ctx) == []


def test_cl_max_range_atr_pct_allows_narrow_or() -> None:
    bars = _cl_base_bars()
    bars.iloc[15, bars.columns.get_loc("high")] = 80.10
    ctx = _cl_ctx(bars, with_prior_day=True)
    params = ClOpeningRangeParams(or_minutes=15, variant="breakout", max_range_atr_pct=5.0)
    sigs = ClOpeningRange(params, _CL).generate(_CL_DAY, bars, ctx)
    assert len(sigs) == 1


# --- breakout_retest --------------------------------------------------------


def _cl_retest_bars(*, do_retest: bool = True) -> pd.DataFrame:
    bars = _cl_base_bars()
    col = bars.columns.get_loc
    # breakout bar: closes beyond the OR high (confirmed close, not just a wick)
    bars.iloc[15, [col("open"), col("high"), col("low"), col("close")]] = [80.02, 80.10, 80.00, 80.08]
    if do_retest:
        # next bar pulls back and touches the edge (80.02) intrabar
        bars.iloc[16, [col("open"), col("high"), col("low"), col("close")]] = [80.08, 80.09, 80.02, 80.05]
    else:
        # price stays well clear of the edge for the whole retest window
        for k in range(16, 21):
            bars.iloc[k, [col("open"), col("high"), col("low"), col("close")]] = [80.08, 80.09, 80.05, 80.08]
    return bars


def test_cl_breakout_retest_long_fires_once_on_confirmed_retest() -> None:
    bars = _cl_retest_bars()
    ctx = _cl_ctx(bars)
    strat = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout_retest"), _CL)
    sigs = strat.generate(_CL_DAY, bars, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == LONG
    assert sig.entry_type == "limit"
    assert sig.entry == pytest.approx(80.02)  # the OR edge
    assert sig.stop == pytest.approx(79.98)  # opposite edge
    assert sig.ts == bars.index[16]  # the retest bar, not the breakout bar
    assert sig.meta["break_depth"] == pytest.approx(80.08 - 80.02)


def test_cl_breakout_retest_no_signal_when_no_retest() -> None:
    bars = _cl_retest_bars(do_retest=False)
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout_retest"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


def test_cl_breakout_retest_no_signal_when_no_confirmed_close() -> None:
    bars = _cl_base_bars()  # never closes beyond the edge at all
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="breakout_retest"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


# --- failed_breakout ---------------------------------------------------------


def _cl_failed_breakout_bars(*, do_reclaim: bool = True) -> pd.DataFrame:
    bars = _cl_base_bars()
    col = bars.columns.get_loc
    # breaks above OR high by >= min_break_ticks (4 ticks = 0.04): 80.06 >= 80.02+0.04
    bars.iloc[15, [col("open"), col("high"), col("low"), col("close")]] = [80.02, 80.08, 80.01, 80.06]
    if do_reclaim:
        bars.iloc[16, [col("open"), col("high"), col("low"), col("close")]] = [80.06, 80.06, 79.99, 80.00]
    else:
        for k in range(16, 22):
            bars.iloc[k, [col("open"), col("high"), col("low"), col("close")]] = [80.06, 80.12, 80.05, 80.10]
    return bars


def test_cl_failed_breakout_short_fires_once_on_reclaim() -> None:
    bars = _cl_failed_breakout_bars()
    ctx = _cl_ctx(bars)
    strat = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="failed_breakout"), _CL)
    sigs = strat.generate(_CL_DAY, bars, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == SHORT  # fading the failed upside break
    assert sig.entry_type == "market"
    assert sig.ts == bars.index[16]  # the reclaim bar
    assert sig.meta["failed_extreme"] == pytest.approx(80.08)
    # stop = failed_extreme + stop_buffer_ticks * tick_size (default 10 ticks = 0.10)
    assert sig.stop == pytest.approx(80.08 + 0.10)
    assert sig.entry < sig.stop  # short: entry below stop


def test_cl_failed_breakout_no_signal_when_no_reclaim() -> None:
    bars = _cl_failed_breakout_bars(do_reclaim=False)
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="failed_breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


def test_cl_failed_breakout_no_signal_when_break_too_shallow() -> None:
    bars = _cl_base_bars()
    col = bars.columns.get_loc
    # only 1 tick beyond the edge; min_break_ticks default is 4
    bars.iloc[15, [col("open"), col("high"), col("low"), col("close")]] = [80.02, 80.03, 80.01, 80.02]
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="failed_breakout"), _CL).generate(_CL_DAY, bars, ctx)
    assert sigs == []


def test_cl_failed_breakout_long_fires_symmetric_on_downside_break() -> None:
    bars = _cl_base_bars()
    col = bars.columns.get_loc
    bars.iloc[15, [col("open"), col("high"), col("low"), col("close")]] = [79.98, 79.99, 79.92, 79.94]
    bars.iloc[16, [col("open"), col("high"), col("low"), col("close")]] = [79.94, 80.01, 79.94, 80.00]
    ctx = _cl_ctx(bars)
    sigs = ClOpeningRange(ClOpeningRangeParams(or_minutes=15, variant="failed_breakout"), _CL).generate(_CL_DAY, bars, ctx)

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.direction == LONG
    assert sig.meta["failed_extreme"] == pytest.approx(79.92)
    assert sig.stop == pytest.approx(79.92 - 0.10)


# --- parameter validation ---------------------------------------------------


def test_cl_params_reject_invalid_or_minutes_and_variant() -> None:
    with pytest.raises(ValueError):
        ClOpeningRangeParams(or_minutes=10)  # must be one of 5, 15, 30
    with pytest.raises(ValueError):
        ClOpeningRangeParams(variant="not_a_variant")
    with pytest.raises(ValueError):
        ClOpeningRangeParams(stop_mode="not_a_mode")
