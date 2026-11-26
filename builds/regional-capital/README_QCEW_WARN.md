# Sensor #51 — Hiring & labor market: BLS QCEW + TWC WARN (Starr County / RGV)

Read-only collector for county employment and wages (BLS Quarterly
Census of Employment and Wages) and layoff/closure notices (Texas
Workforce Commission WARN), covering Starr County, TX (FIPS 48427)
and the McAllen-Edinburg-Mission MSA, with Hidalgo, Cameron, and
Willacy Counties in the WARN scope.

## What it does

`qcew_warn.py` runs two legs and emits one JSON observation per
record, labeled **VERIFIED / REPORTED / UNKNOWN**:

- **VERIFIED** — all key fields present in the source record (QCEW:
  month-3 employment + average weekly wage + establishments, with an
  empty disclosure code; WARN: employer, county, notice date and
  layoff number all present).
- **REPORTED** — record present but a key field is missing or the
  cell is disclosure-suppressed. The figure stays `null`, never
  zero-filled — including BLS's placeholder 0s (see below).
- **UNKNOWN** — record present but its geography cannot be keyed
  (WARN row with a blank county).

Every observation records its source URL and UTC retrieval timestamp.

### Leg 1 — QCEW (BLS)

Keyless CSV slices, no signup, $0:

    https://data.bls.gov/cew/data/api/{year}/{qtr}/area/{area}.csv

Areas: `48427` (Starr County) and `C3258` (McAllen-Edinburg-Mission
MSA — the QCEW area code for CBSA 32580). The collector probes
recent quarters newest-first and keeps the newest `--quarters`
(default 5) that return data. QCEW lags roughly two quarters.

Per quarter, per area, it emits the all-industry total, the private
total, federal/state/local government totals, and the top 5 private
2-digit NAICS sectors by month-3 employment among non-suppressed
rows. QCEW suppresses small cells for confidentiality
(`disclosure_code` non-empty blanks the figures): suppressed sectors
simply do not appear, and suppressed totals are emitted with `null`
figures.

### Leg 2 — WARN (TWC)

No signup, $0. The WARN landing page:

    https://www.twc.texas.gov/data-reports/warn-notice

links one Excel workbook per year
(`warn-act-listings-{YYYY}-twc.xlsx`). The collector downloads the
workbooks for `--warn-years` (default: current year + prior year)
and parses them with stdlib `zipfile` + `xml.etree` (no openpyxl).
Columns: NOTICE_DATE, JOB_SITE_NAME, COUNTY_NAME, WDA_NAME,
TOTAL_LAYOFF_NUMBER, LayOff_Date, WFDD_RECEIVED_DATE, CITY_NAME.
Dates are Excel serial numbers, converted to ISO dates. Only
notices in Starr, Hidalgo, Cameron, or Willacy County are emitted
as observations; statewide notice/worker totals are kept in the
summary for context. **Zero Starr County notices in a year is a real
finding**, reported as such — not a fetch failure.

## How to run

```bash
cd builds/regional-capital
python3 qcew_warn.py --out evidence/qcew_warn_run_20261126.json
```

Options:

| Flag | Effect |
|---|---|
| `--quarters N` | Trailing QCEW quarters to collect (default: 5). |
| `--warn-years YYYY ...` | WARN workbook years (default: current + prior). |
| `--out <path>` | Write result JSON (default: stdout). |

Stdlib Python only; no dependencies. A run fetches ~12 small CSVs
(~100 KB each) + 2 small workbooks and takes ~10 seconds.

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

21 tests for this sensor, all passing (2026-11-26); full suite 155
tests green. Tests are offline fixtures — no network calls — including
a hand-built in-memory WARN workbook and a QCEW CSV fixture.

## Suggested activation cadence

**Monthly.** QCEW publishes quarterly (a monthly run picks up a new
quarter within a month of release and costs almost nothing), while
the WARN workbooks are updated through the year as notices arrive —
a monthly pull catches new layoff notices promptly. Each run is a
fresh snapshot; compare WARN `(employer, notice_date)` pairs and
QCEW `period` sets against the previous run to surface what's new.

## Live evidence (2026-11-26T19:44:49Z)

Full run: [evidence/qcew_warn_run_20261126.json](evidence/qcew_warn_run_20261126.json) —
**112 observations (81 QCEW, 31 WARN), 104 VERIFIED / 8 REPORTED /
0 UNKNOWN.**

### QCEW — Starr County, latest quarter 2026Q1

