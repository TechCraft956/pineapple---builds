# Sensor #87 — Local POI & business changes (Roma / Fronton, TX)

Read-only collector for points of interest (shops, amenities, offices)
in the Roma / Fronton, TX area, from OpenStreetMap (Overpass API) with
an Overture Maps release check. Part of the 100-sensor program, Wave 4.

## What it does

`poi.py` runs two legs:

1. **Overpass (primary):** POSTs an Overpass QL query to
   `https://overpass-api.de/api/interpreter` for nodes, ways and
   relations tagged `shop=*`, `amenity=*` or `office=*` inside a
   ~0.2-degree bbox around Roma, TX (south 26.30, west −99.11,
   north 26.50, east −98.91; Roma city centre 26.4094, −99.0145,
   verified via Nominatim, sits inside). Elements are returned with
   `out meta center`, so each carries its last-edit timestamp (the
   "change" signal) and a centre coordinate for ways/relations.
   One observation per element: category (`shop:convenience`,
   `amenity:restaurant`, …), name, `opening_hours`, coordinates,
   last-edit timestamp, OSM version/changeset, and edit-recency flags
   (edited within 90 / 180 / 365 days of retrieval).
2. **Overture (release check only):** reads the public STAC catalog
   (`https://stac.overturemaps.org/catalog.json`) to record the
   current release, then checks for Parquet tooling. Overture
   places/buildings exist only as GeoParquet (zstd) on public
   S3/Azure — there is no keyless non-Parquet API — so with no
   Parquet reader available the leg is **BLOCKED-needs-feed** (see
   below). No Parquet file is downloaded and no rows are invented.

Each observation is labeled:

- **VERIFIED** — category, coordinates, and edit timestamp all present.
- **REPORTED** — category present but edit timestamp missing (real
  POI; edit recency unknown, never guessed). An unnamed POI is not
  downgraded — many valid POIs have no `name` tag.
- **UNKNOWN** — no usable category value (defensive; the query filters
  on the tag keys, so this should not occur).
- **BLOCKED** — a whole leg could not be fetched; recorded on the leg,
  never as invented observations.

Every observation records its source URL and retrieval timestamp
(UTC). Missing values stay `null` — never zero-filled, never invented.

## Source

- Overpass API: https://overpass-api.de/api/interpreter (keyless,
  no signup, $0). Data © OpenStreetMap contributors, ODbL 1.0.
- Overture Maps STAC catalog: https://stac.overturemaps.org/catalog.json
  (keyless, no signup, $0). Data: `s3://overturemaps-us-west-2/`,
  GeoParquet per release.
- **$0 cost. No signup, no API key, no account.**

## How to run

```bash
cd builds/regional-capital
python3 poi.py --out evidence/poi_run_20261126.json
```

Options:

| Flag | Effect |
|---|---|
| `--bbox south,west,north,east` | Override the Roma/Fronton bbox (default: `26.30,-99.11,26.50,-98.91`). |
| `--timeout N` | Overpass request timeout in seconds (default: 90). |
| `--out <path>` | Write result JSON (default: stdout). |

Stdlib Python only; no dependencies. Exit code 0 when the Overpass
leg succeeds (even with zero POIs); exit code 2 when the Overpass leg
is blocked — the run document still records the block, mirroring
`usaspending.py`.

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

20 tests for `poi.py`, all passing (2026-11-26); full suite 175 tests,
all passing. Tests are offline fixtures — no network calls.

## Suggested activation cadence

**Weekly.** POI edits in a small rural bbox are sparse, and the
change signal is the edit timestamp, so a weekly pull with a
previous-run diff (compare `osm_type`+`osm_id` sets and
`last_edited` values) surfaces new/changed businesses without noise.

## Live evidence — 2026-11-26 (both legs blocked from here)

Run: `evidence/poi_run_20261126.json`, retrieved 2026-11-26T19:45:56Z.
**0 observations — no POI counts, no sample names, no timestamps.**
That is a finding about this environment's egress, not about Roma:
both legs were verified reachable-or-blocked by independent probes,
and nothing was invented to fill the gap.

- **Overpass — BLOCKED (environment egress).** The collector's live
  POST returned **HTTP 406** (`406 Not Acceptable`, nginx) in <1 s,
  and the same 406 came back for a GET query and for
  `/api/status`. Three alternate Overpass mirrors
  (overpass.kumi.systems, overpass.private.coffee,
  overpass.nchc.org.tw) all timed out (HTTP 000, 30–45 s each), and a
  text fetch of the interpreter URL failed with a network error.
  Other OSM infrastructure works from here — Nominatim returned Roma,
  TX (place 314900761, lat 26.4094075, lon −99.0144578) in the same
  session — so this is a block on the Overpass hosts from this
  environment, not proof the Overpass API is down. Re-running the
  collector from another network (or Airam's Mac) is the fix path;
  the query itself is standard Overpass QL and is covered by offline
  tests.
- **Overture — BLOCKED-needs-feed (Parquet tooling required).**
  The STAC catalog **is** reachable and verified live: HTTP 200,
  latest release **`2026-11-18.0`**. The S3 listing for that release
  is also reachable (HTTP 200): places files are zstd Parquet, first
  part `part-00000-...-c000.zstd.parquet`, **743,049,502 bytes**.
  A byte-range GET of its first 8 bytes returned `PAR1` (HTTP 206) —
  a real Parquet file. But `pyarrow`, `duckdb` and GDAL (`osgeo`) are
  all **absent** in this environment (checked at runtime), and stdlib
  Python has no Parquet reader, so no Overture rows can be read
  without adding Parquet tooling (a non-stdlib dependency — not added
  here, per the sensor spec). Overture publishes no keyless
  non-Parquet API: its own docs describe S3/Azure GeoParquet plus the
  STAC index only, read via the `overturemaps` CLI, DuckDB, or GDAL.
  Fix path: install `duckdb` (or `pyarrow`) and implement a
  bbox-filtered read of `theme=places/type=place/` for the recorded
  release — or run the collector where that tooling exists.

## Limitations

- Overpass returns the *current* OSM snapshot only: a POI deleted
  from OSM disappears from the next run (compare runs to catch
  deletions), and `last_edited` is the last edit of that element,
  not necessarily a business opening/closing — a tag fix and a new
  shop look the same until a human checks the diff.
- Category priority is `shop` > `amenity` > `office` when an element
  carries more than one of those keys; the other keys are not
  emitted. `opening_hours` is reproduced exactly as tagged, without
  interpretation.
- The bbox is a rectangle, not the Roma town boundary: a few POIs
  just outside Roma (e.g. along US-83 toward Fronton) are included
  by design; nothing is filtered by town name.
- The Overture leg records the release only. Until Parquet tooling
  exists, #87's business-change signal is Overpass-only.

## Guardrails

$0 recurring cost. No signup, no API key, no spending, no account
creation, no contacting anyone. Read-only public APIs. No secrets or
live private data in any file. No cron/schedule was created — activation
is proposed to the owner (weekly).
