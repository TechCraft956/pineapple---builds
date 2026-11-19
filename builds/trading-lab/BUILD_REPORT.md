# BUILD REPORT — Trading-lab PR (BUILD-20261117-009)
**Brief:** `~/workspace/pineapple/build-briefs/TRADING_LAB_BUILD_BRIEF.md`
**Source:** `TechCraft956/localedge-site`, PR #2 branch `claude/lse-trading-setup-dw4siy`
**Workspace:** `~/workspace/pineapple/builds/trading-lab/`
**Date:** 2026-11-17 (run ~18:40–19:10 CT)
**Verdict: BUILT AND VERIFIED OFFLINE — with two spec-vs-code findings (one confirmed
discrepancy, one confirmed rule gap). No broker, no LSE key, no network in tests,
no Pineapple NEXT contact. Adoption decision is Airam's (see ADOPTION_MEMO.md).**

## 1. Source fetched (Task 1)
- Fetched read-only via the connected GitHub connector (`get_file_contents`, ref
  `refs/heads/claude/lse-trading-setup-dw4siy`); direct `git clone` is blocked in
  this sandbox (no auth for github.com over HTTPS). No merge, close, or comment
  on PR #2; the GitHub repo is untouched.
- **92 unique files** on disk under `src/trading-lab/` (fetch manifest counted 142
  entries because the walker double-listed 50 files — cosmetic script bug, no
  files missing: disk set == manifest unique set). Layout matches the brief:
  `lab/` 51 Python files (42 code + 9 `__init__.py`; the brief's "44" counts
  differently — see §7), `tests/` 21 test files + `helpers.py`, `scripts/` 6 CLIs,
  `specs/` 2, `docs/` 4, `config/config.yaml`, `requirements.txt`, `pyproject.toml`,
  `.env.example`, `.gitignore`, `README.md`.
- Recovered originals untouched: `~/workspace/pineapple/recovered/localedge-site/`
  still holds only its two main-branch files (README.md, index.html, dated
  2026-11-17 16:54); no file under `~/workspace/pineapple/recovered/` is newer
  than the brief. The build ran entirely in the isolated workspace copy.

## 2. Environment (Task 1)
- Clean venv `src/venv/`, **Python 3.12.3** (>= 3.11 required).
- Installed (minimal set — see §7 for why xgboost/jupyter are absent):
  pandas 3.1.1, numpy 2.5.5, pyarrow 26.0.1, scikit-learn 1.9.1, PyYAML 6.0.3,
  matplotlib 3.11.2, lse-data 3.0.1, pytest 9.2.0, scipy 1.18.1, joblib 1.6.0,
  tzdata 2026.6. (`lse-data` installed but never called — no key, no network.)
- No `LSE_API_KEY` was created or used in any step (all runs with the variable unset).

## 3. Test suite (Task 1) — 263/263 pass, 0 skipped, 0 failed
- Command: `env -u LSE_API_KEY venv/bin/python -m pytest -q` from `src/trading-lab/`
  (re-run after the §6 comment fix: same result, exit 0; junit XML parsed for exact counts).
- **Total: 263 passed, 0 failed, 0 errors, 0 skipped.** Per-file:
  test_account 15, test_adherence 12, test_client 11, test_continuity 8,
  test_data_cache 9, test_economics 8, test_engine 14, test_exits 11,
  test_importer 17, test_journal 6, test_loaders 13, test_metrics 5,
  test_ml_features 17, test_ml_models 21, test_montecarlo 13, test_reports 9,
  test_risk_rules 12, test_robustness 15, test_strategies 27, test_survival 11,
  test_walkforward 9.
- Classification: **no test needs a key or network.** `test_client.py` states
  "No network" and doubles the `lse` SDK (`_import_lse` replaced); the only
  HTTP-looking strings in tests are a fake error class and a report assertion
  that no URL leaks into output. No test is marked live/skipped. The suite
  passes with xgboost absent (the ML layer degrades to
  `HistGradientBoostingClassifier`; see §7).
