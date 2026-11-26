# Regional Hazards — Starr County / RGV (Pineapple sensors)

Read-only collectors for Pineapple's regional hazards lane, starting with
Starr County, TX (FIPS 48427) and the Rio Grande Valley. Part of the
100-sensor build program (Wave 3, 2026-11-26). All collectors are stdlib
Python, $0 recurring cost, no signups, no API keys, no spending, no
account creation, no contacting anyone.

## Collectors

| Sensor | Collector | Source | Cadence |
|---|---|---|---|
| #57 FEMA disasters + Public Assistance | `openfema.py` | OpenFEMA API (per-dataset current version) | Daily |
| #73 NFIP flood claims (v3) | `openfema.py` | OpenFEMA `NfipClaims` v3 | Daily |
| #74 NOAA weather + drought | `nws_drought.py` | NWS API + NDMC Drought Monitor web service | Hourly (NWS) / Weekly (drought) |
| #53 EPA ECHO violations/permits | `epa_echo.py` | ECHO web services (`echodata.epa.gov`) | Weekly |
| #75 FRS facility registry + TCEQ | `epa_echo.py` | Envirofacts (`data.epa.gov`) + TCEQ ArcGIS | Weekly |

Each collector emits observations labeled **VERIFIED / REPORTED / UNKNOWN**
(plus **BLOCKED** where a leg needs an owner step). Missing values stay
`null` — never zero-filled, never invented.

## Live evidence (2026-11-26)

- **#57 OpenFEMA disasters:** **23 declarations** affecting Starr County,
  1967-09-28 → 2025-05-21 (14 DR + 9 EM; Hurricane 10, Flood 2, Severe
  Storm 3); PA declared on 19. Newest: DR 4871, severe storms/flooding,
  2025-05-21.
- **#57 Public Assistance:** **238 funded projects**, project amount
  **$5,623,627.00**, total obligated **$4,215,690.69**. Roads and Bridges
  dominate (169 of 238).
- **#73 NFIP claims:** **85 claims**, losses 1981-06-01 → 2026-10-01,
  total paid **$2,117,276.18** (building $1,630,415.33 + contents
  $486,860.85). Busiest years: 2008 (16), 2020 (13), 2025 (9).
- **#74 NWS (Roma, TX 26.4073, -98.9751):** office BRO, gridpoint
  BRO/20,29, forecast zone TXZ252, county zone TXC427. 7-day forecast,
  14 periods — Thanksgiving Day 63 °F, tonight 47 °F, Friday 66 °F.
  **0 active alerts** for Starr County; 1 statewide (Severe Freeze
  Warning, NWS Lake Charles, not Starr).
- **#74 Drought (USDM, release 2026-11-24, valid thru 2026-11-30):**
  Starr County 1,214.95 sq mi, categorical **D0 100.0%, D1–D4 all 0** —
  the county improved out of D1 (whole county Oct 20–Nov 3) into D0-only.
- **#53 ECHO:** **389 facilities** in Starr County (CAA 12 / CWA 91 /
  RCRA 29 / TRI 0 — the TRI zero is verified real, cross-checked with a
  Harris County control); 1 significant violation, 6 current violations,
  7 facilities with quarters in violation, 3 formal enforcement actions,
  8 inspections (5-yr), **$53,692 total penalties**. Worst: Union Water
  Supply WWTP — 11 noncompliance quarters, $52,492.
- **#75 Registry:** **498 FRS program rows / 450 distinct Registry IDs**
  (upper bound — one site can carry two IDs); **3 TCEQ permitted
  wastewater outfalls** (City of Roma ×2, City of Rio Grande City ×1).

## How to run

```bash
cd builds/regional-hazards
python3 openfema.py --out evidence/openfema_run_<date>.json
python3 nws_drought.py --out evidence/nws_drought_run_<date>.json
python3 epa_echo.py --out evidence/epa_echo_run_<date>.json
```

## Tests

```bash
cd builds/regional-hazards
python3 -m unittest discover -s tests -v
```

71 tests, all passing (2026-11-26): 25 OpenFEMA + 20 NWS/drought +
26 EPA ECHO. Tests are offline fixtures — no network calls.

## Notes

- **OpenFEMA versions are per-dataset, not per-API.** `DisasterDeclarationsSummaries`
  and `PublicAssistanceFundedProjectsDetails` are current as **v2**;
  `NfipClaims` is current as **v3**. The "v2 retired Oct 2026 — v3 only"
  premise does not hold for these datasets; the collector uses each
  dataset's current version (verified against the v1 DataSets catalogue).
  County-code formats differ too: declarations/PA use the 3-digit county
  code (`427` + state `48`); only NfipClaims uses full 5-digit FIPS
  `48427`. Requests must send `Accept: application/json` or fema.gov
  answers with a Drupal 404 page. `metadata.count` is 0 unless
  `$count=true` is requested.
- **USDM county JSON moved.** The date-based
  `droughtmonitor.unl.edu/data/json/<date>/tx_county.json` path is dead
  (404); the live path is the NDMC web service
  `usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByArea`
  (keyless, `Accept: application/json`).
- **ECHO and Envirofacts moved hosts.** `ofmpub.epa.gov/echo/*` is HTTP
  404 on every variant and `ofmpub.epa.gov/enviro/efservice` is HTTP 502;
  the live hosts are `echodata.epa.gov/echo` and `data.epa.gov`
  (`efservice` / `dmapservice`). The ECHO county parameter is `p_fips`,
  not `p_cx` — `p_cx` is silently ignored and returns the whole country
  (5.7M rows). Dead paths are recorded in the run output under
  `superseded_paths`.
- No cron/schedule was created by this wave — activation is proposed
  per wave to the owner (daily for #57/#73, hourly/weekly for #74,
  weekly for #53/#75).
