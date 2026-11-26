# Sensor #82 — TX procurement & DIR contracts (Starr County / RGV)

Read-only collector over three public, keyless legs covering Texas
state procurement relevant to Starr County, TX (FIPS 48427) and the
Rio Grande Valley. Part of the 100-sensor program (Wave 4, 2026-11-26).

## What it does

`procurement.py` runs three legs and emits one JSON observation per
record, labeled **VERIFIED / REPORTED / UNKNOWN**:

- **VERIFIED** — record present in the source with its key fields
  (id + title/name + date) all present.
- **REPORTED** — record present but a key field is missing or
  unparseable. The value stays `null`, never zero-filled.
- **UNKNOWN** — reserved; no leg emits it as built (see Caveats).

Every observation records its source URL and a UTC retrieval
timestamp. Contact emails/phone numbers in the DIR datasets are
never read into an observation (see Privacy).

| Leg | Source | Dataset / URL |
|---|---|---|
| ESBD | TxSmartBuy Electronic State Business Daily | https://www.txsmartbuy.gov/esbd |
| DIR active contracts | data.texas.gov (Socrata, keyless) | `vipt-h4ye` |
| DIR FY2026 sales to Starr customers | data.texas.gov (Socrata, keyless) | `a743-wj72` |
| TxDOT current lettings | data.texas.gov (Socrata, keyless) | `qh8x-rm8r` |

Human browse UI for the DIR register: https://dir.texas.gov/contracts

## How to run

```bash
cd builds/regional-capital
python3 procurement.py --out evidence/procurement_run_20261126.json
```

Options:

| Flag | Effect |
|---|---|
| `--esbd-pages N` | Newest ESBD listing pages to scan (default 5). |
| `--dir-sample-limit N` | DIR active-contract sample rows (default 50). |
| `--max-dir-sales-rows N` | Cap on DIR FY2026 Starr sales rows (default 1000). |
| `--out <path>` | Write result JSON (default: stdout). |

Stdlib Python only; no dependencies. A run takes ~25–65 s (ESBD
pages are the slow part, ~2–10 s each).

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

22 tests in `tests/test_procurement.py`, all passing (2026-11-26);
full suite 178 tests, all green. Tests are offline fixtures — no
network calls.

## Suggested activation cadence

**Weekly.** DIR's register changes slowly, TxDOT lettings roll over
weeks, and ESBD's newest-first slice is a monitoring sample, not a
full search — a weekly run with `--esbd-pages 5` catches new
RGV/Starr postings near the top of the listing without pretending
to cover all 2,534 pages. Compare `solicitation_id` /
`contract_number` / `project_id` sets against the previous run to
surface new items.

## Live evidence (2026-11-26T19:48:38Z)

Full run output: [evidence/procurement_run_20261126.json](evidence/procurement_run_20261126.json) —
**342 observations, all VERIFIED** (287 Starr scope, 5 RGV scope).

- **ESBD:** 5 newest pages scanned, 120 rows, **5 RGV matches, 0
  Starr matches** in the slice — all five are TxDOT maintenance
  contracts: `6512-67-001_1226` Hidalgo Co limestone rock asphalt
  (due 12/2/2026), `6511-13-001_1126` Hidalgo Co sweeping/debris
  (due 11/4/2026), `6511-87-001_1126` Hidalgo Co winter weather
  material (due 11/17/2026), `6511-88-001_1126` Hidalgo Co hot mix
  (due 11/23/2026), `6512-28-001_1126` Cameron Co hot mix (due
  11/23/2026). Listing total: 2,534 pages.
- **DIR active contracts:** register size **5,214**; 50-row sample
  of most recently started contracts = **37 distinct contracts**
  (register is one row per vendor/reseller contact). Newest:
  `DIR-CPO-6269` Flood Early Warning Systems, AT&T Enterprises,
  started 2026-10-30; `DIR-CPO-6278` DBITS, Berry Dunn, started
  2026-08-03.