| Period | Employment (Mar) | Avg weekly wage | Establishments |
|---|---|---|---|
| 2025Q1 | 15,137 | $772 | 668 |
| 2025Q2 | 14,729 | $762 | 669 |
| 2025Q3 | 14,823 | $834 | 675 |
| 2025Q4 | 15,204 | $852 | 672 |
| **2026Q1** | **15,613** | **$796** | **675** |

2026Q1 split: private 9,310 jobs @ $578/wk (604 establishments);
federal 911 @ $2,795; state 338 @ $1,588; local government 5,054 @
$782. Total quarterly wages $161,540,063. Top private sectors
(2026Q1, non-suppressed only): Accommodation & food services
(NAICS 72) 1,170 jobs @ $349/wk; Finance & insurance (52) 269 @
$894; Construction (23) 189 @ $1,604; Professional/scientific/
technical (54) 123 @ $833; Utilities (22) 120 @ $1,646.

### QCEW — McAllen-Edinburg-Mission MSA, latest quarter 2026Q1

14,226 establishments, **297,416 jobs**, $850 avg weekly wage,
$3,283,706,555 total quarterly wages. MSA employment trend:
296,635 → 294,530 → 294,315 → 300,538 → 297,416 (2025Q1–2026Q1).

### WARN — RGV layoff notices

- **2026 workbook: 123 notices statewide, 18,772 workers.** RGV: **6
  notices, all Cameron County, 816 workers** — First Brands Group,
  Brownsville (345 + 183 + 43 across three sites, noticed 2026-03-04),
  Compass Connections, Harlingen (148), Cardone Industries, Harlingen
  (41), CPLC Texas, Los Fresnos (56). **Starr County: 0 notices.**
- **2025 workbook: 289 real notices statewide, 26,630 workers.**
  RGV: **25 notices, 1,901 workers** — Cameron 11, Hidalgo 12,
  Willacy 2. Largest: Sunny Glen Children's Home, Raymondville
  (Willacy, 424), LUKE Holdings, Donna (201), American Bar
  Association ProBAR, Harlingen (191), Southwest Key Programs,
  McAllen (128). **Starr County: 0 notices.**

## Limitations and verified quirks

- **QCEW lag:** the newest published quarter as of 2026-11-26 is
  2026Q1. 2026Q2 and 2026Q3 answer HTTP 404 (not yet released);
  the collector records the 404s in `files` and walks down to the
  newest quarter that returns data.
- **`www.bls.gov/cew` bulk ZIPs are HTTP 403 from here** (Akamai
  bot block, "Access Denied"). The `data.bls.gov` CSV-slice API
  used here answers HTTP 200. The BLS public API v1
  (`api.bls.gov`) also answers HTTP 200, but no series-ID path was
  needed once the CSV slices worked.
- **MSA area code is `C3258`, not `C32580`** (`C32580` and bare
  `32580` are both HTTP 404).
- **MSA ownership breakdowns are not published** in the area slice:
  the industry-`10` rows for federal/state/local/private carry
  placeholder 0s with disclosure code `-`. The collector emits
  those as `null` + REPORTED, never as 0. In the 2025Q3–Q4 MSA
  slices 1,573 of 1,574 rows are suppressed, so almost no MSA
  sector detail exists there; the 2026Q1 MSA slice contains only
  the all-ownership total row (2 lines). MSA detail lags the
  county file by about a quarter.
- **County detail is heavily suppressed too:** 565–589 of ~760 rows
  per Starr County file carry a disclosure code. Sector rankings
  cover only the non-suppressed private 2-digit sectors (10 of
  them in 2026Q1); small sectors are invisible by design, not by
  collector error.
- **WARN 2025 workbook row count:** the file has 754 physical sheet
  rows but only **289 real notices** — rows 291–754 are empty
  formatted ghost rows (styled cells, no values) from TWC's export
  template. The parser skips them; the statewide count is the
  real-notice count.
- **TWC page moved:** the old `/businesses/warn` path is HTTP 404.
  The live page is `/data-reports/warn-notice`; the collector
  records which year workbooks the page lists (2020–2026 as of
  2026-11-26) as REPORTED evidence.
- **WARN is notices, not outcomes:** a notice records an announced
  layoff/closure and a planned date; it does not confirm the layoff
  happened, nor does it capture sub-WARN-threshold layoffs
  (generally <100 workers / <50 if ≥33% of the workforce) or
  layoffs with no notice filed.

## Guardrails

$0 recurring cost. No signup, no API key, no spending, no account
creation, no contacting anyone. Read-only public data. No secrets or
live private data in any file.
