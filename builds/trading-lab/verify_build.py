#!/usr/bin/env python3
"""Build verification for the trading-lab PR branch (BUILD-20261117-009).

Covers brief Tasks 2-5 checks that the shipped test suite does not already
pin down: ES prior_swing LONDON-only truncation (GPT finding 1), CL
blocked-news skip rule (GPT finding 2), ES displacement ATR threshold +
news scope, DST/17:00-CT invariants, BacktestResult provenance stamping,
continuity fixtures, and config/script consistency.

Run from the workspace root:  venv/bin/python ../verify_build.py
Working dir must be src/trading-lab so `lab` imports resolve.
"""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "src" / "trading-lab"))

from lab.backtest.costs import CostModel  # noqa: E402
from lab.backtest.engine import BacktestEngine, fixed_contracts  # noqa: E402
from lab.backtest.exits import FixedR  # noqa: E402
from lab.core.config import LabConfig, load_config  # noqa: E402
from lab.core.frames import fingerprint  # noqa: E402
from lab.core.instruments import get_instrument  # noqa: E402
from lab.core.sessions import ASIA, CL_RTH, LONDON, trading_day, window_bounds  # noqa: E402
from lab.data.continuity import analyse_continuity  # noqa: E402
from lab.strategies.base import build_session_context  # noqa: E402
from lab.strategies.cl_opening_range import ClOpeningRange, ClOpeningRangeParams  # noqa: E402
from lab.strategies.es_london_sweep import EsLondonSweep, EsLondonSweepParams  # noqa: E402

ES = get_instrument("ES")
CL = get_instrument("CL")
DAY = pd.Timestamp("2024-01-09").date()  # ordinary Tuesday

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------- ES frame
def es_frame(*, sweep_k=None, disp_close=4790.0, asia_low_pos=-3,
             news_windows=(), reclaim_news=False):
    """1m bars: flat Asia (high 4802 / low 4790) + flat London (4800-4801).
    Carves a SHORT sweep at London bar `sweep_k` (02:00 + k min), reclaim at
    k+1, displacement at k+2. `asia_low_pos` places the 4790 Asia-low bar
    that many bars before the end of Asia (default -3 -> 01:57)."""
    a_start, a_end = window_bounds(ASIA, DAY)
    l_start, l_end = window_bounds(LONDON, DAY)
    idx = pd.date_range(a_start, l_end, freq="1min", tz="UTC", inclusive="left")
    bars = pd.DataFrame(
        {"open": 4796.0, "high": 4797.0, "low": 4795.0, "close": 4796.0, "volume": 500.0},
        index=idx)
    col = bars.columns.get_loc
    asia_idx = np.where((idx >= a_start) & (idx < a_end))[0]
    bars.iloc[asia_idx[5], col("high")] = 4802.0
    bars.iloc[asia_idx[asia_low_pos], col("low")] = 4790.0
    london_idx = np.where((idx >= l_start) & (idx < l_end))[0]
    for j in london_idx:
        bars.iloc[j, [col("open"), col("high"), col("low"), col("close")]] = [4800.5, 4801.0, 4800.0, 4800.5]
    if sweep_k is not None:
        si, ri, di = london_idx[sweep_k], london_idx[sweep_k + 1], london_idx[sweep_k + 2]
        bars.iloc[si, [col("open"), col("high"), col("low"), col("close")]] = [4801.0, 4804.0, 4800.0, 4802.5]
        bars.iloc[ri, [col("open"), col("high"), col("low"), col("close")]] = [4802.0, 4802.5, 4800.5, 4801.0]
        bars.iloc[di, [col("open"), col("high"), col("low"), col("close")]] = [4801.0, 4801.5, 4789.5, disp_close]
    return bars, idx, london_idx


def es_ctx(bars, news_windows=()):
    return build_session_context(DAY, bars, "ES", ES, news_windows=news_windows)


print("== A. ES prior_swing LONDON-only truncation (GPT finding 1) ==")
print("Sweep k = London 1m-bar index (02:00 + k min). Spec: prior_swing = min low")
print("over the 15 bars immediately before the sweep (incl. Asia bars).")
for k in [0, 1, 2, 3, 5, 10, 14, 15, 16, 20]:
    bars, idx, london_idx = es_frame(sweep_k=k)
    ctx = es_ctx(bars)
    sigs = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars, ctx)
    ps = sigs[0].meta["prior_swing"] if sigs else None
    print(f"  sweep 02:{k:02d} (London bar {k:2d}): "
          f"signal={'YES' if sigs else 'no '} prior_swing={ps} "
          f"lookback_bars_available={min(15, k)}")