- **DIR FY2026 Starr-customer purchases:** **287 rows, $310,993.66
  total, all fetched** (no truncation): Starr County 183 rows
  $144,677.29; Starr County Memorial Hospital 22 rows $102,271.69;
  Starr County Sheriff 26 rows $58,715.46; Starr County Appraisal
  District 56 rows $5,329.22. Top vendors include Xerox
  (`DIR-CPO-4412`) and Cisco (`DIR-CPO-5347`).
- **TxDOT lettings:** **0 open Starr County lettings** (0 bid-item
  rows for `county='Starr'`) — a real finding, not an error.
  Context: 198 distinct projects statewide; Pharr district 3
  projects (Cameron FM 510 rehab, Hidalgo IH-2 material
  maintenance, Hidalgo SH 107 widening); Hidalgo 258 / Cameron 133
  / Willacy 0 bid-item rows.

## Caveats (honest, not silent)

- **ESBD has no reachable machine API.** The site's filter is
  JavaScript-only; its backing Suitelet
  (`services/ESBD.Service.ss`) answers HTTP 404 from this
  environment at every resolvable path (plain, `/app/services/`,
  extension paths, with touchpoint params), and `?keyword=` /
  `?agency=` query params are ignored server-side — verified live
  2026-11-26 (an agency-filtered fetch returned the same unfiltered
  newest-first listing). The collector therefore parses the
  server-rendered HTML listing and keyword-matches titles itself.
  **Coverage is partial by design:** the newest N pages only, never
  presented as a full search. ESBD observations are labeled by
  field completeness, with `match_method` / `match_term` recorded
  so a match can be audited.
- **No Starr County member agency posts on ESBD.** The agency
  dropdown (427 options) contains no Starr County entity; RGV
  members present include Cameron County (C0311), Hidalgo County
  (C1080), City of Pharr (M1083), McAllen ISD (S1080), UT Rio
  Grande Valley (746), and both regional mobility authorities.
  Starr-relevant ESBD postings would come from state agencies
  mentioning Starr in the title — none in the newest slice.
- **Keyword matching is whole-word.** A plain substring test
  false-positived on "mission" inside "Transmission" during the
  first live run; matching now uses word boundaries (regression
  test included). Residual risk: a genuine Starr/RGV place name
  spelled differently in a title (e.g. "Rio Grande" without
  "City") is missed — `match_term` shows what matched, nothing
  more is claimed.
- **The ESBD listing drifts between runs.** New postings push the
  newest-first pages down, so two runs minutes apart return
  different match sets (2 vs 4 vs 5 RGV matches across three live
  runs on 2026-11-26). Diffs between runs are expected; the
  evidence file is a timestamped snapshot, not a stable census.
- **DIR active-contract sample is register rows, not contracts.**
  One row per vendor/reseller contact, so `--dir-sample-limit 50`
  yielded 37 distinct contracts. The register total (5,214) is the
  authoritative size; the sample is a recency window only.
- **TxDOT lettings are bid line items, not projects.** The
  collector deduplicates to one observation per distinct
  controlling project id and records `_bid_item_rows`. The rolling
  window drops past lettings, so "0 Starr lettings" means none
  open now, not none ever.
- **A real bug was caught by the live runs:** the distinct-project
  count query sent an unencoded space in `$select=count(distinct
  ...)` and Socrata silently failed it, returning `null` context
  counts in the first two evidence runs. Fixed by URL-encoding the
  select expression, with a regression test asserting no raw space
  in the request URL. The final evidence run (19:48:38Z) has the
  correct values (198 statewide, 3 Pharr).
- **No BLOCKED legs in this build.** Nothing in #82 needs an owner
  step: all three legs are keyless and reachable. If ESBD or
  Socrata becomes unreachable, the leg reports `ERROR:` with the
  exact exception and the run still completes with the other legs.

## Privacy note

DIR datasets carry personal contact data (vendor and contract
manager emails/phone numbers, customer contact names). Those
columns are dropped at ingest and never appear in any output file —
see `build_dir_contract_observation` /
`build_dir_sale_observation`, and the tests asserting the
addresses/names are absent from the emitted JSON.

## Guardrails

$0 recurring cost. No signup, no API key, no spending, no account
creation, no contacting anyone. Read-only public sources. No
secrets or live private data in any file.
