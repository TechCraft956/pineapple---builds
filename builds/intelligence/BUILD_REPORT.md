# BUILD REPORT — 04_INTELLIGENCE modules group (BUILD-20261117-010)

Built by Everest (subagent) 2026-11-17, ~18:40–19:10 CT. Workspace:
`~/workspace/pineapple/builds/intelligence/`. GPT's review
(RESULT-BUILD-20261117-010-GPT, BLOCKED_SOURCE_UNAVAILABLE = GPT-side access
limit, not a brief defect) was already folded into the brief; its acceptance
gate was adopted as the build cross-check and every gate item is verified
below. No writes were made to the AI Bridge sheet or PIPELINE_STATE.md
(parent's job).

## What was built

### Task 1 — Missing sample datasets restored (4 files, all SAMPLE, fabricated)
- `cad_appraisal/data/sample_parcels.json` — 12 parcels (Hidalgo ×7, Cameron ×5),
  all four flags covered: under_assessed ×4, high_equity ×4, long_owned ×5,
  estate_or_trust ×4, plus raw_land ×1. Two parcels deliberately carry no flag
  (incl. P-44-0820-0159-0201-00: market $199,999 — $1 under the high-equity
  threshold — and 24 years owned — 1 year under long-owned), proving `items()`
  filters. Every owner contains "SAMPLE"; lat/lon on every parcel.
- `county_records/data/sample_events.json` — 15 events covering all 5 event
  types and all 4 core counties + Brooks (neighbor). Dates are the next
  first-Tuesday sales (2026-12-01, 2027-01-05) and December 2026 meetings.
- `local_econ/data/sample_signals.json` — 12 signals covering all 6 kinds and
  McAllen / Edinburg / Brownsville / Harlingen; every record carries its live
  portal in `real_source`; deadlines are future-dated so scores are not
  stale-penalized.
- `osint/data/sample_entities.json` — 6 clean entities (incl. "Valley Sun
  Produce LLC (SAMPLE)" for the selftest query filter) + 1 deliberately dirty
  record under a separate top-level `rejected_examples` key (see Surprises).

### Task 2 — `_lib` import portability defect fixed (both layers)
**Choice: seed the marker + copy `_lib` AND add a workspace-relative fallback
in the three build copies.** Why both: the marker approach keeps the three
modules byte-identical to the originals and matches the design intent (the
workspace IS a self-contained OS root), while the fallback hardens the modules
so they also import when no marker exists anywhere in the parent tree — which
is exactly what the brief's `_boot()` regression test demands. The fallback is
in the build copies only; recovered originals are untouched.
- `.pineapple_root` seeded at the workspace root; `_lib/pineapple_intel.py`
  copied (its only imports are stdlib: json/sys/dataclasses/datetime/pathlib/
  typing — no true dependencies beyond the file itself).
- `_boot()` in the build copies of `economic_checker`, `political_tracker`,
  `recon_engine` now also accepts any ancestor holding
  `_lib/pineapple_intel.py`; the marker still wins when present.
- **Recon dedup (build hardening, not in the original):** the original
  `recon_engine.scan()` scored every row, so a duplicated lead counted twice.
  The brief's Task 3 requires a dedup test, so the build copy now dedupes by
  (source, normalized title), keeping the freshest copy (tie-break: highest
  est_value). Pure function `_dedupe_leads()`, no I/O. Documented here, not
  silently changed.
- First-run sample inputs created on run: `economic_checker/input/indicators.json`,
  `political_tracker/input/agenda_items.json`, `recon_engine/input/leads.json`.

### Task 3 — Tests: 57/57 pass (`pytest tests/ -q`, socket blocked module-wide)
- All 8 `--selftest` modules exit 0; the 3 `IntelModule` modules run exit 0
  with first-run inputs + `output/opportunities.json` created.
- cad_appraisal boundaries: under_assessed fires at exactly 8.0% (market
  $184,000 on $200,000 comps) and not at 7.9%; high_equity fires at $200,000
  and not at $199,999; long_owned fires at 25 years and not at 24.
  Equity math vs hand-computed fixtures (comp $200,000, under_assessed 15.0%,
  land_share 23.5%) and a land-only parcel (comp None, est = market).
- OSINT ethics gate: the `rejected_examples` record is rejected; each banned
  key fragment (ssn, dob, date_of_birth, drivers_license, home_address,
  credit_card, ein, tax_id, personal_email, cell) and each banned source
  (facebook, spokeo, "scraped") is rejected individually; a clean record
  passes; no banned key appears anywhere in the loaded entities.
- county_records: all 5 event types + 4 core counties present; items sorted
  by score desc; agenda events have `est_value None`; murky-owner risk
  escalation (MED → HIGH) verified.
- local_econ: three-lens weights verified arithmetically
  (building_permit 71.0 → contractor 67.5 / realestate 46.2 / marketplace 24.9);
  passed-deadline penalty + risk bump verified.
- recon_engine dedup: freshest copy kept, est_value tie-break, and
  end-to-end dedup through `scan()` on a synthetic input file.
- `_boot()` regression: all three modules import AND `recon_engine` scans
  (5 opps) in a marker-free temp tree via the fallback; negative control
  proves the test is real — the ORIGINAL modules fail to import with
  `ModuleNotFoundError: pineapple_intel` when neither marker nor `_lib` is present.
- Feed writer mapping: 111 records validate against the feed opportunity
  schema; ids unique and stable across runs; lat/lon present where the module
  carries it.

### Task 4 — Feed writers: 111/111 round-trip
`writers/intelligence_writer.py` maps every module's `items()` (or `scan()`
Opportunities for the three IntelModule ones) to Opportunity Engine records
(type `other`, approval PENDING, evidence `estimate`). Every record carries
`data_status: sample` + its module warning in `provenance` and `risk_notes`,
lat/lon in provenance where available, and the real-source portal URL.
Per-module counts: cad_appraisal 10, code_violations 15, county_records 15,
delinquent_tax 14, local_econ 12, osint 6, preforeclosure 12,
utility_shutoffs 12, economic_checker 6, political_tracker 4, recon_engine 5.
Verified against a LOCAL copy of the feed service (port 8102, scratch data
dir, test token — never the original, never deployed): 111/111 posted and
read back unchanged in meaning; re-post → 111 duplicates, 0 conflicts
(idempotent); unauthenticated POST → 401. Log: `BUILD_LOG_feed_roundtrip.txt`.
Service process terminated after the run; nothing deployed.

### Task 5 — `LIVE_SOURCE_MAP.md`
Per-module portals with verified-vs-walled verdicts, reusing GEOINT's
evidence (Starr/Willacy CAD REST verified live, FEMA NFHL layer 28, TxGIO
StratMap identify; Hidalgo/Cameron CAD walled with documented fallbacks).
~45 remaining portals listed as UNVERIFIED. **No live data fetched, no walled
source re-probed.**

## Acceptance evidence
- All eleven modules' `--selftest` (or equivalent run) exit 0 on restored
  sample data; the four already-passing modules still pass with identical
  tops (code_violations 15 / [95.0] Pharr commercial blight; delinquent_tax
  14 / [100] ABC Holdings LLC; preforeclosure 12 / [77.4] vacant LLC-owned;
  utility_shutoffs 12 / [66.0] Brownsville water distress).
- The three `_lib`-dependent modules import and run in the isolated workspace;
  the regression test proves the fix (including the negative control).
- Full test suite passes offline (57/57), including ethics-gate and
  scoring-boundary tests. No network in tests (socket blocked).
- Feed round-trips pass for every module's items; sample provenance and
  warnings survive on every record.
- `LIVE_SOURCE_MAP.md` written with verified-vs-walled verdicts per portal;
  no live data fetched, no walled source re-probed.
- No real person's data used; no PII; no seller or third-party contact;
  recovered originals untouched (see below).

## What failed / caveats / surprises
- **OSINT dirty record placement:** the dirty record cannot live in the
  `entities` list — `_load_entities()` runs the ethics gate on every record
  and raises, which would break the selftest. It lives under a separate
  top-level `rejected_examples` key that the loader never reads; tests load
  it explicitly and assert rejection. The file documents this.
- **Recon dedup was missing in the original:** the brief's Task 3 requires a
  dedup test but the original code has no dedup. Implemented in the build
  copy (see Task 2) rather than weakening the test.
- **Scoring quirks (original behavior, not changed):** `economic_checker`
  scores favorable indicators as weight + magnitude×100, so
  construction_permits scores only 43.3 despite moving the right way, while
  manufacturing_announcements caps at 100. `political_tracker` sample items
  score 25–46 ("C" grades) because each hits only 1–2 keywords — expected
  for keyword scoring, not a defect. `county_records`' top lead is a
  commissioners-agenda signal (82.2), outranking dollar events, because agenda
  signal strength + urgency outweighs the equity-spread component.
- **Recovered clone is not a git repo** (`git status` → "not a git repository"),
  so originality is verified by md5, not git diff: all 12 original files
  (11 modules + `_lib/pineapple_intel.py`) re-checked after the build and
  byte-identical to the pre-build snapshot in `.original_md5.txt`.
- The `feed-service-copy/` directory in this workspace is a scratch copy of
  the feed service used only for the round-trip verification; the original
  `builds/feed-dash/feed-service/` was not modified.

## Files
- `cad_appraisal/data/sample_parcels.json`, `county_records/data/sample_events.json`,
  `local_econ/data/sample_signals.json`, `osint/data/sample_entities.json` (new sample data)
- `economic_checker/economic_checker.py`, `political_tracker/political_tracker.py`,
  `recon_engine/recon_engine.py` (build copies: `_boot()` fallback; recon also dedup)
- `_lib/pineapple_intel.py` (copy), `.pineapple_root` (seeded marker)
- `tests/test_intelligence.py` (57 tests), `writers/intelligence_writer.py`,
  `verify_feed_roundtrip.py`, `BUILD_LOG_feed_roundtrip.txt`
- `LIVE_SOURCE_MAP.md`, `BUILD_REPORT.md` (this file)
- `00_PROCESSED/` (module selftest outputs, inside the workspace)
