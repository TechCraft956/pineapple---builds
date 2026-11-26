# Regional Capital Radar — Starr County / RGV (Pineapple sensors)

Read-only collectors for Pineapple's regional capital radar, starting with
Starr County, TX (FIPS 48427) and the Rio Grande Valley. Part of the
100-sensor build program (Waves 2–4, 2026-11-26). All collectors are stdlib
Python, $0 recurring cost, no signups, no API keys (except where noted),
no spending, no account creation, no contacting anyone.

## Collectors

| Sensor | Collector | Source | Cadence |
|---|---|---|---|
| #72 SBA 7(a)/504 loans | `sba_loans.py` | SBA FOIA loan data (data.sba.gov), quarterly CSVs | Weekly |
| #31 Gov contracts & grants | `usaspending.py` | USAspending API v2 (keyless POST) | Weekly |
| #52 TxDOT traffic & work zones | `txdot.py` | TxDOT ArcGIS AADT + DriveTexas WZDx + Highway Events | Hourly |
| #81 Starr deeds, liens & DBAs | `kofile.py` | KoFile QuickLink index (1848–1984) + modern portals | Weekly |
| #51 Hiring & labor market | `qcew_warn.py` | BLS QCEW area CSVs + TWC WARN workbooks | Monthly |
| #55 Census BFS + CBP | `bfs.py` + `cbp.py` | Census BFS bulk files + CBP county ZIP (API leg blocked, needs key) | Monthly |
| #87 Local POI & business changes | `poi.py` | OSM Overpass + Overture Maps (both legs blocked live) | Weekly |
| #82 TX procurement & DIR | `procurement.py` | TxSmartBuy ESBD + TX DIR Socrata contracts | Weekly |
| #85 DOL foreign labor | `oflc.py` | DOL OFLC disclosure .xlsx (official leg blocked; MORVS mirror) | Quarterly |
| #101 County unemployment (LAUS) | `laus.py` | BLS LAUS API v1 (keyless) — Wave 4 deficit sweep | Monthly |

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
- **#81 KoFile deeds (Wave 3):** the real Starr KoFile path was found on
  the official County Clerk page — KoFile QuickLink
  (`kofilequicklinks.com/StarrTX/Default.aspx`, HTTP 200, **VERIFIED**):
  Clerk Humberto Gonzalez, coverage claimed 1848–1984, book types Deed of
  Trust / Deeds, year ranges 1884-1926, 1926-1971, 1971-1979, 1979-1984.
  **Zero deed records retrieved** — the index is name-keyed and no search
  has completed from here (search-leg GET timed out at 30 s, twice).
  Modern portal `starr.tx.publicsearch.us` is HTTP 403 from this
  environment (**UNKNOWN**, renders via text fetch, certified through
  11/20/2026); search host `starrtx.search.kofile.com` closes the
  connection here (**UNKNOWN**). TexasFile leg is **BLOCKED-spend**
  (registration + paid records). DBA leg **UNKNOWN** (no online portal
  found). #81 covers the historical deed leg only — it does **not** by
  itself close the #27 lien/foreclosure gap, whose records live in the
  modern portal.

## Live evidence — Wave 4 (2026-11-26)

- **#51 QCEW + WARN:** **112 observations (104 VERIFIED).** Starr
  County 2026Q1: **15,613 jobs, 675 establishments, $796 avg weekly
  wage, $161.5M quarterly wages**; trend 15,137 → 15,613 across
  2025Q1–2026Q1. MSA 2026Q1: 297,416 jobs, $850/wk. WARN: 6 RGV
  notices in 2026 (all Cameron, 816 workers), 25 in 2025 — **zero
  WARN notices in Starr County in either year**. QCEW lags ~2
  quarters (2026Q2/Q3 are HTTP 404, not yet released).
- **#55 BFS:** **34 observations, all VERIFIED.** Starr County
  business applications 178 (2005) → **466 (2025)**, +213 since
  2019. Texas weekly (wk 43, 2026): 9,790 applications. The BFS API
  leg is **BLOCKED-needs-owner** ("Missing Key" page — Census API
  key mandate, May 2026); the bulk files are keyless, so the sensor
  is built on them.
- **#55 CBP (deficit sweep):** **216 Starr rows, all VERIFIED**
  (2023 reference year). Starr total: **8,704 employees, 594
  establishments, $234.8M annual payroll**. Top sector: Health Care
  & Social Assistance, 4,156 employees.
- **#87 POI:** **0 observations — both legs blocked live.**
  Overpass answers HTTP 406 from this environment (corroborated
  across mirrors; Nominatim works, so it is an egress block, not the
  API being down). Overture's STAC catalog is live (latest release
  2026-11-18.0) but its data is zstd Parquet and no Parquet tooling
  exists here — **BLOCKED-needs-feed**. The collector is ready to
  produce real data the moment either leg is unblocked.
