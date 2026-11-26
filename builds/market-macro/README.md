# Market & Macro — Pineapple Wave 5

SEC EDGAR filings, central-bank policy rates, FX, and FINRA margin
debt. All collectors are read-only, keyless, stdlib-only, $0.
No signups, no keys, no spend, no account creation.

## Sensors

| # | Collector | Source | Status (2026-11-26) |
|---|---|---|---|
| 18 | `insider.py` | SEC EDGAR daily master index + submissions JSON | BUILT |
| 60 | `events_8k.py` | SEC EDGAR daily master index + submissions JSON | BUILT |
| 62 | `ipo_pipeline.py` | SEC EDGAR daily master index | BUILT |
| 64 | `rates_fx.py` | BIS Stats API v2 (WS_CBPOL) + ECB Data Services | BUILT |
| 103 | `margin_debt.py` | FINRA margin-statistics XLSX | BUILT (Wave 5 deficit sweep) |

Shared client: `edgar.py` (User-Agent, 10 req/s throttle, master-index
parsing, submissions, Form 4 XML, 8-K item extraction).

## Run

```sh
cd builds/market-macro
python3 insider.py --days 5 --max-form4 25 --out evidence/insider_run_20261126.json
python3 events_8k.py --days 5 --max-items 20 --out evidence/events_8k_run_20261126.json
python3 ipo_pipeline.py --days 5 --out evidence/ipo_pipeline_run_20261126.json
python3 rates_fx.py --last-n 3 --out evidence/rates_fx_run_20261126.json
python3 margin_debt.py --months 12 --out evidence/margin_debt_run_20261126.json
```

## Tests

```sh
python3 -m unittest discover -s tests -v   # 31 tests, offline fixtures only
```

## Live evidence (2026-11-26, Thanksgiving Day)

- **#18 — 3,928 observations.** Form 4 filings Nov 23–25: 1,347 / 1,389 /
  1,140 (Nov 22 was a Sunday, Nov 26 index not yet posted — HTTP 403,
  recorded UNKNOWN). 37 13F-HR filings. 52 insider transactions parsed
  from 25 Form 4 XMLs (11 open-market buys P, 25 sells S, rest F/D/M
  codes). Watchlist (12 large-cap CIKs): 120 recent Form 4 / 13F-HR
  filings.
- **#60 — 683 8-K filings** (Nov 23–25: 245 / 253 / 185). 20 parsed
  for items: 9.01 ×12, 1.01 ×5, 7.01 ×5, 8.01 ×4, 5.02 ×4.
  Watchlist: 60 recent 8-Ks.
- **#62 — 170 pipeline filings** (Nov 23–25: 35 / 77 / 58): S-1 15,
  S-1/A 11, F-1 5, F-1/A 6, S-4 9, S-4/A 5, 424B4 1 (Yesway Inc.,
  Nov 23), 424B3 90, EFFECT 28.
- **#64 — 90 observations, all VERIFIED.** BIS: 16 series (14 monthly
  economies + daily US/XM). US policy rate 3.625 (Aug 2026) → 3.875
  (Sep, Oct) — the FOMC 3.75–4.00% midpoint. Euro area 2.25 → 2.50.
  ECB: 12 FX reference rates (USD/EUR 1.0963 / 1.0935 / 1.0975,
  Nov 24–26) + EURIBOR 3M ~2.63%, 1Y ~3.24%.
- **#103 — 358 monthly rows (Jan 1997 – Oct 2026).** Latest Oct 2026:
  margin debit $1,448,360M, free credit cash $210,290M, free credit
  margin $212,890M. Nov 2025 debit was $1,214,321M.

## Labels

VERIFIED — fetched live, all key fields parsed.
REPORTED — row/filing exists but detail is missing or unparseable
(e.g. an 8-K whose text was not fetched, a Form 4 beyond the parse
cap). The row is real; the gap is recorded, never zero-filled.
UNKNOWN — no data returned (weekend/holiday with no master index, a
watchlist CIK with no filings of that form, a series not published
at the requested frequency).

## Caveats

- The EDGAR master index is posted end-of-day; a same-day run sees
  HTTP 403/404 for today (recorded UNKNOWN, not an error).
- Form 4 / 8-K detail is capped per run (`--max-form4`,
  `--max-items`); unparsed filings are counted, never invented.
- 8-K item extraction searches the full filing text (up to 250k
  chars) because HTML/CSS boilerplate buries the headings.
- The BIS API needs the full dataflow path
  (`/data/dataflow/BIS/WS_CBPOL/1.0/...`) and the SDMX-JSON Accept
  header — the short path returns 500, a plain request 406.
- The ECB's own key policy rates (MRO / deposit facility) have no
  stable SDW key in this API (guessed keys 404) — recorded UNKNOWN;
  EURIBOR is the euro-area rate leg.
- FINRA margin workbook lists newest first; the collector sorts
  ascending before taking the recent window.
