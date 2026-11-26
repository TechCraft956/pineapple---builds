# Sensor #55 — County Business Patterns (CBP), Starr County (second leg)

Read-only collector for the U.S. Census Bureau's County Business
Patterns: establishment counts, employment and payroll by county and
NAICS, for Starr County, TX (FIPS 48427). $0 cost, no signup, no API
key, no account. Added in the Wave 4 deficit sweep (2026-11-26):
#55's own definition names "BFS … and CBP", but the Wave 4 BFS
collector covered only the Business Formation Statistics bulk files.
CBP is the other half — the stock of existing businesses (BFS counts
new EIN applications; CBP counts the establishments that actually
exist, by industry).

## What it does

`cbp.py` downloads the annual CBP county ZIP for the reference year
(`cbp{YY}co.zip`, ~13 MB, ~1.1M rows, all counties), streams it, and
emits one observation per NAICS row for Starr County (216 rows in
2023): employees (mid-March), first-quarter and annual payroll
($1,000), establishments, and establishments by employment size
class. Optional `--include-rgv` adds Hidalgo / Cameron / Willacy.

## Live evidence (2026-11-26, `evidence/cbp_run_20261126.json`)

- **216 Starr County rows, all VERIFIED** (2023 reference year,
  1,100,961 rows scanned).
- **Starr total: 8,704 employees, 594 establishments, $234.8M
  annual payroll** (Q1 payroll $58.5M). 300 of the 594 establishments
  have fewer than 5 employees.
- **Top sectors by employment:** Health Care & Social Assistance
  (62----) 4,156 employees / 115 establishments; Retail Trade
  (44----) 1,728 / 129; Accommodation & Food Services (72----)
  1,059 / 61; Finance & Insurance (52----) 272 / 63; Transportation
  & Warehousing (48----) 258 / 36.

## How to run

```bash
cd builds/regional-capital
python3 cbp.py --out evidence/cbp_run_<date>.json
python3 cbp.py --include-rgv --out evidence/cbp_run_<date>_rgv.json
python3 cbp.py --year 2022 --out evidence/cbp_run_<date>_2022.json
```

- `--year` — CBP reference year (default: latest verified, 2023).
  Released annually, ~2 years after the reference year; bump the
  default when a new release is confirmed on the CBP datasets page.
- Exit code 0 whenever a document was written, even if the fetch
  failed (fetch status is in the document).

## Tests

```bash
cd builds/regional-capital
python3 -m unittest tests.test_cbp -v
```

7 tests, all passing (2026-11-26): NAICS level classification,
ZIP URL construction, total-row observation (values, noise flags,
size classes), empty employee count → REPORTED not zero, Starr-only
default filtering, RGV secondary, fetch error recorded.
Tests are offline fixtures (in-memory ZIP) — no network calls.

## Caveats

- **CBP applies noise to published values** (the `*_nf` flags).
  Values are published as-is with their flags carried in the
  observation — small differences are not meaningful.
- **census.gov rejects urllib's default User-Agent (HTTP 403).** The
  collector sends an identifying `Pineapple-Sensor-CBP/1.0` UA (same
  fix as `bfs.py`).
- **Annual data, ~2 years stale by design.** 2023 is the latest
  release; 2024 lands ~late 2026. For fresher business counts use
  the BFS leg (annual county applications through 2025).
- A business application (BFS) is an EIN request, not a company
  formed; CBP counts establishments with paid employees only
  (nonemployers are out of scope).
