# BUILD REPORT — Decision Engine trio (BUILD-20261117-004)

Built 2026-11-17 in `~/workspace/pineapple/builds/decision-engine/`.
Stage claimed: **VERIFIED** — every acceptance check in the brief passes
(see evidence below). Recovered originals untouched; all work in this
isolated workspace. No sheet or state-file writes were made by this build
(the parent owns those).

## What was built

- **First-run kit (Task 1).** Runtime dirs seeded; `00_INDEX/source_config.json`
  for this Linux/cloud sandbox (Windows host paths kept only as a
  `_path_map_for_this_sandbox` mapping to the workspace sample sources);
  three SAMPLE inbox fixtures (money / risk / opportunity notes) plus one
  recorded scan fixture; `.pineapple_root` marker (load-bearing — see below).
- **Stale-context rule (Task 2).** Defined, implemented, documented in
  `STALE_CONTEXT_RULE.md`: items older than 30 days decay −10 quant, are
  flagged `stale` with `age_days`, and carry a STALE doctrine flag. Fresh
  items untouched; missing date treated as fresh.
- **Test suite (Task 2 + 4).** `tests/test_decision_engine.py` — 21 tests,
  stdlib only, no network: quant dims/boundaries, doctrine penalties,
  context dedup, scanner write-safety (explicit allowlist: writes ONLY
  inside `00_INDEX` / `00_PROCESSED`, anything else raises), outcomes
  append-only, stale rule (incl. the 30/31-day boundary), learned-weights
  flag, boundary guard. **21 passed, 0 failed** (3 consecutive runs).
- **Feed writer (Task 3).** `writers/decision_brief_writer.py` (stdlib only).
  Mapping documented in `FEED_MAPPING.md`: quant → confidence (quant/100);
  `roi_estimate` carried raw in `provenance.roi_estimate` — null stays null,
  never 0; `est_value` 0 + `est_value_unknown: true`; doctrine flags ride
  along as evidence; `approval_status` PENDING.
- **Boundary guard (Task 4).** Scope comment at the top of
  `decision_engine.py` stating the historical-aggregator-only scope line,
  plus a guard test proving no import of, and no reference to, the two
  out-of-scope systems anywhere in the build (only the scope comment and
  the guard test itself name them). Guard test passes.
- **Learning-loop audit (Task 5).** `LEARNING_LOOP_AUDIT.md`: read-back is
  wired and proven with synthetic outcomes (see below); zero real outcomes
  exist, so it is production-unproven. No realised outcomes invented.

## End-to-end run evidence (clean-state reproduction, temp copy)

- Intake: `3 new, 0 unchanged(skipped), 0 unparsed. Index: 3 items`
- Scanner: `scanned=1 new=1 ... Index: 1 files, unparsed 0, duplicates 0`
- Engine run 1: `total_considered: 29` (15 module items + 14 context items),
  `top_actions: 10`
- Engine run 2: intake `0 new, 3 unchanged(skipped)`; scanner
  `scanned=1 new=0 skipped_unchanged=1`; brief still 29 items, same 14
  context items — dedup clean. Outcomes log: 20 lines after 2 runs, prior
  lines byte-identical, all `actual_roi: null`.
- The same numbers were produced in the live workspace before the temp-copy
  reproduction.

## Feed round-trip evidence

- In-process (`tests/feed_roundtrip_test.py`, feed-dash venv): **2 passed**.
  10 top actions schema-validated, POSTed to a throwaway copy of the feed
  service, read back via `GET /api/feed/opportunities`: confidence ==
  quant/100 for all 10; `roi_estimate` preserved exactly (7 null, 3 numeric:
  1700.0, 127000.0, 7500.0); `est_value_unknown` true; re-POST idempotent;
  unauthenticated POST rejected (401).
- Live HTTP: the writer posted the same 10 records to a local uvicorn copy
  of the feed service (port 8123, throwaway data dir) and the GET read-back
  matched on all 10. Server stopped, temp data removed. The feed-dash build
  and its data were not modified.

## Learning-loop evidence

- Real log: 20 rows, all `recommended`, 0 closed. `learning.py recalibrate`
  correctly refuses ("Need >=3 closed outcomes ... Have 0."); no weights
  file exists; the engine scores on built-in defaults.
- Seam proven in a deleted temp copy with 3 SYNTHETIC closed rows only:
  `recalibrate` wrote `00_INDEX/quant_weights.json` (roi 0.4106, time
  0.1313, risk 0.1826, difficulty 0.1152, capital 0.1604) and a report;
  `load_weights()` read them back (TW200-style input: 81.0 learned vs 81.1
  defaults). Synthetic rows never touched the real log.
