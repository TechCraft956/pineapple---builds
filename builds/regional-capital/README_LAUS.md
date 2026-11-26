# Sensor #101 — BLS Local Area Unemployment Statistics (LAUS), Starr County

Read-only collector for monthly unemployment / labor-force estimates
for Starr County, TX (FIPS 48427), the McAllen-Edinburg-Mission MSA
(CBSA 32580), and Texas statewide context. $0 cost, no signup, no
API key, no account. Added in the Wave 4 deficit sweep (2026-11-26):
Wave 4's #51 (QCEW + WARN) covers jobs and layoffs, but the
inventory had **no county unemployment-rate sensor at all** — the
most basic labor-market gauge was missing.

## What it does

`laus.py` queries the BLS public API v1 (keyless) for four measures —
unemployment rate (%), unemployed, employed, civilian labor force —
for Starr County, the McAllen MSA, and Texas, and emits one
observation per series-month, labeled VERIFIED / REPORTED with source
URL + UTC retrieval timestamp.

## Live evidence (2026-11-26, `evidence/laus_run_20261126.json`)

- **424 observations (412 VERIFIED, 12 REPORTED).**
- **Starr County unemployment rate: 8.3% (Sep 2026, preliminary)** —
  down from 10.8% in Jan 2024; labor force 25,335.
- **McAllen MSA: 5.6% (Sep 2026). Texas: 4.3% (Oct 2026).**
- Starr runs ~4 points above the state rate across the whole window.

## How to run

```bash
cd builds/regional-capital
python3 laus.py --out evidence/laus_run_<date>.json
python3 laus.py --include-rgv --out evidence/laus_run_<date>_rgv.json
python3 laus.py --start-year 2024 --end-year 2026 --out evidence/laus_run_<date>.json
```

- Default window is 2025–2026 (the API returns the 3 most recent
  years regardless — see caveats).
- `--include-rgv` adds Hidalgo / Cameron / Willacy counties (24
  queries/run, at the keyless v1 daily cap of 25 — run at most
  once/day in that mode).
- Exit code 0 whenever a document was written, even if a series
  failed (per-series status is in `fetch_status`).

## Tests

```bash
cd builds/regional-capital
python3 -m unittest tests.test_laus -v
```

10 tests, all passing (2026-11-26): series-ID construction (county /
MSA / state formats), payload parsing (values, preliminary flag,
missing value → REPORTED not zero, unknown series ignored), fetch
shape (API error recorded, fake live payload). Tests are offline
fixtures — no network calls.

## Caveats

- **One POST per series.** Multi-series v1 requests answer HTTP 503
  / BLS's "website is busy" page from this environment, while
  single-series requests succeed (verified 2026-11-26). Twelve
  queries per run is inside the keyless v1 limit of 25/day at a
  monthly cadence.
- **api.bls.gov answers 503 to urllib's default User-Agent.** The
  collector sends an identifying `Pineapple-Sensor-LAUS/1.0` UA.
- **The API returns the 3 most recent years regardless of the
  requested start year** (2024–2026 came back for a 2025–2026
  request). The extra year is kept and labeled, not trimmed.
- **County/MSA series are NOT seasonally adjusted.** Compare against
  the NSA national rate, not the headline seasonally adjusted rate.
- **Oct 2025 gap:** the API returned the Oct 2025 rows for Starr
  County and the MSA with empty values (12 REPORTED observations).
  Texas Oct 2025 has values. Recorded as-is; cause unknown, not
  filled in.
- **M13 rows are annual averages**, included with the monthly rows
  and labeled by their `M13` period.
