# Regional Capital Radar — Starr County / RGV (Pineapple sensors)

Read-only collectors for Pineapple's regional capital radar, starting with
Starr County, TX (FIPS 48427) and the Rio Grande Valley. Part of the
100-sensor build program (Waves 2–3, 2026-11-26). All collectors are stdlib
Python, $0 recurring cost, no signups, no API keys (except where noted),
no spending, no account creation, no contacting anyone.

## Collectors

| Sensor | Collector | Source | Cadence |
|---|---|---|---|
| #72 SBA 7(a)/504 loans | `sba_loans.py` | SBA FOIA loan data (data.sba.gov), quarterly CSVs | Weekly |
| #31 Gov contracts & grants | `usaspending.py` | USAspending API v2 (keyless POST) | Weekly |
| #52 TxDOT traffic & work zones | `txdot.py` | TxDOT ArcGIS AADT + DriveTexas WZDx + Highway Events | Hourly |
| #81 Starr deeds, liens & DBAs | `kofile.py` | KoFile QuickLink index (1848–1984) + modern portals | Weekly |

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

## How to run

```bash
cd builds/regional-capital
python3 sba_loans.py --out evidence/sba_loans_<date>.json
python3 usaspending.py --start 2025-01-01 --end 2026-11-26 --out evidence/usaspending_run_<date>.json
python3 txdot.py --out output_txdot_<date>.json --cache-dir cache
python3 kofile.py --out evidence/kofile_run_<date>.json
```

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

83 tests, all passing (2026-11-26): 15 SBA + 19 USAspending + 20 TxDOT
+ 29 KoFile. Tests are offline fixtures — no network calls.

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
