# BUILD REPORT — GEOINT / TerraRecon (BUILD-20261117-005)
Built by Everest (subagent) 2026-11-17, ~16:37–17:05 CT. Workspace:
`~/workspace/pineapple/builds/geoint/`. Stage: **VERIFIED** — every
acceptance check in the brief passes (see Acceptance evidence below).
No writes were made to the AI Bridge sheet or PIPELINE_STATE.md (parent's job).

## What was built

### 1. Sample dataset restored (Task 1)
`data/parcels.geojson` — 12 synthetic RGV parcels (McAllen, Edinburg,
Mission, Pharr, Brownsville, Roma, Rio Grande City, South Padre Island,
Port Mansfield), zones X×4 / A×2 / AE×3 / VE×3, 5 zonings (Residential,
Commercial, Agricultural, Industrial, Mixed-Use), Polygon geometry, owners
prefixed `SAMPLE:`, `"data_source": "sample"` on every feature.

### 2. Module hardening (build copy only — recovered originals untouched)
`gis_parcels.py` is a copy of the recovered module with three deliberate,
brief-directed changes (original md5 `9c5f4674b81a34f04732968e455df1c9`
re-verified after the build):
- **Unknown flood zone ⇒ HIGH (0.70), never 1.00** (GPT-folded hardening):
  `flood_risk()` default changed MED → HIGH; the `"" → LOW` entry removed,
  so `""`/`None`/unknown codes all score HIGH. Selftest asserts
  `flood_risk("ZZZ"/""/None) == "HIGH"` and `score_parcel(1.0, "ZZZ") == 0.70`.
- `PROCESSED_DIR` moved from the Pineapple OS root's `00_PROCESSED` to this
  workspace's `00_PROCESSED/` so `--export` never writes outside the build.
- `items()` now carries `data_source` + `warning` (planning-signal) on every
  record, plus `flood_join_method`/`flood_caveat`; `export_scored()` carries
  a top-level `_warning`. Selftest asserts warning + data_source on all items.

### 3. Live county + FEMA adapters (Task 2)
`adapters/` (stdlib only): `client.py` (retries + cache with
`retrieved_at_utc` + source URL), `mapping.py` (BIS + StratMap field maps),
`fema.py` (NFHL join with point-in-polygon), `stratmap.py` (identify grid),
`run_live.py` (bounded live pull + join → `live/`).

**Endpoints verified live 2026-11-17 (curl, no login, no account):**
| Source | Layer / endpoint | Fields found |
|---|---|---|
| FEMA NFHL MapServer | `hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer`, **layer 28 "Flood Hazard Zones"** (Polygon, maxRecordCount 2000) | `FLD_ZONE, ZONE_SUBTY, SFHA_TF, DFIRM_ID, FLD_AR_ID, ...` — AE polygons returned for coastal Cameron Co (DFIRM 48061C); 808 X-polygons in an RGV-wide bbox; central-McAllen envelope returns 0 polygons (high ground is not polygonized — recorded as `no_intersection`, not as polygon-confirmed X). Service is flaky: 4× connection resets (HTTP 000) during probing; the client retries 3× with backoff. |
| Starr CAD parcels | `utility.arcgis.com/usrsvcs/servers/ff05af.../rest/services/StarrCADWebService/FeatureServer/**0 "Parcels"**` (found via the BIS viewer `config.json` at `gis.bisclient.com/starrcad/cdn/6/config.json`) | `prop_id, prop_id_text, file_as_name (owner), geo_id, legal_acreage, market, land_val, imprv_val, city, county (district CODE "01"), situs_*, legal_desc, hood_cd` — real parcels returned for a Roma envelope. |
| Willacy CAD parcels | `utility.arcgis.com/usrsvcs/servers/4bc982.../rest/services/WillacyCADWebService/FeatureServer/**0 "Parcels"**` | Same BIS schema as Starr EXCEPT `Block` (capital B) vs Starr's `block`; `county` field is code `"GWI"`. Real parcels returned for a Raymondville envelope. |
| TxGIO StratMap (fallback) | `feature.geographic.texas.gov/arcgis/rest/services/Parcels/stratmap_land_parcels_48_most_recent/MapServer/**0**` | `prop_id, geo_id, owner_name, legal_area, gis_area, land_value, imp_value, mkt_value, situs_addr, county ("HIDALGO"), fips, tax_year, stat_land_use, ...` — **`/0/query` with an envelope returns 0 features** (verified McAllen + Austin) and attribute-only query → HTTP 200 with 400 "Requested operation is not supported"; the working path is **`/MapServer/identify` at a point** (verified: McAllen point → Hidalgo parcel, SOURCE "HIDALGO APPRAISAL DISTRICT", TAX_YEAR 2026; Brownsville point → Cameron parcel). Adapter uses an identify point grid + PROP_ID dedupe. |

**Counties that walled the REST path (documented + fallback used):**
- **Hidalgo (own AD REST: WALLED).** `gis.hidalgoad.org/` serves a bare Apache Tomcat default page — no GIS app at root, `/arcgis/rest/services` → 404. Appraisal data lives in the True Automation PropAccess JS portal (`propaccess.trueautomation.com/Search.aspx?cid=84`), which exposes no public REST. Not on BIS GIS (404s). **Fallback used:** TxGIO StratMap identify (verified live, Hidalgo parcels returned). BROWSER-AGENT fallback (work the PropAccess portal as the owner would) remains available per the brief's routing.
- **Cameron (own AD REST: WALLED/UNREACHABLE).** `https://www.cameroncad.org/` unreachable via curl (HTTP 000); `http://` → 403; `esearch.cameroncad.org` unreachable; not on BIS GIS (404). Research: the district publishes a data/GIS download page with a parcel shapefile (bulk fallback) and a JS map search. **Fallback used:** TxGIO StratMap identify (verified live, Cameron parcel returned).

**Live run result (`python3 -m adapters.run_live --limit 5`): 20 parcels**
Starr 5, Willacy 5, Hidalgo 5 (StratMap), Cameron 5 (StratMap) → `live/*.geojson`
+ `live/all_live.geojson`. FEMA joins: `polygon_contained` 14, `centroid_in_polygon`
1 (with the "partial coverage — centroid only, cannot establish parcel-wide
hazard" caveat), `no_intersection` 5 (all Hidalgo — X inferred, caveat "no NFHL
polygon intersected — verify on FEMA FIRMette; zone X inferred, not
polygon-confirmed"). Zones: X×18, AH×1, AO×1. Every live parcel carries
`data_source` + `retrieved_at_utc` + `source_url`; raw responses cached in
`cache/` (6 files). The unmodified module loads `live/all_live.geojson`:
20 `items()`, confidence **0.8** (above 0.45, live path only), warning on all.
Zoning is `"UNKNOWN"` on all live parcels — no county AD layer carries zoning
(recorded in the mapping module, not invented).

**FEMA join semantics (GPT hardening implemented):** centroid point-in-polygon
against the parcel-bbox query; `polygon_contained` only when every vertex is
inside the SAME zone polygon; centroid-only joins carry the partial-coverage
caveat; no-polygon ⇒ X inferred with caveat; unknown zone codes kept verbatim
and scored HIGH (0.70) by the patched module.

### 4. Feed writer (Task 3)
`writers/geoint_writer.py` maps `items()` → Opportunity Engine records
(`type: other`, `id: geoint:<parcel_id>`, approval PENDING, risk mapped
LOW/MED/HIGH → low/medium/high, flood caveat + data_source in `provenance`,
planning warning in `risk_notes`). Round-trip verified against a LOCAL COPY
of the feed service (`feed-service-copy/`, unmodified, port 8101, scratch
data dir, test token): **32/32 records posted and read back unchanged in
meaning** (12 sample + 20 live; by source sample 12 / starr 5 / willacy 5 /
stratmap 10); re-post → 12 duplicates, 0 conflicts (idempotent);
unauthenticated POST → 401. Log: `BUILD_LOG_feed_roundtrip.txt`. Service
process terminated after the run; nothing deployed.

### 5. Tests (Task 4)
`tests/test_geoint.py` — **33/33 pass** (`pytest tests/ -q`, socket blocked
for the whole module so no outbound call can hide in the offline tests):
flood discount boundaries for every zone in the table + 6 unknown-zone cases
(→ 0.70 HIGH); geometry validation (missing geometry, non-Feature, empty FC,
missing props, non-FeatureCollection); centroid/bbox Polygon vs MultiPolygon;
per-county field mapping on RECORDED live fixtures (Starr, Willacy, StratMap);
FEMA join correctness on fixtures (AE → 0.88, X → 1.00, unknown "D" → 0.70,
centroid-only caveat, polygon-contained, no-intersection inference, plus a
join against the RECORDED live AE polygons, DFIRM 48061C); fetch_json fails
with the network blocked; feed writer records validate against the feed
opportunity schema and carry warning + data_source (sample and live).

## Acceptance evidence
- `--selftest` exits 0 (12 parcels; LOW=4 MED=5 HIGH=3; top SAMPLE-RGV-006, 0.88).
- `--json` emits 12 items; `--export` writes `00_PROCESSED/geoint_parcels_scored.geojson`.
- Hidalgo adapter runs against the live endpoint (StratMap fallback — Hidalgo's
  own REST is walled, documented above) and produces module-loadable GeoJSON
  with provenance on every parcel; all four counties have live parcels.
- FEMA join verified on fixtures: parcel inside AE polygon → 0.88 discount;
  parcel in X → 1.00; unknown zone → 0.70.
- Feed round-trip passes; every record carries the flood caveat + data_source.
- Offline tests pass (33/33) with no network calls (socket blocked in-test).

## What failed / caveats
- FEMA NFHL is intermittently flaky (4× HTTP 000 connection resets during
  probing; retries recover). The adapter retries 3× with backoff.
- StratMap `/0/query` is unusable for envelope queries (returns 0 features);
  only `identify` works — adapter uses identify grids, so StratMap pulls are
  point-sampled, not exhaustive. A full-county pull would need a denser grid
  or the DataHub bulk shapefile.
- Hidalgo's 5 live parcels all came back `no_intersection` (X inferred) —
  consistent with the McAllen envelope returning 0 NFHL polygons; the caveat
  is on each record. A parcel in a mapped SFHA near McAllen would need a
  targeted pull around a known floodplain (e.g. along the Arroyo Colorado).
- Live parcels have no zoning (CAD layers don't carry it) and
  `opportunity_score` is a documented heuristic (cheap land scores higher),
  not a valuation. Confidence 0.8 on live data reflects authoritative parcel
  geometry + values, not a verified flood determination where the join was
  centroid-only or no-intersection — the caveat fields carry that nuance.
- One Willacy live parcel has `acreage: null` (source `legal_acreage` null) —
  carried through as null, not invented.

## Files changed / created (all under `~/workspace/pineapple/builds/geoint/`)
- `gis_parcels.py` (patched build copy), `data/parcels.geojson` (new),
  `00_PROCESSED/geoint_parcels_scored.geojson`
- `adapters/{__init__,client,mapping,fema,stratmap,run_live}.py`
- `writers/geoint_writer.py`, `verify_feed_roundtrip.py`,
  `BUILD_LOG_feed_roundtrip.txt`
- `tests/test_geoint.py`, `fixtures/` (8 recorded live responses),
  `cache/` (6 raw live responses), `live/` (5 GeoJSON files, 20 parcels)
- `feed-service-copy/` (unmodified copy for the local round-trip test),
  `README.md`, `README_ORIGINAL.md`, this report
- Recovered originals untouched (md5-verified: gis_parcels.py
  `9c5f4674b81a34f04732968e455df1c9`; README.md
  `c71a37ba07a0a625716a2d1f4b4b8807`).

## Surprises in the module
- The recovered module's `flood_risk()` defaulted unknown zones to MED
  (0.88) — the GPT hardening (HIGH / 0.70) was a real, needed change, not
  cosmetic: an unmapped zone must never outrank proven high ground.
- `export_scored()` in the recovered original wrote to the Pineapple OS
  root's `00_PROCESSED` — outside any build workspace; the build copy
  confines it. Worth checking in other briefs that reuse recovered modules
  with a `ROOT / "00_PROCESSED"` pattern.
- The module's `_feature_point` (mean of vertices) is what the FEMA join
  reuses as the centroid — consistent, but for a concave parcel the mean
  can fall outside the parcel; the join's `polygon_contained` check (all
  vertices inside one zone polygon) is the guard for parcel-wide claims.
