#!/usr/bin/env python3
"""
PINEAPPLE OS - 08_GEOINT - GIS Parcel + Hazard Layer.

Loads a Leaflet-ready GeoJSON FeatureCollection of Rio Grande Valley parcels,
computes a bounding box + centroid, scores each parcel as an opportunity, and
exposes items() so the parcels feed the Pineapple decision engine.

STATUS: sample. The bundled data/parcels.geojson is clearly-marked SAMPLE data
(realistic RGV lon/lat, fabricated owners/values). Wire the REAL layers listed
in PLUGIN["sources"] and in the REAL_LAYERS table below before acting on output.

Run standalone:
    python gis_parcels.py --selftest     # health summary, exit 0 on success
    python gis_parcels.py                 # pretty-print scored parcels
    python gis_parcels.py --json          # emit items() as JSON
    python gis_parcels.py --export        # write scored geojson to 00_PROCESSED

Pure Python 3.11 stdlib only. Windows host. UTF-8.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Paths. ROOT = Pineapple OS root. Output only goes to our folder or 00_PROCESSED.
# --------------------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent
ROOT = MODULE_DIR.parent
GEOJSON_PATH = MODULE_DIR / "data" / "parcels.geojson"
# Build copy: processed output stays inside this isolated workspace
# (the recovered original wrote to the Pineapple OS root's 00_PROCESSED).
PROCESSED_DIR = MODULE_DIR / "00_PROCESSED"

# Planning-signal warning (GPT-folded hardening, BUILD-20261117-005):
# every scored output and every feed record carries this. Output is NEVER
# authoritative title, valuation, or flood determination.
PLANNING_WARNING = (
    "PLANNING SIGNAL ONLY — not authoritative title, valuation, or flood "
    "determination. Verify against county AD records and FEMA NFHL before acting."
)

# --------------------------------------------------------------------------
# REAL_LAYERS - public GIS endpoints to wire later (currently NOT fetched;
# this module is offline-only and ships sample data). Documented here so the
# sample features can be swapped for authoritative parcel + hazard geometry.
#
#   Hidalgo County AD parcels (ArcGIS REST FeatureServer):
#     https://gis.hidalgoad.org/  (Hidalgo County Appraisal District GIS portal)
#     Parcel layer typically exposed as an ArcGIS MapServer/FeatureServer
#     /query?where=1=1&outFields=*&f=geojson
#   Cameron County AD:
#     https://www.cameroncad.org/  (GIS / parcel viewer; ArcGIS REST backend)
#   Starr County AD:
#     https://www.starrcad.org/
#   Willacy County AD:
#     https://www.willacycad.org/
#
#   FEMA National Flood Hazard Layer (NFHL) - flood_zone source of truth:
#     https://hazards.fema.gov/femaportal/wps/portal/NFHLWMS
#     ArcGIS REST: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
#     Flood zone polygons (Zone X / AE / VE / A) via /28/query?f=geojson
#
#   USGS - elevation / hydrography / NAIP imagery:
#     The National Map: https://apps.nationalmap.gov/services/
#     3DEP elevation: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer
#     NHD hydrography: https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer
#
#   TNRIS / Texas (TxGIO) - statewide parcels, imagery, lidar:
#     https://data.geographic.texas.gov/   (Texas Geographic Information Office)
#     StratMap parcels & historical imagery for Hidalgo/Cameron/Starr/Willacy.
#
# Wiring note: each county AD layer returns its own field names. Map them to the
# canonical property schema below (parcel_id, owner, value, flood_zone, zoning)
# in a small adapter, then drop in via load_parcels(path=...).
# --------------------------------------------------------------------------

# Canonical property keys every feature must carry.
REQUIRED_PROPS = ("parcel_id", "owner", "value", "opportunity_score", "flood_zone", "zoning")

# Flood-zone -> risk mapping (FEMA NFHL semantics).
#   X       = minimal hazard (outside 0.2% annual chance)        -> LOW
#   AE / A  = 1% annual chance (100-yr) Special Flood Hazard Area -> MED
#   VE / V  = coastal high-velocity SFHA (wave action)           -> HIGH
# GPT-folded hardening (BUILD-20261117-005): an UNKNOWN zone (anything not in
# this table, including "" / None) is conservatively HIGH (discount 0.70),
# never 1.00 and never a silent default to LOW. Unknown means unproven
# hazard, and unproven hazard must not rank above proven high ground.
_FLOOD_RISK = {
    "X": "LOW", "X500": "LOW",
    "A": "MED", "AE": "MED", "AO": "MED", "AH": "MED",
    "VE": "HIGH", "V": "HIGH",
}


# --------------------------------------------------------------------------
# Loading + geometry
# --------------------------------------------------------------------------
def load_parcels(path: Path = GEOJSON_PATH) -> dict:
    """Load and minimally validate the GeoJSON FeatureCollection."""
    with open(path, "r", encoding="utf-8") as fh:
        fc = json.load(fh)
    if fc.get("type") != "FeatureCollection":
        raise ValueError("not a FeatureCollection: %r" % fc.get("type"))
    feats = fc.get("features")
    if not isinstance(feats, list) or not feats:
        raise ValueError("FeatureCollection has no features")
    for i, f in enumerate(feats):
        if f.get("type") != "Feature":
            raise ValueError("feature %d is not type Feature" % i)
        props = f.get("properties") or {}
        missing = [k for k in REQUIRED_PROPS if k not in props]
        if missing:
            raise ValueError("feature %d (%s) missing props: %s"
                             % (i, props.get("parcel_id", "?"), missing))
        if not f.get("geometry"):
            raise ValueError("feature %d has no geometry" % i)
    return fc


def _iter_coords(geometry: dict):
    """Yield (lon, lat) pairs from any GeoJSON geometry (Point..MultiPolygon)."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if coords is None:
        return
    if gtype == "Point":
        yield coords[0], coords[1]
    elif gtype in ("MultiPoint", "LineString"):
        for c in coords:
            yield c[0], c[1]
    elif gtype in ("MultiLineString", "Polygon"):
        for ring in coords:
            for c in ring:
                yield c[0], c[1]
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                for c in ring:
                    yield c[0], c[1]