check("A1 sweep at 02:00 (London bar 0) yields NO signal (prior_swing None)",
      not EsLondonSweep(EsLondonSweepParams(), ES).generate(
          DAY, *es_frame(sweep_k=0)[:1], es_ctx(es_frame(sweep_k=0)[0])))

print("\nAsia-swing divergence case: Asia low 4790 sits at 01:57, inside the")
print("spec's 15-bar lookback for a 02:03 sweep, but outside London.")
bars, idx, london_idx = es_frame(sweep_k=3, disp_close=4790.0)
ctx = es_ctx(bars)
sigs = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars, ctx)
atr = ctx.as_of(idx[london_idx[5]]).atr
print(f"  code prior_swing={sigs[0].meta['prior_swing'] if sigs else None} "
      f"(London-only), ATR at displacement={atr:.3f}, "
      f"threshold=0.5*ATR={0.5 * atr:.3f}")
print(f"  code emits signal: {bool(sigs)}; spec would NOT (spec prior_swing 4790, "
      f"need close <= {4790 - 0.5 * atr:.2f}, close is 4790.0)")
check("A2 code emits a signal the spec would NOT (Asia swing invisible to code)",
      bool(sigs) and sigs[0].meta["prior_swing"] == 4800.0)
bars, idx, london_idx = es_frame(sweep_k=0, disp_close=4785.0)
sigs0 = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars, es_ctx(bars))
print(f"  sweep at 02:00 with displacement close 4785: code signal={bool(sigs0)}; "
      f"spec WOULD signal (spec prior_swing 4790, need close <= {4790 - 0.5 * 1.0:.2f})")
check("A3 code MISSES a signal the spec would emit (first London bar)",
      not sigs0)

print("\n== B. CL blocked-news skip rule (GPT finding 2) ==")
print("Spec: blocked bars are SKIPPED for retest/reclaim and NEVER count toward")
print("N-bar windows; a blocked decision bar kills only that bar, not the setup.")

CL_DAY = pd.Timestamp("2024-03-05").date()
CL_START, CL_END = window_bounds(CL_RTH, CL_DAY)


def cl_bars():
    """OR high=80.02 / low=79.98; post-OR bars sit clearly ABOVE the OR high
    (80.04-80.06) so they neither trigger a breakout (high < ... no: they do
    not matter for retest/failed variants) nor count as a retest (low 80.04 >
    edge 80.02) nor as a reclaim (close 80.05 > or_high 80.02) unless a test
    explicitly carves one in."""
    idx = pd.date_range(CL_START, CL_END, freq="1min", tz="UTC", inclusive="left")
    n = len(idx)
    high = np.full(n, 80.06); low = np.full(n, 80.04)
    high[:15] = 80.02; low[:15] = 79.98
    return pd.DataFrame({"open": 80.05, "high": high, "low": low,
                         "close": 80.05, "volume": 500.0}, index=idx)


def cl_ctx(bars, news_windows=()):
    return build_session_context(CL_DAY, bars, "CL", CL, news_windows=news_windows)


def cl_gen(params, bars, news_windows=()):
    return ClOpeningRange(params, CL).generate(CL_DAY, bars, cl_ctx(bars, news_windows))


col = None
# B1: retest window must not count blocked bars.
bars = cl_bars(); c = bars.columns.get_loc
bars.iloc[15, [c("open"), c("high"), c("low"), c("close")]] = [80.02, 80.10, 80.00, 80.08]  # confirm
# bars 16,17,18 news-blocked; bar 21 (6th bar after confirm) touches the edge.
bars.iloc[21, [c("open"), c("high"), c("low"), c("close")]] = [80.08, 80.09, 80.02, 80.05]
news = [(bars.index[16], bars.index[18] + pd.Timedelta(minutes=1))]
sigs = cl_gen(ClOpeningRangeParams(or_minutes=15, variant="breakout_retest"), bars, news)
print(f"  B1 retest at bar 21 (3rd NON-blocked bar after confirm): signal={bool(sigs)} "
      f"(spec: YES — blocked bars 16-18 must not count toward the 5-bar window)")
check("B1 blocked bars do not count toward retest window", bool(sigs))