- One cosmetic warning class: 39× `Pandas4Warning: Timestamp.dayofweek is
  deprecated` from `lab/ml/features.py:413` (pandas 3.1.1) — works today, will
  break on a future pandas that removes `dayofweek`; should be `day_of_week`.

## 4. Invariants (Task 2)
Verified with the shipped suite plus added checks in `verify_build.py`
(25 passed / 3 failed — the 3 failures are all Finding F-2 in §5).

| # | Invariant | Evidence |
|---|---|---|
| 1 | UTC internally; Chicago session windows; DST handled by tz db | **Verified by added check D1.** `window_bounds(LONDON)` stays 02:00–07:00 CT wall-clock across the 2024-03-10 spring-forward (UTC 08:00–13:00 on 2024-03-08 → 07:00–12:00 on 2024-03-11) and the 2024-11-03 fall-back (back to 08:00–13:00 UTC on 2024-11-04); ASIA anchors 18:00→02:00 across the DST night. **Gap in shipped suite:** no test crosses a DST boundary — `test_robustness.py` deliberately stays "on one side of the US DST transition". The code path (`tz_localize` with `nonexistent="shift_forward"`, `ambiguous=True`) is correct and now empirically verified here. |
| 2 | CME trading day rolls at 17:00 CT | **Verified by added check D2 + shipped tests.** `trading_day(16:59 CST)=2024-03-08`, `trading_day(17:00 CST)=2024-03-09`. Shipped: `test_daily_pnl_groups_by_cme_trading_day_not_calendar_date`, `test_max_attempts_per_day_resets_on_a_new_trading_day`, `test_session_end_flattens_at_window_end_of_the_entry_trading_day` — all pass. |
| 3 | No lookahead | **Verified by shipped tests (all pass).** `test_no_lookahead_invariance_appending_future_bars_does_not_change_trades`, `test_features_are_bit_identical_before_and_after_future_bars`, `test_features_bit_identical_with_bars_truncated_exactly_at_as_of`, `test_build_dataset_raises_on_a_planted_lookahead_feature`, `test_build_dataset_does_not_raise_when_leaky_feature_only_reads_up_to_as_of`, `test_each_registry_feature_individually_ignores_future_bars[...]` (10 features), `test_point_in_time_guard_rejects_future_release` (releases unreadable before publish), `test_dist_to_prior_day_high_atr_ignores_future_bars`, `test_sweep_depth_ticks_ignores_future_bars`, `test_purge_removes_train_samples_whose_outcome_reaches_into_test`. |
| 4 | Pessimistic intrabar + ambiguous-bar counting | **Verified by shipped tests (all pass).** `test_ambiguous_bar_resolves_stop_first_under_pessimistic_default` (asserts `ambiguous_bars_total == 1`, `..._resolved_by_pessimistic_default == 1`), `test_ambiguous_bar_resolves_via_finer_bars_when_they_prove_target_first`. |
| 5 | Costs are assumptions until measured (conservative defaults) | **Verified by added check D4 + shipped tests.** ES $4.00 / MES $1.00 / CL $4.40 / MCL $1.20 round-turn, 1.0 tick slippage in `lab/core/instruments.py`, matching `config.yaml` overrides. Shipped: `test_defaults_are_defaults_not_guesses`, `test_cost_arithmetic_to_the_cent_on_one_es_trade`, `test_build_cost_overrides_*` (3 tests). |
| 6 | Results carry provenance | **Implemented and verified by added check D3; shipped-test gap.** Every `BacktestResult` stamps `params` (max_concurrent, costs, `pessimistic_intrabar`, `finer_bars_supplied`) and `data_fingerprint` = SHA-256 of the bar frame (`lab/core/frames.py:fingerprint`). Added check: fingerprint `15e1ff66484ef90c` on the textbook ES run, identical across re-runs, params present. **Gap:** no shipped test asserts a `BacktestResult` carries a non-empty fingerprint — `test_every_preset_carries_provenance` covers risk-rule presets (`RULES_AS_OF` + source note), and `test_data_cache.py` covers cache fingerprints, but the engine stamp itself is untested. |

