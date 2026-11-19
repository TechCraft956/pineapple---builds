"""adapters/run_live.py — live adapter run (Task 2).

Pulls a small bounded set of real parcels per county, joins FEMA NFHL
flood zones, and writes canonical module-loadable GeoJSON to ../live/.

  python -m adapters.run_live [--limit N] [--skip-fema]

County sources (verified live 2026-11-17; see BUILD_REPORT.md):
  Starr    — BIS FeatureServer StarrCADWebService/0, Roma envelope.
  Willacy  — BIS FeatureServer WillacyCADWebService/0, Raymondville envelope.
  Hidalgo  — own AD REST walled (gis.hidalgoad.org = bare Tomcat; appraisal
             data via True Automation PropAccess JS portal, no REST) ->
             TxGIO StratMap identify grid over central McAllen.
  Cameron  — cad site unreachable via curl (https 000 / http 403) ->
             TxGIO StratMap identify grid over Brownsville.

Every parcel carries data_source + retrieved_at_utc + source_url; every
FEMA join records flood_join_method + flood_caveat. Raw responses are
cached to ../cache/ with retrieved_at_utc + source URL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))

from adapters import client  # noqa: E402
from adapters import fema, mapping, stratmap  # noqa: E402

STARR_SERVICE = ("https://utility.arcgis.com/usrsvcs/servers/"
                 "ff05af4293474b45abf39075250efe78/rest/services/"
                 "StarrCADWebService/FeatureServer")
WILLACY_SERVICE = ("https://utility.arcgis.com/usrsvcs/servers/"
                   "4bc982f495e848eca3b3433a64288e14/rest/services/"
                   "WillacyCADWebService/FeatureServer")

BIS_FIELDS = ("prop_id,prop_id_text,file_as_name,geo_id,legal_acreage,market,"
              "land_val,imprv_val,city,county,situs_street,situs_city,"
              "legal_desc,hood_cd")

# Bounded live pulls (small envelopes, capped record counts).
PULLS = [
    {"key": "starr", "county": "Starr", "source": "bis",
     "service": STARR_SERVICE, "bbox": (-99.02, 26.39, -98.98, 26.42)},
    {"key": "willacy", "county": "Willacy", "source": "bis",
     "service": WILLACY_SERVICE, "bbox": (-97.80, 26.47, -97.76, 26.49)},
    {"key": "hidalgo", "county": "Hidalgo", "source": "stratmap",
     "bbox": (-98.25, 26.20, -98.22, 26.22)},
    {"key": "cameron", "county": "Cameron", "source": "stratmap",
     "bbox": (-97.52, 25.96, -97.48, 25.98)},
]


def pull_bis(pull: dict, limit: int):
    params = {
        "where": "1=1",
        "outFields": BIS_FIELDS,
        "geometry": "%s,%s,%s,%s" % pull["bbox"],
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "f": "geojson",
        "resultRecordCount": str(limit),
    }
    import urllib.parse
    url = pull["service"] + "/0/query?" + urllib.parse.urlencode(params)
    payload = client.fetch_json(url)
    client.cache_response("bis_%s_raw" % pull["key"], url, payload)
    feats = payload.get("features", [])
    stamp = client.utcnow()
    return [mapping.map_bis_feature(f, pull["county"],
                                    "%s_cad_live" % pull["key"], stamp, url)
            for f in feats]


def pull_stratmap(pull: dict, limit: int):
    results = stratmap.identify_grid(pull["bbox"], nx=3, ny=3)
    stamp = client.utcnow()
    source_url = stratmap.STRATMAP_BASE + "/identify (grid %s)" % (pull["bbox"],)
    client.cache_response("stratmap_%s_raw" % pull["key"], source_url,
                          {"grid_bbox": pull["bbox"], "results": results})
    feats = [mapping.map_stratmap_result(r, pull["county"],
                                         "stratmap_live", stamp, source_url)
             for r in results]
    feats = [f for f in feats if f.get("geometry")]
    return feats[:limit]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GEOINT live adapter run")
    ap.add_argument("--limit", type=int, default=5, help="max parcels per county")
    ap.add_argument("--skip-fema", action="store_true",
                    help="skip the live FEMA join (fixtures only)")
    args = ap.parse_args(argv)

    live_dir = WORKSPACE / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    all_features = []
    summary = {}
    for pull in PULLS:
        try:
            if pull["source"] == "bis":
                feats = pull_bis(pull, args.limit)
            else:
                feats = pull_stratmap(pull, args.limit)
        except Exception as e:
            print("FAIL %s: %s" % (pull["key"], e))
            summary[pull["key"]] = {"error": str(e)}
            continue
        if not args.skip_fema:
            for f in feats:
                try:
                    fema.join_flood_zone(f)
                except Exception as e:
                    print("FEMA join failed for %s: %s"
                          % (f["properties"].get("parcel_id"), e))
                    f["properties"]["flood_zone"] = None
                    f["properties"]["flood_join_method"] = "join_error"
                    f["properties"]["flood_caveat"] = "FEMA join failed: %s" % e
        fc = {
            "type": "FeatureCollection",
            "name": "rgv_parcels_live_%s" % pull["key"],
            "_status": "live",
            "_warning": ("PLANNING SIGNAL ONLY — not authoritative title, "
                         "valuation, or flood determination. Verify against "
                         "county AD records and FEMA NFHL before acting."),
            "features": feats,
        }
        path = live_dir / ("%s.geojson" % pull["key"])
        path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
        all_features.extend(feats)
        summary[pull["key"]] = {
            "parcels": len(feats),
            "zones": {z: sum(1 for f in feats
                             if f["properties"].get("flood_zone") == z)
                      for z in sorted({f["properties"].get("flood_zone")
                                      for f in feats})},
            "methods": {m: sum(1 for f in feats
                               if f["properties"].get("flood_join_method") == m)
                        for m in sorted({f["properties"].get("flood_join_method")
                                        for f in feats})},
            "file": str(path),
        }
        print("%s: %d parcels -> %s" % (pull["key"], len(feats), path))

    combined = {
        "type": "FeatureCollection",
        "name": "rgv_parcels_live_all",
        "_status": "live",
        "_warning": ("PLANNING SIGNAL ONLY — not authoritative title, "
                     "valuation, or flood determination. Verify against "
                     "county AD records and FEMA NFHL before acting."),
        "features": all_features,
    }
    combined_path = live_dir / "all_live.geojson"
    combined_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print("combined: %d parcels -> %s" % (len(all_features), combined_path))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