# B2: blocked retest bar must be skipped, not kill the candidate.
bars = cl_bars(); c = bars.columns.get_loc
bars.iloc[15, [c("open"), c("high"), c("low"), c("close")]] = [80.02, 80.10, 80.00, 80.08]
bars.iloc[16, [c("open"), c("high"), c("low"), c("close")]] = [80.08, 80.09, 80.02, 80.05]  # blocked retest
bars.iloc[17, [c("open"), c("high"), c("low"), c("close")]] = [80.08, 80.09, 80.02, 80.05]  # clean retest
news = [(bars.index[16], bars.index[16] + pd.Timedelta(minutes=1))]
sigs = cl_gen(ClOpeningRangeParams(or_minutes=15, variant="breakout_retest"), bars, news)
print(f"  B2 blocked retest bar 16, clean retest bar 17: signal={bool(sigs)} "
      f"ts={sigs[0].ts if sigs else None} (spec: YES at bar 17)")
check("B2 blocked retest bar is skipped, clean retest still signals", bool(sigs))

# B3: failed_breakout reclaim — same rule.
bars = cl_bars(); c = bars.columns.get_loc
bars.iloc[15, [c("open"), c("high"), c("low"), c("close")]] = [80.02, 80.08, 80.01, 80.06]  # break
bars.iloc[16, [c("open"), c("high"), c("low"), c("close")]] = [80.06, 80.06, 79.99, 80.00]  # blocked reclaim
bars.iloc[17, [c("open"), c("high"), c("low"), c("close")]] = [80.06, 80.06, 79.99, 80.00]  # clean reclaim
news = [(bars.index[16], bars.index[16] + pd.Timedelta(minutes=1))]
sigs = cl_gen(ClOpeningRangeParams(or_minutes=15, variant="failed_breakout"), bars, news)
print(f"  B3 blocked reclaim bar 16, clean reclaim bar 17: signal={bool(sigs)} "
      f"(spec: YES at bar 17)")
check("B3 blocked reclaim bar is skipped, clean reclaim still signals", bool(sigs))

# B4: control — breakout trigger skip works (news bars skipped in trigger scan).
bars = cl_bars(); c = bars.columns.get_loc
bars.iloc[15, c("high")] = 80.10  # blocked trigger bar
bars.iloc[16, c("high")] = 80.10  # clean trigger bar
news = [(bars.index[15], bars.index[15] + pd.Timedelta(minutes=1))]
sigs = cl_gen(ClOpeningRangeParams(or_minutes=15, variant="breakout"), bars, news)
print(f"  B4 breakout: blocked trigger 15, clean trigger 16: signal={bool(sigs)} "
      f"ts={sigs[0].ts if sigs else None} (spec: YES at bar 16)")
check("B4 breakout trigger scan skips blocked bars", bool(sigs) and sigs[0].ts == bars.index[16])

print("\n== C. ES displacement ATR threshold + news scope ==")
bars, idx, london_idx = es_frame(sweep_k=20, disp_close=4790.0)
ctx = es_ctx(bars)
sigs = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars, ctx)
atr = ctx.as_of(idx[london_idx[22]]).atr
print(f"  ATR at displacement bar: {atr:.3f}; threshold 0.5*ATR = {0.5 * atr:.3f}; "
      f"prior_swing = {sigs[0].meta['prior_swing']}")
check("C1 far displacement (close 4790) fires", bool(sigs))
bars2, idx2, li2 = es_frame(sweep_k=20, disp_close=4799.90)
sigs2 = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars2, es_ctx(bars2))
print(f"  displacement close 4799.90 (inside prior_swing - 0.5*ATR = "
      f"{4800 - 0.5 * atr:.2f}): signal={bool(sigs2)} (spec: no)")
check("C2 marginal displacement inside ATR threshold does NOT fire", not sigs2)
# C3: reclaim bar inside a news block must NOT kill the setup (ES blocks news
# on sweep and displacement only, per spec + GPT confirmation).
bars3, idx3, li3 = es_frame(sweep_k=20, disp_close=4790.0)
reclaim_ts = idx3[li3[21]]
news = [(reclaim_ts - pd.Timedelta(seconds=30), reclaim_ts + pd.Timedelta(seconds=30))]
sigs3 = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars3, es_ctx(bars3, news))
print(f"  reclaim bar inside news block: signal={bool(sigs3)} (spec: YES — ES "
      f"news-blocks sweep + displacement only)")