def bbox(fc: dict) -> list:
    """[min_lon, min_lat, max_lon, max_lat] over all features."""
    lons, lats = [], []
    for f in fc["features"]:
        for lon, lat in _iter_coords(f.get("geometry") or {}):
            lons.append(lon)
            lats.append(lat)
    if not lons:
        raise ValueError("no coordinates found for bbox")
    return [min(lons), min(lats), max(lons), max(lats)]


def centroid(fc: dict) -> list:
    """[lon, lat] center of the bbox (Leaflet setView-friendly)."""
    b = bbox(fc)
    return [(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0]


def _feature_point(f: dict) -> list:
    """Representative [lon, lat] for a feature (mean of its vertices)."""
    pts = list(_iter_coords(f.get("geometry") or {}))
    if not pts:
        return [None, None]
    n = len(pts)
    return [sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n]


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def flood_risk(zone: str) -> str:
    # Unknown / empty zone => HIGH (conservative). See _FLOOD_RISK note above.
    return _FLOOD_RISK.get((zone or "").strip().upper(), "HIGH")


def score_parcel(props: dict) -> float:
    """
    Composite opportunity score in [0,1]. Blends the provided opportunity_score
    with a flood-risk discount so high-hazard parcels rank lower even if cheap.
    """
    base = props.get("opportunity_score")
    try:
        base = float(base)
    except (TypeError, ValueError):
        base = 0.5
    base = max(0.0, min(1.0, base))
    discount = {"LOW": 1.0, "MED": 0.88, "HIGH": 0.70}[flood_risk(props.get("flood_zone"))]
    return round(base * discount, 3)


def _confidence(props: dict) -> float:
    """Sample data => modest confidence; real wired layers should override."""
    if props.get("data_source") == "sample":
        return 0.45
    return 0.8


# --------------------------------------------------------------------------
# items() - decision-engine feed
# --------------------------------------------------------------------------
def items(path: Path = GEOJSON_PATH) -> list:
    """Return opportunity-scored parcels, shaped for the Pineapple decision engine."""
    fc = load_parcels(path)
    out = []
    for f in fc["features"]:
        p = f.get("properties") or {}
        risk = flood_risk(p.get("flood_zone"))
        score = score_parcel(p)
        lon, lat = _feature_point(f)
        try:
            value = float(p.get("value"))
        except (TypeError, ValueError):
            value = None
        county = p.get("county", "")
        city = p.get("city", "")
        loc = ", ".join(x for x in (city, county) if x)
        loc = (loc + " County, TX") if county else (loc or "Rio Grande Valley, TX")
        out.append({
            "title": "Parcel %s - %s (%s, FEMA %s, %s)" % (
                p.get("parcel_id", "?"), p.get("zoning", "?"),
                city or county or "RGV", p.get("flood_zone", "?"),
                ("opp %.0f%%" % (score * 100)),
            ),
            "category": "ASSETS",
            "source": "GIS Parcel + Hazard Layer (sample; county AD + FEMA NFHL to wire)",
            "action": "Inspect parcel %s (%s, %s zoning). Verify FEMA zone %s, owner, "
                      "delinquency, and AD value before any offer." % (
                          p.get("parcel_id", "?"), loc, p.get("zoning", "?"),
                          p.get("flood_zone", "?")),
            "est_value": value,
            "risk": risk,
            "location": loc,
            "url": "https://hazards.fema.gov/femaportal/wps/portal/NFHLWMS",
            "confidence": _confidence(p),
            # extra fields useful downstream / for the map (ignored by engine if unknown)
            "lon": lon,
            "lat": lat,
            "opportunity_score": score,
            "flood_zone": p.get("flood_zone"),
            "zoning": p.get("zoning"),
            "parcel_id": p.get("parcel_id"),
            # provenance + planning-signal warning (required on every output)
            "data_source": p.get("data_source", "sample"),
            "warning": PLANNING_WARNING,
            "flood_join_method": p.get("flood_join_method"),
            "flood_caveat": p.get("flood_caveat"),
        })
    out.sort(key=lambda d: (d["opportunity_score"] or 0), reverse=True)
    return out


# --------------------------------------------------------------------------
# Export (Leaflet-ready, scored) - writes only to 00_PROCESSED
# --------------------------------------------------------------------------
def export_scored(out_dir: Path = PROCESSED_DIR) -> Path:
    """Write a scored copy of the FeatureCollection (with computed_score) to 00_PROCESSED."""
    fc = load_parcels()
    for f in fc["features"]:
        p = f.setdefault("properties", {})
        p["computed_score"] = score_parcel(p)
        p["flood_risk"] = flood_risk(p.get("flood_zone"))
    payload = {
        "type": "FeatureCollection",
        "name": "rgv_parcels_scored_sample",
        "_status": "sample",
        "_warning": PLANNING_WARNING,
        "bbox": bbox(fc),
        "centroid": centroid(fc),
        "features": fc["features"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "geoint_parcels_scored.geojson"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------
# PLUGIN descriptor
# --------------------------------------------------------------------------
PLUGIN = {
    "id": "geoint_gis_parcels",
    "name": "GIS Parcel + Hazard Layer (RGV)",
    "category": "ASSETS",
    "authority": "regional",
    "status": "sample",
    "inputs": ["data/parcels.geojson (GeoJSON FeatureCollection)"],
    "outputs": [
        "items() opportunity-scored parcels",
        "bbox + centroid",
        "00_PROCESSED/geoint_parcels_scored.geojson (Leaflet-ready)",
    ],
    "sources": [
        "https://gis.hidalgoad.org/",
        "https://www.cameroncad.org/",
        "https://www.starrcad.org/",
        "https://www.willacycad.org/",
        "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
        "https://apps.nationalmap.gov/services/",
        "https://data.geographic.texas.gov/",
    ],
    "safety": "Read-only, offline. Ships clearly-marked SAMPLE parcels (fabricated "
              "owners/values). Do NOT treat output as authoritative title, valuation, "
              "or flood determination. Verify against county AD records and FEMA NFHL "
              "before any real-estate decision.",
}


# --------------------------------------------------------------------------
# CLI / selftest
# --------------------------------------------------------------------------
def selftest() -> int:
    try:
        # 1. geojson parses with json.load
        with open(GEOJSON_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        assert raw["type"] == "FeatureCollection", "not a FeatureCollection"

        # 2. load + validate
        fc = load_parcels()
        n = len(fc["features"])
        assert n >= 12, "expected >=12 parcels, got %d" % n

        # 3. geometry
        b = bbox(fc)
        c = centroid(fc)
        assert len(b) == 4 and len(c) == 2, "bad bbox/centroid shape"
        # RGV sanity: lon ~ -99..-97, lat ~ 25..27
        assert -99.5 < c[0] < -97.0, "centroid lon out of RGV range: %s" % c[0]
        assert 25.0 < c[1] < 27.0, "centroid lat out of RGV range: %s" % c[1]

        # 4. items() contract
        its = items()
        assert len(its) == n, "items count mismatch"
        req = ("title", "category", "source", "action", "est_value",
               "risk", "location", "url", "confidence")
        for it in its:
            for k in req:
                assert k in it, "item missing key: %s" % k
            assert it["risk"] in ("LOW", "MED", "HIGH"), "bad risk: %s" % it["risk"]
            assert 0.0 <= it["confidence"] <= 1.0, "bad confidence"
            assert it["est_value"] is None or isinstance(it["est_value"], (int, float))
            assert it.get("data_source"), "item missing data_source"
            assert it.get("warning") == PLANNING_WARNING, "item missing planning warning"

        # 4b. GPT-folded hardening: unknown flood zone is conservatively HIGH.
        assert flood_risk("ZZZ") == "HIGH", "unknown zone must be HIGH"
        assert flood_risk("") == "HIGH", "empty zone must be HIGH"
        assert flood_risk(None) == "HIGH", "None zone must be HIGH"
        assert score_parcel({"opportunity_score": 1.0, "flood_zone": "ZZZ"}) == 0.70, \
            "unknown zone discount must be 0.70"

        # 5. PLUGIN shape
        for k in ("id", "name", "category", "authority", "status",
                  "inputs", "outputs", "sources", "safety"):
            assert k in PLUGIN, "PLUGIN missing %s" % k
        assert PLUGIN["status"] == "sample"
        assert PLUGIN["sources"], "PLUGIN.sources empty"

        top = its[0]
        print("OK geoint_gis_parcels selftest")
        print("  parcels        : %d" % n)
        print("  bbox           : [%.4f, %.4f, %.4f, %.4f]" % tuple(b))
        print("  centroid       : [%.4f, %.4f]" % (c[0], c[1]))
        print("  flood risks    : LOW=%d MED=%d HIGH=%d" % (
            sum(1 for i in its if i["risk"] == "LOW"),
            sum(1 for i in its if i["risk"] == "MED"),
            sum(1 for i in its if i["risk"] == "HIGH")))
        print("  top opportunity: %s (score %.2f)" % (top["parcel_id"], top["opportunity_score"]))
        return 0
    except Exception as e:
        print("FAIL geoint_gis_parcels selftest: %s" % e)
        return 1


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GIS Parcel + Hazard Layer (RGV)")
    ap.add_argument("--selftest", action="store_true", help="run health check, exit 0 on success")
    ap.add_argument("--json", action="store_true", help="emit items() as JSON")
    ap.add_argument("--export", action="store_true", help="write scored geojson to 00_PROCESSED")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.export:
        p = export_scored()
        print("wrote %s" % p)
        return 0
    if args.json:
        print(json.dumps(items(), indent=2))
        return 0

    fc = load_parcels()
    print("GIS Parcel + Hazard Layer (RGV) - SAMPLE data")
    print("bbox     :", bbox(fc))
    print("centroid :", centroid(fc))
    print("-" * 72)
    for it in items():
        ev = "n/a" if it["est_value"] is None else ("${:,.0f}".format(it["est_value"]))
        print("[%-4s] %-13s %-11s opp %.2f  %s" % (
            it["risk"], it["parcel_id"], ev, it["opportunity_score"], it["location"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
