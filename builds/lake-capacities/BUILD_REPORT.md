# BUILD REPORT — Lake Capacities v1
Built 2026-11-17/18 (America/Chicago) in `~/workspace/pineapple/builds/lake-capacities/`.
Python stdlib only, public keyless data, nothing scheduled or deployed.

## What genuinely runs
- **TWDB client — WIRED.** Structured paths documented by TWDB itself on
  /reservoirs/download and verified live: `reservoirs/recent-conditions.json`
  (123 reservoirs: current storage, conservation storage/capacity, pool
  elevation, % full, dated timestamp) and per-reservoir
  `reservoirs/individual/<slug>-30day.csv` daily history for all 10 slugs.
- **USGS NWIS client — WIRED for 8 of 10 lakes.** IV + 30-day DV JSON for
  62614/62615/00054. Storage+elevation at Toledo Bend, Medina, Choke Canyon,
  Corpus Christi; elevation-only at Travis, Buchanan, Canyon, Sam Rayburn
  (their storage comes from TWDB).
- **Normalization, trend, cross-source confidence, Markdown renderer,
  items() dicts** — all working; brief renders offline from cache
  (`scripts/build_brief.py --offline` verified).

## Live smoke — Falcon + Amistad (2026-11-18 05:09 UTC pull; data dated 2026-11-17)
- **Falcon International Reservoir — 22.8% of conservation capacity
  (storage 355,620 ac-ft, TWDB, retrieved 2026-11-18 05:09 UTC), rising
  over 30 days (+33,330 ac-ft).**
  Hand-check: 355,620 / 1,562,367 = 22.76% → 22.8%, and TWDB's own
  published percent_full is 22.8. Both inputs are in the cached raw
  `cache/twdb_recent_conditions.json`. Confidence 0.6 (single source —
  see USGS note below). Elevation 262.25 ft; conservation pool 301.2 ft.
- **Amistad International Reservoir — 53.1% of conservation capacity
  (storage 963,219 ac-ft, TWDB, retrieved 2026-11-18 05:09 UTC), rising
  over 30 days (+148,673 ac-ft).**
  Hand-check: 963,219 / 1,813,408 = 53.12% → 53.1% = TWDB published.
  Confidence 0.6 (single source). Elevation 1,069.97 ft; pool 1,117.0 ft.
- Full smoke output: `evidence/live_smoke_output.txt` (SMOKE PASS);
  records: `output/live_smoke_records.json`.

## Registry coverage (10/10 lakes have a computed % + trend)
| Lake | TWDB | USGS | % (2026-11-17) | Trend 30d | Confidence |
|---|---|---|---|---|---|
| Falcon International Reservoir | WIRED (slug falcon) | NOT WIRED — site 08461200 exists, IV/DV return zero series | 22.8 | rising +33,330 | 0.6 |
| Amistad International Reservoir | WIRED (amistad) | NOT WIRED — site USIBW 08450700 exists, IV/DV zero series even with agencyCd | 53.1 | rising +148,673 | 0.6 |
| Lake Travis | WIRED (travis) | WIRED 08154500, elevation only | 100.0 | rising +63,041 | 0.85 |
| Lake Buchanan | WIRED (buchanan) | WIRED 08148000, elevation only | 96.2 | steady +2,877 | 0.85 |
| Canyon Lake | WIRED (canyon) | WIRED 08167700, elevation only | 97.0 | steady +484 | 0.85 |
| Medina Lake | WIRED (medina) | WIRED 08179500, storage+elevation | 27.6 | falling −1,726 | 0.85 |
| Choke Canyon Reservoir | WIRED (choke-canyon) | WIRED 08206900, storage+elevation | 21.1 | steady −2,133 | 0.85 |
| Lake Corpus Christi | WIRED (corpus-christi) | WIRED 08210500, storage+elevation | 82.5 | rising +3,842 | 0.85 |
| Toledo Bend Reservoir | WIRED (toledo-bend) | WIRED 08025350, storage+elevation | 83.7 | falling −26,616 | 0.85 |
| Sam Rayburn Reservoir | WIRED (sam-rayburn) | WIRED 08039300, elevation only | 59.9 | falling −71,489 | 0.85 |

Rendered brief: `output/LAKE_BRIEF.md`; all records: `output/records.json`.

## Tests
- Offline fixture suite: **22 tests, all passing** (`python3 -m unittest
  discover -s tests`) — USGS/TWDB parsing, % math incl. null cases
  (no capacity, no storage, undated), trend boundaries (steady at exactly
  ±0.5% of capacity; rising/falling just outside; unknown on short/missing
  series), cross-source disagreement (both values kept, confidence 0.6),
  two-source agreement (0.85), elevation-only → "% unknown (elevation
  only)", renderer completeness, items() shape.
- Live smoke is a separate script (not part of the offline suite): PASS.

## Stubs / NOT WIRED, with reasons
- **USGS data for Falcon & Amistad: NOT WIRED.** Both reservoir sites
  exist in the NWIS site file (Falcon USGS-08461200; Amistad
  USIBW-08450700), but NWIS IV/DV return zero time series for
  62614/62615/00054 — verified repeatedly, including with agencyCd=USIBW
  for Amistad. These are IBWC-operated reservoirs; TWDB carries them
  from IBWC data (Falcon page: Data Source IBWC:08-4612.00), so they are
  fully served at single-source confidence 0.6. No averaging, no faking.
- **USACE: not wired** (out of v1 scope per brief; not needed — TWDB
  already aggregates USACE-operated lakes such as Sam Rayburn/Canyon).

## Endpoint surprises vs the brief
1. **TWDB has a clean structured JSON** (`recent-conditions.json`) in
   addition to the documented CSV downloads — no page scraping needed,
   and it carries conservation capacity + pool elevation per lake.
2. **Binational/shared-pool accounting:** for Falcon, Amistad (and
   Toledo Bend), TWDB's conservation_capacity/conservation_storage are
   the *Texas share* only (Falcon 58.6%, Amistad 56.2%), while `volume`
   is total storage. Percent must be computed conservation_storage ÷
   conservation_capacity — using total volume would overstate Falcon at
   ~31%. Records keep both figures plus total capacity at pool.
3. **Memory-guessed USGS ids were wrong** (Travis is 08154500, Buchanan
   08148000); live discovery via the USGS OGC monitoring-locations
   service corrected them. Travis/Buchanan publish no USGS storage
   series at all (DV 00054 empty) — elevation-only cross-check.
4. **Datum wrinkle:** Travis USGS elevation is 62615/NAVD88 and reads
   0.58 ft above TWDB's figure — inside the 1.0 ft agreement tolerance,
   recorded in `sources_detail`, never averaged.
5. Lake Travis reads exactly 100.0% because TWDB caps conservation
   storage at capacity while total volume (1,127,889 ac-ft) sits above
   it (flood pool) — the record keeps both numbers visible.