check("C3 ES reclaim inside news block still signals", bool(sigs3))
check("C4 ES signals carry empty targets (no target set by strategy)",
      bool(sigs) and sigs[0].targets == ())

print("\n== D. Invariants: DST / 17:00 CT roll / provenance / costs / config ==")
# D1 DST: London window must stay 02:00-07:00 CT wall-clock across the
# 2024-03-10 spring-forward (CST -6 -> CDT -5).
for d, exp_start_utc in [(date(2024, 3, 8), "08:00"), (date(2024, 3, 11), "07:00"),
                         (date(2024, 11, 4), "08:00")]:
    s, e = window_bounds(LONDON, d)
    local_s, local_e = s.tz_convert("America/Chicago"), e.tz_convert("America/Chicago")
    ok = s.strftime("%H:%M") == exp_start_utc and local_s.strftime("%H:%M") == "02:00" \
        and local_e.strftime("%H:%M") == "07:00"
    print(f"  LONDON {d}: UTC {s.strftime('%H:%M')}-{e.strftime('%H:%M')} "
          f"CT {local_s.strftime('%H:%M')}-{local_e.strftime('%H:%M')}")
    check(f"D1 LONDON window wall-clock 02:00-07:00 CT on {d}", ok)
s, e = window_bounds(ASIA, date(2024, 3, 11))
print(f"  ASIA 2024-03-11: {s} -> {e} (must span the DST night, ending 02:00 CDT)")
check("D1b ASIA window anchors across spring-forward night",
      s.tz_convert("America/Chicago").strftime("%H:%M") == "18:00"
      and e.tz_convert("America/Chicago").strftime("%H:%M") == "02:00")
# D2 17:00 CT roll.
t_before = pd.Timestamp("2024-03-08 22:59", tz="UTC")  # 16:59 CST
t_at = pd.Timestamp("2024-03-08 23:00", tz="UTC")      # 17:00 CST
print(f"  trading_day(16:59 CST)={trading_day(t_before)} trading_day(17:00 CST)={trading_day(t_at)}")
check("D2 CME day rolls at 17:00 CT",
      trading_day(t_before) == date(2024, 3, 8) and trading_day(t_at) == date(2024, 3, 9))
# D3 provenance: run a real backtest, check the stamp.
bars, idx, li = es_frame(sweep_k=20, disp_close=4790.0)
ctx = es_ctx(bars)
sigs = EsLondonSweep(EsLondonSweepParams(), ES).generate(DAY, bars, ctx)
eng = BacktestEngine(ES, CostModel(commission_round_turn=4.0, slippage_ticks=1.0),
                     LabConfig(pessimistic_intrabar=True))
res1 = eng.run(bars, sigs, FixedR(1.5), fixed_contracts(1), strategy="es_london_sweep", version="v1.0")
res2 = eng.run(bars, sigs, FixedR(1.5), fixed_contracts(1), strategy="es_london_sweep", version="v1.0")
print(f"  BacktestResult: trades={len(res1.trades)} fingerprint={res1.data_fingerprint!r} "
      f"params={dict(res1.params)}")
check("D3 BacktestResult carries a non-empty data fingerprint",
      bool(res1.data_fingerprint) and res1.data_fingerprint == fingerprint(bars))
check("D3b fingerprint is deterministic across identical runs",
      res1.data_fingerprint == res2.data_fingerprint)
check("D3c BacktestResult stamps code params (costs + pessimistic_intrabar)",
      res1.params.get("commission_round_turn") == 4.0
      and res1.params.get("pessimistic_intrabar") is True)
# D4 conservative cost defaults.
print(f"  ES defaults: commission ${ES.commission_round_turn}/RT, slippage "
      f"{ES.default_slippage_ticks} tick; CL ${CL.commission_round_turn}/RT")
check("D4 conservative cost defaults present (ES $4.00, CL $4.40, 1.0 tick slip)",
      ES.commission_round_turn == 4.00 and CL.commission_round_turn == 4.40
      and ES.default_slippage_ticks == 1.0)
# D5 config loads + unknown keys rejected.
cfg = load_config()
print(f"  config: timeframe={cfg.default_timeframe} account=${cfg.account_size} "
      f"seed={cfg.random_seed} pessimistic_intrabar={cfg.pessimistic_intrabar}")