- Simulator selftest: **PASSED** (sympy 1.12 present; 3 sample scenarios;
  `items()` → 3 ranked recommendations).

## Files changed / added (this workspace only)

- Copied from recovered (never modified there): `decision_engine.py`,
  `context_intake.py`, `source_scanner.py`, `pineapple_os.py`,
  `_lib/pineapple_quant.py`, `_lib/doctrine.py`,
  `06_DECISION/learning.py`, `06_DECISION/simulator/`.
- **Deviation from the brief's copy list, documented:** the brief names
  seven files but omits their transitive imports — without
  `_lib/pineapple_context.py` and `_lib/pineapple_intel.py` the intake and
  scanner cannot import at all, and without the `04_INTELLIGENCE/` modules
  the engine produces zero module items (contradicting the brief's own
  verified state of 15 module items and its acceptance "brief includes
  module + context items"). Those files were copied as well, unmodified
  except as noted below. No other recovered files were copied.
- Modified copies (build work, originals untouched):
  - `decision_engine.py` — scope comment at top; stale-context rule
    (`apply_staleness`, 30 days / −10); learned-weights flag
    (`build_brief(use_learned_weights=...)`, CLI `--no-learned-weights`).
  - `06_DECISION/simulator/data/sample_scenarios.json` — **recreated**: the
    file is referenced by the simulator README but was absent from the
    recovered clone, so the simulator's selftest failed and `run_all()` /
    `items()` returned nothing. Recreated as clearly-marked SAMPLE data
    using exactly the parameter keys `simulator.py` requires; no values are
    real owner data.
- New files: `00_INBOX/sample_*.txt` (3 fixtures),
  `sample_sources/Downloads/sample_listing_note.txt`,
  `00_INDEX/source_config.json`, `.pineapple_root`,
  `tests/test_decision_engine.py`, `tests/feed_roundtrip_test.py`,
  `writers/decision_brief_writer.py`, `scripts/run_pipeline.sh`,
  `STALE_CONTEXT_RULE.md`, `FEED_MAPPING.md`, `LEARNING_LOOP_AUDIT.md`,
  this report.
- Runtime outputs (generated, not source): `decision_brief.json`,
  `00_INDEX/context_index.json`, `00_INDEX/scan_index.json`,
  `00_INDEX/context_digest*.json`, `00_INDEX/source_registry.json`,
  `00_INDEX/scan_log.jsonl`, `00_INDEX/unparsed_report.json`,
  `00_INDEX/duplicate_report.json`, `00_PROCESSED/**`,
  `06_DECISION/outcomes_log.jsonl` (20 rows), plus module-generated
  `04_INTELLIGENCE/*/input/*.json` (sample inputs the modules create on
  first run) and `04_INTELLIGENCE/*/output/opportunities.json` — all inside
  this isolated workspace; the recovered originals hold none of these.

## Gaps / surprises found (recovered code, not changed)

- The simulator's sample data file was missing (fixed by recreating it as
  SAMPLE — see above). `simulator.py` also needs sympy (non-stdlib) and
  carries a hardcoded Windows absolute `PROCESSED` path, so `--write` is
  not usable on this Linux runtime.
- `pineapple_quant._root()` falls back to the `_lib/` folder when no
  `.pineapple_root` marker is found — weights would then silently land in
  `_lib/00_INDEX/` instead of the workspace `00_INDEX/`. This build ships
  the marker; any future copy must carry it.
- `learning.py record` rewrites the whole outcomes log rather than
  appending (pre-existing; the append-only contract covers the engine's
  logging). Simulator `items()` is not wired into the brief (see audit).
- No `00_INDEX/doctrine.json` exists in the recovered clone, so doctrine
  rules default to empty and no penalties apply in the live run. Penalties
  are covered by tests with explicit doctrine dicts; seeding real doctrine
  rules is a separate owner decision, not part of this build.
- Module `roi_estimate` values are module-defined and unit-mixed (some are
  dollar-ish: 1700.0, 127000.0, 7500.0) — the feed writer carries them raw
  rather than normalising, per the mapping doc.

## What failed

Nothing in the build failed. Two test failures occurred during development
and were fixed in the tests, not by weakening them: a temp-workspace harness
leak (stale cached module pointing at a deleted temp dir; fixed by evicting
cached modules per test) and a round-trip assertion that wrongly assumed all
top actions have null `roi_estimate` (fixed to compare per-action exact
values). Final state: 21 + 2 tests passing.
