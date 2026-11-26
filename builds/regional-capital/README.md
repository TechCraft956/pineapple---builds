# Regional Capital Radar — Starr County / RGV (Pineapple sensors)

Read-only collectors for Pineapple's regional capital radar, starting with
Starr County, TX (FIPS 48427) and the Rio Grande Valley. Part of the
100-sensor build program (Wave 2, 2026-11-26). All collectors are stdlib
Python, $0 recurring cost, no signups, no API keys (except where noted),
no spending, no account creation, no contacting anyone.

## Collectors

| Sensor | Collector | Source | Cadence |
|---|---|---|---|
| #72 SBA 7(a)/504 loans | `sba_loans.py` | SBA FOIA loan data (data.sba.gov), quarterly CSVs | Weekly |
| #31 Gov contracts & grants | `usaspending.py` | USAspending API v2 (keyless POST) | Weekly |
| #52 TxDOT traffic & work zones | `txdot.py` | TxDOT ArcGIS AADT + DriveTexas WZDx + Highway Events | Hourly |

Each collector emits observations labeled **VERIFIED / REPORTED / UNKNOWN**
(plus **BLOCKED** for #52's WZDx leg) with source URL + retrieval
timestamp. Missing values stay `null` — never zero-filled, never invented.

## Live evidence (2026-11-26)

- **#72 SBA:** 523,243 rows scanned; **11 Starr County loans, all
  VERIFIED** (10 × 7(a), 1 × 504), approvals 2017-05-12 → 2026-06-25,
  total gross approval **$2,761,000**. Street addresses dropped at ingest.
- **#31 USAspending:** **142 awards, all VERIFIED** (3 contracts
  $73,587.90 + 139 grants $15,423,655.00) in the 2025-01-01 → 2026-11-26
  window; 942 all-time. Largest: Union Water Supply $9,411,120.
- **#52 TxDOT:** **1,659 AADT stations** in the corridor bbox, 860 within
  3 km of US-83 / I-2; Starr's top count 31,615 veh/day. WZDx leg is
  **BLOCKED-needs-feed** — the feed answers HTTP 401 without a free
  DriveTexas API key (owner step, see `README_TXDOT.md`).

## How to run

```bash
cd builds/regional-capital
python3 sba_loans.py --out evidence/sba_loans_<date>.json
python3 usaspending.py --start 2025-01-01 --end 2026-11-26 --out evidence/usaspending_run_<date>.json
python3 txdot.py --out output_txdot_<date>.json --cache-dir cache
```

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

54 tests, all passing (2026-11-26): 15 SBA + 19 USAspending + 20 TxDOT.
Tests are offline fixtures — no network calls.

## Notes

- #28 Census BPS permits was **not** built in this wave: Gemini's live
  sample run (Bridge row CHAT-GEMINI-20261126-002) already covers it with
  a Sheet baseline (Census `co2609c.txt`). A production collector for #28
  remains open for a later wave.
- #52's WZDx work-zone leg needs a free DriveTexas API key (owner step).
  Until then the work-zone signal is the `Highway_Events_LN` mirror
  (REPORTED, not WZDx-standard).
- Per-sensor details, run options, and limitations live in
  `README_SBA.md`, `README_USASPENDING.md`, and `README_TXDOT.md`.
- No cron/schedule was created by this wave — activation is proposed
  per wave to the owner (weekly for #72/#31, hourly for #52).
