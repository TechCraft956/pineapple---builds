# Town Vitals v1

One-page "how is this town doing" brief per town, from US Census Bureau
American Community Survey (ACS) 5-year data. Python stdlib only
(`urllib`), public Census sources, no accounts.

## Layout

- `src/town_vitals/census_client.py` — ACS 5-year API client
  (`api.census.gov/data/<vintage>/acs/acs5`): variable map, variable-id
  verification against the API's variables endpoint, negative-sentinel
  → null parsing, raw-response caching with provenance. Supports an
  optional free key via `CENSUS_API_KEY` (see "API key change" below).
- `src/town_vitals/table_api.py` — keyless transport over the Census
  Bureau's own data.census.gov table-access endpoint: identical ACS
  tables/variable ids, used by the live smoke.
- `src/town_vitals/resolver.py` — name → state+place FIPS. State-generic
  (seed: Texas/48). Sources: the API's place list (key) or the Census
  Gazetteer place file (keyless). Ambiguity returns/raises the candidate
  list — never a silent pick.
- `src/town_vitals/vitals.py` — vitals record assembly: rates from raw
  counts with formulas stored on the record; growth only when both
  vintages' populations exist, both vintages named; `to_item()` feed
  dict (category `PLACES`, `est_value` null, confidence 0.8).
- `src/town_vitals/renderer.py` — one-page Markdown brief from a record
  alone (offline-renderable from cache). Null figures render "unknown".
- `src/town_vitals/hooks.py` — town-hall items + economy-signals hooks,
  interfaces only, each returning an explicit `NOT WIRED` marker.
  No scraping in v1.
- `tests/test_town_vitals.py` — offline fixture tests (no network).
- `live_smoke.py` — live pull for Roma city, TX + McAllen, TX (separate
  from the offline suite). Writes briefs/records to `evidence/`, raw
  responses to `cache/`.
- `fixtures/` — offline test fixtures.

## Run

```bash
python3 -m unittest discover -s tests -v   # offline suite
python3 live_smoke.py                      # live smoke (network)
```

## API key change (differs from the original brief)

Since **2026-05-12** the Census Bureau requires a free API key for all
`api.census.gov` **data** queries; a keyless query 302-redirects to
`missing_key.html` and returns no data. The client detects that
redirect and raises `CensusKeyRequiredError` rather than returning
zeros. The variables/metadata endpoint still answered keyless at build
time, so variable verification needs no key. For keyless live data the
smoke uses the Bureau's data.census.gov table-access endpoint (same ACS
tables and variable ids; each response names its underlying
api.census.gov query). To use the direct API instead, get a free key at
https://api.census.gov/data/key_signup.html and set `CENSUS_API_KEY` —
the key is never written into provenance or cache files.

## Data discipline

Unknown figures are `null` in the record and "unknown" in the brief —
never 0, never interpolated, never borrowed from county data. Every
figure traces to the query URLs + vintage + `retrieved_at_utc` stored
in the record's provenance.