## 5. Spec-vs-code conformance (Task 3)
Full tables below. Two GPT-flagged checks resolved; both are findings, not fixes —
no strategy code was rewritten.

### 5a. ES London sweep — spec `specs/es_london_sweep.md` v1.0 vs `lab/strategies/es_london_sweep.py`

| Rule | Code | Verdict |
|---|---|---|
| Asia range 18:00–02:00 CT, anchored to end inside the trading day | `ASIA` window via `build_session_context` / `session_levels` | MATCH |
| Entry window LONDON 02:00–07:00 CT; no bar outside scanned | `slice_window(bars, LONDON, day)` | MATCH |
| Sweep: first bar ≥ 4 ticks beyond Asia extreme; news-blocked bars skipped | `_scan` sweep loop, `continue` on `in_news_block` | MATCH |
| Reclaim: first close back inside Asia range within 6 bars after sweep | reclaim loop, no news check (spec requires none) | MATCH |
| Displacement: close breaks prior swing (15 bars before sweep) by ≥ 0.5×ATR, ATR from `ctx.as_of(ts)` | displacement loop, `threshold = 0.5 * atr`, `close <= prior_swing - threshold` | **MISMATCH — Finding F-1** (lookback truncated to London window) |
| Displacement bar in news block → no signal | `if ctx.in_news_block(decision_ts): return None` | MATCH |
| Entry limit at 50% retrace, tick-rounded; market at displacement close | `entry = displaced_close + 0.5*(sweep_extreme - displaced_close)`, `round_to_tick` | MATCH |
| Stop 3 ticks beyond sweep extreme | `sweep_extreme ± 3*0.25` | MATCH |
| No target / no max hold set by strategy (`targets` empty) | `Signal.targets` defaults `()`; added check C4 confirms | MATCH |
| `max_attempts_per_day` 1; both directions scanned, sorted, truncated | `generate` sorts by `ts`, slices `[:max_attempts]` | MATCH |
| Overnight-range filter (both bounds default None) | implemented as specified | MATCH |
| No Asia data / no sweep / no reclaim / no displacement / ATR None or ≤ 0 → no signal | all present | MATCH |
| Tick-rounding violation → skip, not fabricate | `try: Signal(...) except ValueError: return None` | MATCH |
| Parameter defaults (4 / 6 / 15 / 0.5 / 0.5 / limit / 3 / LONDON / 1 / 10) | dataclass defaults identical | MATCH |

**Finding F-1 — CONFIRMED (GPT finding 1): ES `prior_swing` is computed from
London-only bars, not the spec's "15 bars immediately before the sweep."**
Code: `window = slice_window(bars, LONDON, day)`; `prior_swing` = min/max over
`window.iloc[max(0, sweep_idx-15):sweep_idx]`. Quantified on 1-minute bars
(`verify_build.py` §A, Asia high 4802 / low 4790, London flat 4800–4801):

| Sweep time (CT) | London bar index | Lookback bars available | Signal? |
|---|---|---|---|
| 02:00 | 0 | 0 — `prior_swing` is `None` | **NO signal at all** |
| 02:01–02:14 | 1–14 | 1–14 (truncated) | Yes, but swing from London bars only |
| 02:15+ | 15+ | 15 (full, but London-only) | Yes |

Affected sweep times: **02:00–02:14 CT** (the first 15 minutes of London) have a
truncated lookback; **02:00 itself can never signal**. Behavioural divergence
demonstrated (Asia low 4790 placed at 01:57, inside the spec's 15-bar window
for a 02:03 sweep): code `prior_swing = 4800.0`, ATR 3.20, threshold 1.60 —
code **emits** a signal on displacement close 4790.0 (4790 ≤ 4800 − 1.60), while
the spec's `prior_swing = 4790` would require close ≤ 4788.40, i.e. **no signal**.
Conversely a 02:00 sweep with displacement close 4785 **would** signal under the
spec (prior_swing 4790, need ≤ 4789.50) but the code emits nothing. This is a
real, falsifiable deviation: early-London sweeps are evaluated against a
different (higher for shorts / lower for longs) swing than the spec defines.
Recorded as a finding; the strategy was NOT rewritten.