check("D5 config.yaml loads with expected values",
      cfg.default_timeframe == "1m" and cfg.account_size == 150000
      and cfg.random_seed == 20260805 and cfg.pessimistic_intrabar is True)
try:
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.yaml"
        bad.write_text("default_timeframe: '1m'\ncomission_round_turn: 9\n")
        load_config(str(bad))
    check("D5b unknown config key rejected", False, "no error raised")
except ValueError as exc:
    check("D5b unknown config key rejected", "unknown config keys" in str(exc), str(exc)[:100])

print("\n== E. Continuity fixtures (Task 4) ==")


def daily_bars(start, end, price0=5000.0, seed=7):
    days = pd.bdate_range(start, end) + pd.Timedelta(hours=14, minutes=30)
    idx = pd.DatetimeIndex(days).tz_localize("UTC")
    rng = np.random.default_rng(seed)
    n = len(idx)
    closes = price0 + np.cumsum(rng.normal(0, 0.3, size=n))
    opens = closes - rng.normal(0, 0.1, size=n)
    return pd.DataFrame({"open": opens, "high": np.maximum(opens, closes) + 0.5,
                         "low": np.minimum(opens, closes) - 0.5, "close": closes,
                         "volume": 1000.0}, index=idx)


def inject_jump(df, roll_date, jump):
    out = df.copy()
    mask = out.index.date >= pd.Timestamp(roll_date).date()
    out.loc[mask, ["open", "high", "low", "close"]] += jump
    return out


df = daily_bars("2024-01-02", "2024-03-01")  # ~43 trading days < one quarterly cycle
r = analyse_continuity(df, ES)
print(f"  single-expiry (short span, no jumps): verdict={r.verdict} "
      f"rolls={len(r.roll_events)} confidence={r.confidence:.2f}")
check("E1 short quiet span -> likely_single_expiry", r.verdict == "likely_single_expiry")
df = inject_jump(daily_bars("2024-01-02", "2024-06-28"), "2024-03-15", 50.0)
r = analyse_continuity(df, ES)
print(f"  stitched (+50 jump 2024-03-15): verdict={r.verdict} rolls="
      f"{[(str(e.trading_day), round(e.gap, 1)) for e in r.roll_events]}")
check("E2 stitched roll gap -> likely_continuous_stitched_raw, 1 event on 2024-03-15",
      r.verdict == "likely_continuous_stitched_raw" and len(r.roll_events) == 1
      and str(r.roll_events[0].trading_day) == "2024-03-15")
df = daily_bars("2024-01-02", "2024-06-28", price0=30.0)
early = df.index.date <= pd.Timestamp("2024-02-01").date()
df.loc[early, ["open", "high", "low", "close"]] -= 60.0
r = analyse_continuity(df, ES)
print(f"  back-adjusted (early history pushed < 0): verdict={r.verdict} "
      f"neg_bars={r.n_negative_bars} confidence={r.confidence:.2f}")
check("E3 negative prices -> likely_continuous_backadjusted",
      r.verdict == "likely_continuous_backadjusted" and r.has_negative_prices)

print("\n== F. Config/script consistency (Task 5) ==")
root = Path(__file__).resolve().parent / "src" / "trading-lab"
print(f"  scripts/measure_costs.py exists: {(root / 'scripts' / 'measure_costs.py').exists()}")
print(f"  lab/journal/costs_measure.py exists: {(root / 'lab' / 'journal' / 'costs_measure.py').exists()}")
print(f"  scripts dir: {sorted(p.name for p in (root / 'scripts').glob('*.py'))}")
check("F1 scripts/measure_costs.py does NOT exist (stale comment, not a missing CLI)",
      not (root / "scripts" / "measure_costs.py").exists())
check("F2 cost-measurement code lives at lab/journal/costs_measure.py",
      (root / "lab" / "journal" / "costs_measure.py").exists())
check("F3 config.yaml comment is the ONLY reference to scripts/measure_costs.py",
      "scripts/measure_costs.py" in (root / "config" / "config.yaml").read_text()
      and sum("scripts/measure_costs.py" in p.read_text(errors="ignore")
              for p in root.rglob("*") if p.is_file()
              and "__pycache__" not in str(p) and ".pyc" not in p.name) == 1)

print(f"\n==== SUMMARY: {len(PASS)} passed, {len(FAIL)} failed ====")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print(f"  - {f}")
sys.exit(1 if FAIL else 0)
