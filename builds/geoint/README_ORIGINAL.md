# 08_GEOINT - GIS Parcel + Hazard Layer (RGV)

Local-first GIS module for Pineapple OS. Loads a Leaflet-ready GeoJSON
FeatureCollection of Rio Grande Valley parcels, computes a bounding box +
centroid, scores each parcel as a real-estate opportunity (discounted by FEMA
flood hazard), and exposes them to the Pineapple decision engine.

## Status: SAMPLE (offline)

`data/parcels.geojson` is **clearly-marked synthetic data**: realistic RGV
lon/lat near McAllen / Edinburg / Brownsville (~ -98.2, 26.2), but fabricated
owners, values, and parcel IDs. Every feature carries `"data_source": "sample"`
and owners are prefixed `SAMPLE:`. The module never fetches live network data.
Do **not** treat the output as authoritative title, valuation, or flood
determination. Verify against county AD records and FEMA NFHL before acting.

## Files

| File | Purpose |
|------|---------|
| `gis_parcels.py` | Module: load, bbox/centroid, scoring, `items()`, `PLUGIN`, CLI/selftest |
| `data/parcels.geojson` | 12 sample RGV parcels (Polygon features), Leaflet-ready GeoJSON |

## Property schema (per feature)

`parcel_id`, `owner`, `value`, `opportunity_score`, `flood_zone`, `zoning`
(plus `county`, `city`, `acreage`, `data_source`).

## Run

```bash
python gis_parcels.py --selftest   # health check, exit 0 on success
python gis_parcels.py              # pretty-print scored parcels
python gis_parcels.py --json       # items() as JSON
python gis_parcels.py --export     # write scored geojson to 00_PROCESSED
```

## Scoring

`computed_score = opportunity_score x flood_discount`, where the flood discount
is derived from the FEMA NFHL zone:

| FEMA zone | Meaning | risk | discount |
|-----------|---------|------|----------|
| X / X500  | minimal hazard | LOW | 1.00 |
| A / AE / AO / AH | 1% annual (100-yr SFHA) | MED | 0.88 |
| V / VE    | coastal high-velocity SFHA | HIGH | 0.70 |

So a cheap parcel in a velocity zone ranks below an equally-cheap parcel on
high ground.

## How it plugs into the decision brief

`items()` returns dicts shaped for the decision engine, each with:
`title, category ("ASSETS"), source, action, est_value, risk
("LOW"/"MED"/"HIGH"), location, url, confidence (0-1)` plus map extras
(`lon, lat, opportunity_score, flood_zone, zoning, parcel_id`).

`decision_engine.py` ranks ASSETS items by quant score; these parcels surface
in the **ASSETS** lane of `decision_brief.json`. Confidence is held low (0.45)
while data is sample, so real wired sources will outrank it.

`export_scored()` writes `00_PROCESSED/geoint_parcels_scored.geojson`
(FeatureCollection with `bbox`, `centroid`, `computed_score`, `flood_risk`) -
drop straight into `L.geoJSON(...)` for a Leaflet map.

## REAL live sources to wire (currently NOT fetched - offline)

Replace the sample FeatureCollection with authoritative parcel geometry + FEMA
hazard polygons via these public endpoints (also listed in `PLUGIN["sources"]`
and the `REAL_LAYERS` comment block in `gis_parcels.py`):

**County Appraisal District parcels (ArcGIS REST FeatureServer/MapServer):**
- Hidalgo County AD GIS: https://gis.hidalgoad.org/
- Cameron County AD: https://www.cameroncad.org/
- Starr County AD: https://www.starrcad.org/
- Willacy County AD: https://www.willacycad.org/
- (neighbors: Brooks, Kenedy, Jim Hogg, Zapata county ADs)

Typical query: `.../FeatureServer/0/query?where=1=1&outFields=*&f=geojson`

**FEMA National Flood Hazard Layer (flood_zone source of truth):**
- Portal: https://hazards.fema.gov/femaportal/wps/portal/NFHLWMS
- ArcGIS REST: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
- Flood zone polygons via `/28/query?f=geojson` (Zone X / AE / VE / A)

**USGS (elevation / hydrography / imagery):**
- The National Map services: https://apps.nationalmap.gov/services/
- 3DEP elevation: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer
- NHD hydrography: https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer

**TNRIS / Texas Geographic Information Office (TxGIO):**
- https://data.geographic.texas.gov/ (StratMap statewide parcels, lidar, imagery)

### Wiring note

Each county AD layer uses its own field names. Add a small adapter that maps
them onto the canonical schema (`parcel_id, owner, value, flood_zone, zoning`),
join FEMA NFHL zones by spatial intersection, then call
`load_parcels(path=<adapter output>)`. Raise `confidence` above 0.45 once data
is authoritative.

## Safety

Read-only and offline. Writes only inside this folder or `00_PROCESSED`. No
network calls. No existing Pineapple files are modified.
