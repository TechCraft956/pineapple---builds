# Sensor #52 — TxDOT traffic counts & work zones (US-83 / I-2, Starr County / RGV)

Read-only collector for Pineapple sensor #52. Standard library Python only.
$0 recurring cost. No signups, no API keys (by default), no spending, no
account creation, no contacting anyone.

## What it does

`txdot.py` runs three legs and emits one JSON document of observations, each
labelled **VERIFIED / REPORTED / UNKNOWN / BLOCKED** with `source_url` and
`retrieved_at_utc`. Missing values stay `null` — never zero-filled.

| Leg | Status (2026-11-26) | Source |
|---|---|---|
| AADT traffic counts | **VERIFIED** — 1,659 stations in bbox, 860 within 3 km of US-83 / I-2 | TxDOT ArcGIS `TxDOT_5_Year_Statewide_AADT_Traffic_Counts` layer 0 (`TMB_RPT_SHORT_AADT_HIST`), keyless |
| WZDx work zones | **BLOCKED-needs-feed** — feed answers HTTP 401 without an API key | `https://api.drivetexas.org/api/conditions.wzdx.geojson` (WZDx v4.2, key required per USDOT registry entry `txdot_v4_2`) |
| Highway events | **REPORTED** — 0 active events in the corridor bbox | TxDOT ArcGIS `Highway_Events_LN` layer 0, keyless |

Corridor: bounding box lon −99.3…−97.6, lat 26.0…27.0 (Starr County + RGV).
US-83 Roma→Harlingen and I-2 McAllen→Harlingen polylines are waypoint lists
in the script; stations within 3 km are flagged `corridor_near`. The AADT
layer has no route-name field, so the corridor filter is geographic, not
by route attribute — see `evidence/txdot_evidence.md`.

Latest AADT is taken from the column matching each station's
`LATEST_AADT_YR` (2025 → `AADT_RPT_QTY`, 2024 → `HIST_01`, …, 2021 →
`HIST_04`). A station whose latest-year cell is empty is reported with
`latest_aadt: null` and status UNKNOWN.

## How to run

```bash
cd ~/workspace/pineapple/builds/regional-capital
python3 txdot.py --out output_txdot_20261126.json --cache-dir cache
```

- `--out FILE` — also write the JSON document to FILE (otherwise stdout only).
- `--cache-dir DIR` — save raw ArcGIS responses + `.meta.json` sidecars
  (`retrieved_at_utc`, byte count) under DIR.
- `--no-cache` — skip raw-response caching.
- Exit code 0 whenever a document was written, even if a leg is blocked
  (leg status is in the document). Exit code 2 only if no output could be
  produced.

To enable the WZDx leg later, the owner obtains a free DriveTexas API key at
<https://api.drivetexas.org/> and runs with it in the environment:

```bash
TXDOT_WZDX_API_KEY=<key> python3 txdot.py --out out.json
```

The key is never written to any file. Without it the collector records the
HTTP 401 and emits a BLOCKED observation — it never invents work zones.

## Suggested activation cadence

**Hourly.** AADT is annual data (changes only when TxDOT republishes, latest
year mostly 2024), so its value is a stable baseline; the hourly value is
the work-zone / highway-event legs, which the DriveTexas feed updates every
5 minutes. Hourly keeps the sensor fresh without hammering a public
ArcGIS service. No cron/schedule was created by this build — activation is
the coordinator's call.

## Tests

```bash
cd ~/workspace/pineapple/builds/regional-capital
python3 -m unittest tests.test_txdot -v
```

20 tests, fixture-based, no network: AADT year→column mapping, missing
values staying null, corridor-distance flagging, highway-event parsing,
WZDx 401 → BLOCKED (and the keyed success path), ArcGIS pagination, and a
stubbed end-to-end `collect()`. Fixtures under `tests/fixtures/` are trimmed
captures of the live payloads from 2026-11-26.

## Files

- `txdot.py` — the collector.
- `tests/test_txdot.py` + `tests/fixtures/` — tests and fixtures.
- `evidence/txdot_evidence.md` — what the live fetch actually returned
  (station counts, date range, 401 evidence, owner step).
- `output_txdot_20261126.json` — live run output, 2026-11-26T18:49:46Z.
- `cache/` — raw ArcGIS responses from the live run (+ `.meta.json`).

## Limitations (honest)

- WZDx work zones are the canonical live source and are **blocked on a free
  API key** (owner step above). Until then the work-zone signal is the
  `Highway_Events_LN` mirror (REPORTED, not WZDx-standard).
- The legacy TxDOT WZDx 2.0 endpoint (`txdot-its-c2c.txdot.gov/WZDx/2.0`)
  is gone (HTTP 404); the DriveTexas ArcGIS point/line mirrors are live
  but empty statewide (0 features).
- AADT "corridor" membership is geographic (3 km from the polyline), not a
  route attribute, because the source layer has no route field.
- AADT is annual: the freshest counts are mostly 2024 (1,631 of 1,659
  stations); only 3 stations report a 2025 count so far.
