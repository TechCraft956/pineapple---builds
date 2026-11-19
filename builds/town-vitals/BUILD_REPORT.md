# BUILD REPORT — Town Vitals v1

Built 2026-11-17 (retrieved timestamps in evidence are UTC,
2026-11-18T05:08Z = 2026-11-17 23:08 CST). Isolated workspace:
`~/workspace/pineapple/builds/town-vitals/`. Python stdlib only.
Nothing outside this directory was written; the AI Bridge sheet and
PIPELINE_STATE.md were not touched.

## What genuinely runs

- Offline fixture test suite: **22 tests, all passing, no network**
  (`python3 -m unittest discover -s tests` → OK).
- Live smoke (`python3 live_smoke.py`): real ACS figures for Roma city,
  TX and McAllen, TX — briefs, records, and items in `evidence/`, raw
  API responses (18 table responses) in `cache/live_raw_responses.json`,
  Gazetteer zip in `cache/`. Roma population/income hand-checked against
  the cached raw B01003/B19013 responses: **match** (11,545 / $24,579).

## Vintage + variable verification

- Latest vintage: **ACS 5-year 2024**; prior vintage for growth:
  **ACS 5-year 2019** (5 years prior, both named on every record).
- All **16 variable ids** verified against the API's own variables
  endpoint for **both** 2024 and 2019 at smoke time (any missing id
  raises `VariableVerificationError`):
  B01003_001E (population), B19013_001E (median HH income),
  B01002_001E (median age), B17001_001E + B17001_002E (poverty),
  B23025_003E + B23025_005E (unemployment = unemployed / civilian labor
  force), B25003_001E + B25003_002E (owner-occupied), B25077_001E
  (median home value), B03002_001E/003E/004E/012E/013E/014E
  (composition). Composition definitions + every rate formula are
  stored on each record under `formulas`.
- Resolver verified live: Gazetteer loaded 1,863 Texas places;
  Roma → FIPS **4863020**, McAllen → FIPS **4845384**.

## Live smoke figures (ACS 2024, retrieved 2026-11-18T05:08Z)

### Roma city, Texas (FIPS 4863020)
- Population **11,545** · Median HH income **$24,579** · Median age **28.0**
- Poverty **37.1%** · Unemployment **12.4%** · Owner-occupied **55.2%**
- Median home value **$94,400**
- Composition: Hispanic/Latino 96.6% · White alone 30.7% · Black alone
  0.0% (raw B03002 counts are genuinely 0) · Other/two+ 69.3%
- Growth: 11,397 (ACS 2019) → 11,545 (ACS 2024) = **+1.3%**

### McAllen city, Texas (FIPS 4845384)
- Population **145,385** · Median HH income **$61,579** · Median age **33.5**
- Poverty **20.0%** · Unemployment **6.0%** · Owner-occupied **59.5%**
- Median home value **$190,400**
- Composition: Hispanic/Latino 87.0% · White alone 36.0% · Black alone
  0.9% · Other/two+ 63.1%
- Growth: 141,968 (ACS 2019) → 145,385 (ACS 2024) = **+2.4%**

No figure was suppressed for either town, so no "unknown" appears in
the live briefs; the unknown path is covered by the offline sentinel
fixture (median home value `-666666666` → null → "unknown").

## Tests (22, offline)

Sentinel parsing (7 sentinel/missing forms + in-record sentinel),
variable verification fail-loud + pass, missing-key redirect detection,
rate math (poverty/unemployment/owner-occupied), composition math,
formulas stored, resolver exact + suffix-insensitive match, resolver
ambiguity (2 candidates, no silent pick), resolver not-found, growth
gating (two vintages / single vintage / missing prior population),
renderer completeness (every non-null figure appears; null renders
"unknown"), growth line naming both vintages, provenance + planning-
signal + NOT WIRED footer, hooks NOT WIRED markers, items() shape.

## What differed from the brief

1. **The Census API is no longer keyless for data.** The brief states
   the ACS API is "free, no key". Free: yes. Keyless: no longer — as of
   **2026-05-12** all `api.census.gov` data queries require a free API
   key; a keyless query 302-redirects to `missing_key.html` (verified
   live at build time; Census Data API User Guide, May 21 2026, states
   "An API key must be used with all data queries"). Handling:
   - The API client is built exactly per the brief and raises
     `CensusKeyRequiredError` loudly on the redirect (never zeros). It
     accepts a free key via `CENSUS_API_KEY` env (redacted from all
     stored provenance/cache) — obtaining one is a 2-minute owner step
     at https://api.census.gov/data/key_signup.html, not done here
     because the task constraints say no keys/accounts.
   - The live smoke instead uses the Census Bureau's own
     **data.census.gov table-access endpoint** — keyless, public, and
     serving the *identical* ACS tables/variable ids (each response's
     `dataAPIURI` names the underlying api.census.gov query). Same
     dataset, same vintages, full per-table query URLs in provenance.
   - The variables/metadata endpoint still answered keyless, so
     variable-id verification runs exactly as the brief specifies.
2. **Place list source.** The API's place list is behind the same key
   requirement, so live resolution uses the Census Bureau **Gazetteer**
   place file (official, keyless) through the same resolver code; the
   API place-list loader is implemented and used automatically when a
   key is present. Resolver semantics (state-generic, ambiguity →
   candidates) are identical for both sources.
3. **Composition definitions** (brief names the four shares but not the
   exact B03002 cells): white_alone = white alone of any ethnicity
   (B03002_003E + _013E), black_alone likewise (_004E + _014E),
   other = total − white_alone − black_alone. Hispanic/Latino
   (B03002_012E) is an ethnicity and overlaps the race shares; the
   briefs carry that caveat line.

## Stubs / not wired (by design)

- `hooks.py`: `town_hall_items` and `economy_signals` return explicit
  `{"status": "NOT WIRED", "items": []}` markers; both print as
  NOT WIRED in every brief's footer. No scraping in v1.
- No scheduling, no feed wiring — `to_item()` only produces the
  items()-style dict (saved per town in `evidence/*_item.json`).

## Files written

- `src/town_vitals/`: `__init__.py`, `census_client.py`, `table_api.py`,
  `resolver.py`, `vitals.py`, `renderer.py`, `hooks.py`
- `tests/test_town_vitals.py`, `fixtures/fixture_values.json`,
  `fixtures/fixture_places.json`
- `live_smoke.py`, `README.md`, `BUILD_REPORT.md`
- `evidence/`: `Roma_city_brief.md`, `Roma_city_record.json`,
  `Roma_city_item.json`, `McAllen_city_brief.md`,
  `McAllen_city_record.json`, `McAllen_city_item.json`,
  `live_smoke_summary.json`
- `cache/`: `live_raw_responses.json`, `2024_Gaz_place_national.zip`