- **#82 Procurement + DIR:** **342 observations, all VERIFIED.**
  ESBD: 5 RGV matches in the newest pages (all TxDOT maintenance
  contracts in Hidalgo/Cameron), 0 Starr matches — no Starr County
  member exists in the ESBD agency dropdown. DIR Socrata: 5,214
  active cooperative contracts; **287 FY2026 purchases by Starr
  customers, $310,993.66** (Starr County $144,677; Memorial Hospital
  $102,272; Sheriff $58,715). TxDOT lettings: 0 open Starr lettings.
- **#85 OFLC:** official DOL leg **BLOCKED** (Akamai 403 on all four
  FY26Q4 .xlsx files from here). MORVS mirror leg (same DOL data,
  CC0): **55 Texas observations** (9 H-2A + 15 H-2B + 31 LCA), FY2026
  Q2 vintage. **Starr/RGV county cut is UNKNOWN** — the mirror
  carries no worksite city/county; the county cut needs the official
  files (Addendum B) from an unblocked host.
- **#101 LAUS (deficit sweep):** **424 observations (412 VERIFIED).**
  Starr County unemployment rate **8.3% (Sep 2026, preliminary)**,
  down from 10.8% (Jan 2024); labor force 25,335. McAllen MSA 5.6%,
  Texas 4.3%.

## How to run

```bash
cd builds/regional-capital
python3 sba_loans.py --out evidence/sba_loans_<date>.json
python3 usaspending.py --start 2025-01-01 --end 2026-11-26 --out evidence/usaspending_run_<date>.json
python3 txdot.py --out output_txdot_<date>.json --cache-dir cache
python3 kofile.py --out evidence/kofile_run_<date>.json
python3 qcew_warn.py --out evidence/qcew_warn_run_<date>.json
python3 bfs.py --out evidence/bfs_run_<date>.json
python3 cbp.py --out evidence/cbp_run_<date>.json
python3 poi.py --out evidence/poi_run_<date>.json
python3 procurement.py --out evidence/procurement_run_<date>.json
python3 oflc.py --out evidence/oflc_run_<date>.json
python3 laus.py --out evidence/laus_run_<date>.json
```

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

195 tests, all passing (2026-11-26): 15 SBA + 19 USAspending + 20 TxDOT
+ 29 KoFile + 21 QCEW/WARN + 10 BFS + 7 CBP + 20 POI + 22 Procurement
+ 22 OFLC + 10 LAUS. Tests are offline fixtures — no network calls.

## Notes

- #28 Census BPS permits was **not** built in this wave: Gemini's live
  sample run (Bridge row CHAT-GEMINI-20261126-002) already covers it with
  a Sheet baseline (Census `co2609c.txt`). A production collector for #28
  remains open for a later wave.
- #52's WZDx work-zone leg needs a free DriveTexas API key (owner step).
  Until then the work-zone signal is the `Highway_Events_LN` mirror
  (REPORTED, not WZDx-standard).
- #81's TexasFile leg needs a TexasFile registration/subscription (owner
  step, paid records). The modern deed/lien portal is environment-blocked
  from here (HTTP 403 / connection closed); it renders via text fetch, so
  the block is on this environment's egress, not proof the portal is down.
  The QuickLink year menu starts 1884 while coverage claims 1848 — the
  1848–1883 slice has no menu entry (TSLAC microfilm Reel 1016443 covers
  it, REPORTED, not a live feed).
- Per-sensor details, run options, and limitations live in
  `README_SBA.md`, `README_USASPENDING.md`, and `README_TXDOT.md`.
- No cron/schedule was created by this wave — activation is proposed
  per wave to the owner (weekly for #72/#31, hourly for #52, weekly
  for #81).
- **Wave 4 notes (2026-11-26):** #51's BLS bulk ZIPs are HTTP 403
  (Akamai) — the `data.bls.gov` CSV-slice API is the working path;
  TWC WARN page moved (`/businesses/warn` is 404; live page is
  `/data-reports/warn-notice`). #55's BFS API leg needs a Census key
  (owner step); the CBP leg's reference year is 2023 — bump
  `LATEST_YEAR` in `cbp.py` when a new release is confirmed. #87's
  Overpass leg is egress-blocked here (HTTP 406) and Overture needs
  Parquet tooling — re-run from an unblocked host. #85's official
  DOL leg is Akamai-blocked here; the MORVS mirror is second-hand
  data (REPORTED, never VERIFIED) with no county cut. #101's BLS API
  v1 answers multi-series requests with HTTP 503 / "website is busy"
  from here — the collector posts one series at a time (12
  queries/run, inside the 25/day keyless limit) and the API returns
  the 3 most recent years regardless of the requested start year.