**ES displacement ATR threshold — CONFIRMED matching (added checks C1–C2).**
At the displacement bar ATR = 2.000, threshold = 1.000: close 4790 fires;
close 4799.90 (inside `prior_swing − 0.5·ATR = 4799.00`) does not.
**ES news scope — CONFIRMED matching (added check C3 + shipped test).**
News blocks sweep scan and the displacement bar only; a reclaim bar inside a
news block still signals (spec + GPT confirmation). Shipped
`test_es_london_sweep_no_signal_inside_news_block` covers the displacement case.

### 5b. CL opening range — spec `specs/cl_opening_range.md` v1.0 vs `lab/strategies/cl_opening_range.py`

| Rule | Code | Verdict |
|---|---|---|
| OR = high/low of first `or_minutes` (5/15/30) of CL_RTH 08:00 CT | `or_bars` from `window_bounds(CL_RTH)` | MATCH |
| Scan post-OR bars within CL_RTH (ends 13:30); no new entry after `entry_deadline_minutes` (120) | `post_or` bounded by session end; `ts >= deadline_ts → break`; decision-bar deadline check | MATCH |
| News: every trigger/confirm/break/retest/reclaim bar checked; blocked bars skipped and NEVER counted toward N-bar windows | Trigger/confirm/break scans skip (`continue`); **retest/reclaim loops do not** | **MISMATCH — Finding F-2** |
| `breakout`: first post-OR bar trades through edge; volume filter on same bar; `Signal.ts` = trigger bar | `_scan_breakout` | MATCH |
| `breakout_retest`: confirm (close beyond edge + volume filter), then retest within 5 bars (range touches edge); `Signal.ts` = retest bar | `_scan_retest` | MATCH except F-2 |
| `failed_breakout`: break ≥ 4 ticks beyond edge, reclaim (close back inside) within 6 bars; `Signal.ts` = reclaim bar | `_scan_failed` | MATCH except F-2 |
| Entry types/prices: breakout `stop` @ edge; retest `limit` @ edge; failed `market` @ reclaim close; `valid_until` = decision + `order_valid_bars` | as specified | MATCH |
| Stops: breakout/retest `opposite_edge` (default) or `buffer`; failed always `buffer` beyond failed extreme | `_stop_for` + failed-breakout stop | MATCH |
| No target / no max hold set by strategy | `Signal.targets` defaults `()` | MATCH |
| `max_attempts_per_day` 1; directions scanned independently, sorted, truncated | `generate` | MATCH |
| `news_day` meta: any blocked window overlapping CL_RTH flags the day | `any(w_start < end and w_end > start ...)` | MATCH (shipped test `test_cl_signal_tags_news_day_even_when_trigger_bar_is_clean`) |
| Invalidation: no OR bars / degenerate OR / `max_range_atr_pct` / no post-OR bars / deadline / volume filter / decision bar in news / tick-rounding | all present | MATCH |
| Parameter defaults (15 / breakout / opposite_edge / 10 / 4 / 6 / 5 / 5 / False / 1.5 / None / 1 / 120) | dataclass defaults identical; invalid values rejected (`__post_init__`, shipped test) | MATCH |

**Finding F-2 — CONFIRMED (GPT finding 2, now tested): the CL blocked-news skip
rule is NOT implemented for retest/reclaim.** In `_scan_retest` and
`_scan_failed`, the retest/reclaim loops contain **no `in_news_block` check at
all**. Two consequences, both demonstrated in `verify_build.py` §B (OR
80.02/79.98, 1-minute bars):
1. **Blocked bars consume window slots.** Confirm at bar 15; bars 16–18
   news-blocked; a retest at bar 21 is the 3rd *non-blocked* bar after confirm
   (spec: within the 5-bar window → signal). Code scans only `range(16, 21)`
   — a fixed positional window — so bar 21 is never examined: **no signal**
   (check B1 FAIL).
