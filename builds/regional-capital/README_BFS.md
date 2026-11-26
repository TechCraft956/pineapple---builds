# Sensor #55 — Census Business Formation Statistics (BFS), Starr County

Read-only collector over the U.S. Census Bureau's Business Formation
Statistics (BFS), filtered to Starr County, TX (FIPS 48427). $0 cost,
no signup, no API key, no account.

## The key question — answered

The plan flagged this sensor **verify-or-block**: `api.census.gov`
needs a key since May 2026. Verified 2026-11-26: the BFS API endpoint
answers with a "Missing Key" page without a key. **But the bulk
downloads on census.gov are not key-gated**, so the sensor is built
on them instead — the API leg is recorded as BLOCKED-needs-owner in
every run document, never worked around.

| Leg | Status (2026-11-26) | Source |
|---|---|---|
| Annual county workbook | **VERIFIED** — 21 Starr years, 2005–2025 | `census.gov/econ/bfs/xlsx/bfs_county_apps_annual.xlsx` |
| Weekly state CSV | **VERIFIED** — latest 13 TX weeks | `census.gov/econ/bfs/csv/bfs_state_apps_weekly_nsa.csv` |
| BFS API (monthly, county) | **BLOCKED-needs-owner** — "Missing Key" page | `api.census.gov/data/timeseries/bfs` |

## What it does

`bfs.py` downloads the annual county workbook (a .xlsx, parsed with
stdlib `zipfile` + `xml.etree` — no dependency) and emits one
observation per year for Starr County (BA2005..BA2025 = business
applications, i.e. EIN requests). It also reads the weekly state CSV
and emits the most recent 13 Texas weeks (BA/HBA/WBA/CBA, NSA) as
state-level context — there is no county split at weekly frequency,
so the state leg is never presented as county data.

Optional `--include-rgv` adds Hidalgo / Cameron / Willacy as
secondary county series.

## Live evidence (2026-11-26, `evidence/bfs_run_20261126.json`)

- **Starr County: 21 years VERIFIED, 2005 → 2025.** 178 applications
  in 2005, **466 in 2025** (+213 since 2019's 253). The series rises
  almost every year after 2019 (253 → 278 → 365 → 405 → 432 → 392 →
  466).
- **Texas weekly (latest): week 43 of 2026 — 9,790 business
  applications** (2,680 high-propensity, 780 with planned wages, 510
  from corporations).

## Disclosure note

The June 2026 county release applies differentially private
geometric noise to county counts (Census DRB approval
CBDRB-FY26-0109, stated in the workbook header). County figures are
noisy estimates, not exact counts — small differences are not
meaningful. The collector repeats this note in every output document.

## How to run

```bash
cd builds/regional-capital
python3 bfs.py --out evidence/bfs_run_<date>.json
python3 bfs.py --include-rgv --out evidence/bfs_run_<date>_rgv.json
python3 bfs.py --state-weeks 26 --out evidence/bfs_run_<date>.json
```

- `--state-weeks N` — recent Texas weekly rows to include (default 13;
  0 skips the state leg).
- Exit code 0 whenever a document was written, even if a leg errored
  (leg status is in the document).

## Tests

```bash
cd builds/regional-capital
python3 -m unittest tests.test_bfs -v
```

10 tests, all passing (2026-11-26): xlsx parsing (incl. sparse rows
placed by cell reference, title rows before the header, blank county
codes skipped), county observation building (Starr-only default, RGV
secondary, unparseable value → REPORTED not zero), state weekly
filtering (TX only, most-recent-N), blocked-API leg recording,
JSON serializability. Tests are offline fixtures — no network calls.

## Caveats

- **County data is annual, ~6 months after year's end.** The 2025
  figures are the newest available; monthly county data exists only
  behind the key-gated API (owner step: free key at
  https://api.census.gov/data/key_signup.html).
- **census.gov rejects urllib's default User-Agent (HTTP 403).** The
  collector sends an identifying `Pineapple-Sensor-BFS/1.0` UA; if
  census.gov changes its bot policy, both bulk legs will record ERROR
  and the sensor degrades to the API leg (BLOCKED until a key exists).
- A business application is an EIN request, not a company formed:
  some are never used, and many businesses never apply for one in
  the same year.