2. **A blocked retest/reclaim bar aborts the candidate instead of being
   skipped.** Blocked retest bar 16 (touches the edge) + clean retest bar 17:
   code picks bar 16 as `retest_idx`, then the end-of-scan
   `in_news_block(decision_ts)` check returns `None` — **no signal**, where the
   spec requires a signal at bar 17 (check B2 FAIL). Same for
   `failed_breakout` reclaim: blocked reclaim bar 16 + clean reclaim bar 17 →
   **no signal** (check B3 FAIL).
The `breakout` variant is unaffected: its trigger scan does `continue` on
blocked bars (check B4 PASS — blocked trigger 15, clean trigger 16 → signal at
16; shipped test covers the negative case). Net effect: on inventory-report
days (EIA/API), CL `breakout_retest` and `failed_breakout` will silently miss
setups the spec says should fire, and will burn their one attempt per day on a
news-blocked bar. Recorded as a finding; the strategy was NOT rewritten.

## 6. Config/script consistency (Task 5) — RESOLVED: stale comment
- `config/config.yaml` line 13 pointed at `scripts/measure_costs.py`, which does
  **not** exist in the branch (scripts are: audit_catalog, fetch_data,
  journal_import, report_premarket, report_session, simulate_account).
- The cost-measurement code lives at `lab/journal/costs_measure.py`
  (`measure_costs()` + `build_cost_overrides_yaml()`), exported via
  `lab/journal/__init__.py`, and tested in `test_adherence.py`
  (`test_measure_costs_computes_stats_regardless_of_sample_size`, etc.).
- `scripts/measure_costs.py` is referenced **nowhere else** in the branch
  (single grep hit: the config comment).
- **Verdict: stale comment, not a missing CLI.** Minimal fix applied **in the
  isolated workspace copy only**: the comment now reads
  "`lab/journal/costs_measure.py: measure_costs() + build_cost_overrides_yaml();
  there is no scripts/measure_costs.py CLI in this branch`". The branch, the
  repo, and the PR are untouched. `load_config()` still loads cleanly after
  the edit (verified: `1m / 150000 / 20260805`), and the full suite re-ran
  263/263 after the edit.
- Unknown config keys are rejected: `load_config` raises `ValueError`
  ("unknown config keys ['comission_round_turn']...") — verified by added check D5b.

## 7. Data-verification procedure (Task 4)
- **Live audit NOT run — no key exists, by design.** `scripts/audit_catalog.py`
  was executed without `LSE_API_KEY`: it exits 1 with the actionable message
  "`LSE_API_KEY` is not set. Get a free key at https://londonstrategicedge.com/data
  and export it … or put it in …/.env (git-ignored). Never commit it." — no
  traceback, no network attempt. The key-gated live audit is documented as a
  HUMAN STEP for Airam (below), not attempted.
- **Continuity flagging verified on synthetic fixtures** (added checks E1–E3,
  plus the shipped `test_continuity.py`, 8/8 pass):
  - Single-expiry (quiet 43-trading-day span, no jumps): verdict
    `likely_single_expiry`, 0 roll events, confidence 0.50.
  - Stitched (+50 jump on 2024-03-15, a quarterly expiry month): verdict
    `likely_continuous_stitched_raw`, 1 roll event (2024-03-15, gap +50.1),
    `near_expiry_cycle=True`.
  - Back-adjusted (early history shifted −60, pushing prices below zero):
    verdict `likely_continuous_backadjusted`, 92 negative bars, confidence 0.90.
  - The module's own stated limitation is honoured: a seamlessly back-adjusted
    series with no negative prices is indistinguishable from a single contract
    by price alone, and the report says so in its warnings.
- **Human step for Airam (free key, londonstrategicedge.com/data):**
  ```
  export LSE_API_KEY='...'        # or put it in trading-lab/.env (git-ignored)
  .venv/bin/python scripts/audit_catalog.py --categories futures,bonds,volatility
  # writes results/catalog_audit_<timestamp>.csv + .md; prints dataset counts
  # grouped by category and inferred contract_type_guess
  .venv/bin/python scripts/fetch_data.py --symbols ES,CL --timeframe 1h \
      --start 2024-01-01 --end 2024-06-01
  ```
  Expected output shape (from the code): a CSV/markdown catalog audit listing
  every dataset with history span and an *inferred* contract type, then per
  symbol the continuity verdict must be established with
  `lab/data/continuity.py` + `docs/verification-checklist.md` against the
  broker's chart before any backtest result influences a real order.

## 8. Files changed (in the isolated workspace only)
| File | Change |
|---|---|
| `src/trading-lab/config/config.yaml` | Comment-only fix (§6): stale `scripts/measure_costs.py` reference corrected to `lab/journal/costs_measure.py`. No code, no values changed. |
| `verify_build.py` (workspace root) | Added verification script: ES prior_swing quantification, CL blocked-news tests, ES displacement/news-scope checks, DST + 17:00-CT + provenance + cost + config checks, continuity fixtures. Result: **25 passed, 3 failed** (the 3 failures are Finding F-2). |
| `BUILD_REPORT.md` (this file) | Build report. |
| `ADOPTION_MEMO.md` | Adoption memo with the named decision for Airam. |
| `fetch_branch.py` | Read-only fetch script used to pull the branch via the GitHub connector (kept for reproducibility). |
| `src/MANIFEST.json`, `src/pytest_*.log`, `src/pytest_*.xml` | Fetch manifest + test evidence. |
| `src/venv/` | Clean venv (Python 3.12.3). |

Nothing in `~/workspace/pineapple/recovered/` was modified; nothing on GitHub was
modified; no file was written to the AI Bridge sheet or to `PIPELINE_STATE.md`
(parent's job).

## 9. Surprises / notes
- **Full `requirements.txt` install fails in this sandbox** (not a lab bug):
  `xgboost>=2.0` pulls the 206 MB `nvidia_nccl_cu13` wheel and the download
  died with `OSError: [Errno 28] No space left on device` (pip's temp usage
  against the 512 MB `/tmp` tmpfs; `/home` itself has 148 GB free). Workaround:
  installed the minimal set (core deps + `lse-data[frames]` + pytest, no
  xgboost, no jupyter) with `TMPDIR` pointed at the workspace — succeeded.
  Consequence: the xgboost model rung is **untested here** (no test in
  `test_ml_models.py` references xgboost at all; the lab degrades gracefully
  to `HistGradientBoostingClassifier` and all 21 ML-model tests pass). If Airam
  adopts the lab, xgboost should be installed on the research machine and the
  ML tests re-run there.
- **pandas 3.1.1 deprecation:** `Timestamp.dayofweek` used at
  `lab/ml/features.py:413` (39 warnings in the suite) — works now, will break
  on a future pandas; one-line fix to `day_of_week`.
- **Count note:** `lab/` holds 51 Python files (42 + 9 `__init__.py`), not the
  brief's "44"; `tests/` holds 21 test files + `helpers.py` (the brief's "22"
  counts helpers). No file is missing — the on-disk set matches the branch tree.
- **No test crosses a DST boundary** (see invariant 1 gap) and **no shipped
  test asserts `BacktestResult.data_fingerprint`** (see invariant 6 gap). Both
  behaviours were verified by the added checks in this build; upstream, two
  small tests would close the gaps.
- The ES strategy's `_scan` iterates SHORT first, then LONG (spec says so);
  CL iterates LONG first, then SHORT — both sort by timestamp and truncate to
  `max_attempts_per_day`, so the observable result is the same.

## 10. Acceptance checklist (brief)
- [x] Clean-venv install succeeds; full pytest suite runs, every result
      classified: **263/263 pass, 0 skipped, offline, no key, no network.**
- [x] All six invariants have a named passing test or a recorded gap (§4).
- [x] Spec-conformance tables written for both strategies; discrepancies are
      findings (§5: F-1 confirmed + quantified, F-2 confirmed + tested).
- [x] Continuity flags verified on synthetic fixtures; key-gated live audit
      documented as Airam's step, not attempted (§7).
- [x] Config/script inconsistency resolved and recorded, minimal fix applied (§6).
- [x] Adoption memo written with the named decision; no feed wiring built; no
      broker or account contact of any kind.
