#!/usr/bin/env python3
"""Sensor #52 — TxDOT traffic counts and work zones (US-83 / I-2, Starr County / RGV).

Read-only collector, standard library only. No accounts, no API keys, no
spending, no signups. Three legs:

1. AADT (VERIFIED, keyless, live) — TxDOT ArcGIS Online FeatureServer
   ``TxDOT_5_Year_Statewide_AADT_Traffic_Counts`` layer 0
   (``TMB_RPT_SHORT_AADT_HIST``). Stations inside the corridor bounding box
   are fetched; stations within ``CORRIDOR_RADIUS_KM`` of the US-83 / I-2
   polylines are flagged ``corridor_near``. Latest AADT is taken from the
   column matching ``LATEST_AADT_YR``; a missing value stays ``null`` — it is
   never zero-filled.

2. WZDx work zones (BLOCKED-needs-feed) — the current TxDOT WZDx v4.2 feed
   is ``https://api.drivetexas.org/api/conditions.wzdx.geojson`` and requires
   an API key (HTTP 401 without one; USDOT WZDx Feed Registry entry
   ``txdot_v4_2``, ``needapikey: true``). The legacy endpoint
   ``http://txdot-its-c2c.txdot.gov/WZDx/2.0`` returns HTTP 404, and the
   DriveTexas ArcGIS mirrors (``DriveTexas_Points`` / ``DriveTexas_Lines``)
   are live but contain zero features statewide. The collector attempts the
   WZDx fetch unauthenticated (or with ``TXDOT_WZDX_API_KEY`` if the owner
   later provides one via environment — never stored in a file) and records
   the outcome; it never invents work zones.

3. TxDOT highway events (REPORTED, keyless, live) — ArcGIS FeatureServer
   ``Highway_Events_LN`` layer 0. Active events inside the corridor bbox.
   This is a TxDOT-published event feed, NOT the WZDx standard feed, and its
   route names are internal IDs — so observations are labelled REPORTED, not
   VERIFIED, and the canonical WZDx leg stays BLOCKED above.

Every observation carries ``status`` (VERIFIED / REPORTED / UNKNOWN /
BLOCKED), ``source_url`` and ``retrieved_at_utc``.

Usage:
    python3 txdot.py [--out FILE] [--cache-dir DIR] [--no-cache]

Exit code is 0 whenever an output document was written, even if a leg is
blocked — leg status is recorded in the document itself. Exit code 2 only
if no output could be produced at all.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SENSOR_ID = 52
SENSOR_NAME = "txdot-traffic-counts-work-zones"

USER_AGENT = "PineappleSensor52/1.0 (research; public TxDOT data, no key)"

# Corridor bounding box: Starr County + RGV (US-83 Roma->Harlingen, I-2 McAllen->Harlingen).
BBOX = {"xmin": -99.3, "ymin": 26.0, "xmax": -97.6, "ymax": 27.0}
CORRIDOR_RADIUS_KM = 3.0

# US-83 Roma -> Harlingen and I-2 McAllen -> Harlingen, (lon, lat) waypoints.
US83_WAYPOINTS = [
    (-99.017, 26.406), (-98.824, 26.380), (-98.565, 26.281),
    (-98.480, 26.245), (-98.326, 26.216), (-98.230, 26.204),
    (-98.183, 26.197), (-98.155, 26.190), (-98.123, 26.186),
    (-98.062, 26.171), (-97.992, 26.159), (-97.918, 26.149),
    (-97.696, 26.191),
]
I2_WAYPOINTS = [
    (-98.230, 26.204), (-98.183, 26.197), (-98.062, 26.171),
    (-97.992, 26.159), (-97.918, 26.149), (-97.696, 26.191),
]

ARCGIS_BASE = ("https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services")
AADT_URL = (ARCGIS_BASE + "/TxDOT_5_Year_Statewide_AADT_Traffic_Counts"
            "/FeatureServer/0/query")
AADT_LAYER_URL = (ARCGIS_BASE + "/TxDOT_5_Year_Statewide_AADT_Traffic_Counts"
                  "/FeatureServer/0")
HWY_EVENTS_URL = ARCGIS_BASE + "/Highway_Events_LN/FeatureServer/0/query"
DRIVETEXAS_POINTS_URL = ARCGIS_BASE + "/DriveTexas_Points/FeatureServer/0/query"
DRIVETEXAS_LINES_URL = ARCGIS_BASE + "/DriveTexas_Lines/FeatureServer/0/query"

WZDx_URL = "https://api.drivetexas.org/api/conditions.wzdx.geojson"
WZDx_REGISTRY_URL = ("https://data.transportation.gov/resource/69qe-yiui.json"
                     "?$where=feedname='txdot_v4_2'")
WZDx_LEGACY_URL = "http://txdot-its-c2c.txdot.gov/WZDx/2.0"
WZDx_KEY_DOC_URL = "https://api.drivetexas.org/"

# LATEST_AADT_YR -> source column for that year's count.
AADT_YEAR_COLUMNS = {
    2025: "AADT_RPT_QTY",
    2024: "AADT_RPT_HIST_01_QTY",
    2023: "AADT_RPT_HIST_02_QTY",
    2022: "AADT_RPT_HIST_03_QTY",
    2021: "AADT_RPT_HIST_04_QTY",
}
AADT_FIELDS = ("DIST_NM,CNTY_NM,TRFC_STATN_ID,LATEST_AADT_YR,"
               "AADT_RPT_QTY,AADT_RPT_HIST_01_QTY,AADT_RPT_HIST_02_QTY,"
               "AADT_RPT_HIST_03_QTY,AADT_RPT_HIST_04_QTY")
HWY_EVENT_FIELDS = ("route_name,route_prefix_type,roadbed_type,event_type,"
                    "event_status,latitude,longitude,event_created_timestamp,"
                    "event_modified_timestamp,event_retired_timestamp")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get(url: str, params: dict | None = None, timeout: int = 90) -> bytes:
    """GET a URL, returning raw bytes. Raises on HTTP/network error."""
    full = url
    if params:
        full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def arcgis_query(base_url: str, params: dict, timeout: int = 90,
                 fetcher=_http_get, page_size: int = 2000) -> dict:
    """Run an ArcGIS REST query, following pagination (maxRecordCount)."""
    all_features: list = []
    offset = 0
    while True:
        page_params = dict(params)
        page_params.update({
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        })
        raw = fetcher(base_url, page_params, timeout)
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("error"):
            raise RuntimeError(f"ArcGIS error from {base_url}: "
                               f"{payload['error']}")
        feats = payload.get("features", [])
        all_features.extend(feats)
        if len(feats) < page_size:
            break  # short page: no more records
        if not payload.get("exceededTransferLimit"):
            break  # full page but the service says there is nothing more
        offset += len(feats)
        if offset > 200000:  # sanity guard against an endless loop
            raise RuntimeError("ArcGIS pagination exceeded safety limit")
    return {"features": all_features}


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _point_segment_km(lon: float, lat: float,
                      lon1: float, lat1: float,
                      lon2: float, lat2: float) -> float:
    """Distance from a point to a segment, equirectangular approx (fine at corridor scale)."""
    # Project into km around the segment midpoint.
    mid_lat = math.radians((lat1 + lat2) / 2.0)
    kx = 111.32 * math.cos(mid_lat)
    ky = 110.54
    px, py = lon * kx, lat * ky
    ax, ay = lon1 * kx, lat1 * ky
    bx, by = lon2 * kx, lat2 * ky
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_corridor_km(lon: float, lat: float) -> float:
    """Shortest distance (km) from a point to the US-83 / I-2 polylines."""
    best = float("inf")
    for poly in (US83_WAYPOINTS, I2_WAYPOINTS):
        for (lon1, lat1), (lon2, lat2) in zip(poly, poly[1:]):
            best = min(best, _point_segment_km(lon, lat, lon1, lat1, lon2, lat2))
    return best


def parse_aadt_feature(feature: dict, retrieved_at: str) -> dict:
    """One AADT station -> one latest-AADT observation. Missing stays None."""
    attrs = feature.get("attributes", {}) or {}
    geom = feature.get("geometry", {}) or {}
    station_id = attrs.get("TRFC_STATN_ID")
    county = attrs.get("CNTY_NM")
    district = attrs.get("DIST_NM")
    latest_year = attrs.get("LATEST_AADT_YR")
    history = {}
    for year, col in sorted(AADT_YEAR_COLUMNS.items()):
        history[str(year)] = attrs.get(col)  # None stays None: never zero-filled
    latest_aadt = None
    if isinstance(latest_year, int) and latest_year in AADT_YEAR_COLUMNS:
        latest_aadt = attrs.get(AADT_YEAR_COLUMNS[latest_year])
    lon = geom.get("x")
    lat = geom.get("y")
    corridor_km = None
    corridor_near = None
    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
        corridor_km = round(distance_to_corridor_km(lon, lat), 3)
        corridor_near = corridor_km <= CORRIDOR_RADIUS_KM
    status = "VERIFIED" if latest_aadt is not None else "UNKNOWN"
    note = None
    if latest_aadt is None:
        note = ("Station is present in the TxDOT AADT layer but the count "
                f"for its latest year ({latest_year}) is empty in the source; "
                "value left null, not zero-filled.")
    return {
        "metric": "aadt_latest",
        "station_id": station_id,
        "county": county,
        "district": district,
        "latest_aadt_year": latest_year,
        "latest_aadt": latest_aadt,
        "history_aadt": history,
        "lon": lon,
        "lat": lat,
        "corridor_distance_km": corridor_km,
        "corridor_near": corridor_near,
        "unit": "vehicles/day",
        "status": status,
        "note": note,
        "source": "TxDOT ArcGIS — TxDOT_5_Year_Statewide_AADT_Traffic_Counts (TMB_RPT_SHORT_AADT_HIST)",
        "source_url": AADT_LAYER_URL,
        "retrieved_at_utc": retrieved_at,
    }


def fetch_aadt(retrieved_at: str, cache: dict | None = None,
               fetcher=_http_get) -> dict:
    """Fetch AADT stations in the corridor bbox. Returns leg dict."""
    leg = {"name": "aadt", "status": "VERIFIED", "source_url": AADT_LAYER_URL,
           "retrieved_at_utc": retrieved_at, "stations": [],
           "station_count_bbox": 0, "station_count_corridor_near": 0,
           "counties": {}, "latest_years": {}, "error": None}
    try:
        params = {
            "where": "1=1",
            "geometry": f"{BBOX['xmin']},{BBOX['ymin']},{BBOX['xmax']},{BBOX['ymax']}",
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": 4326,
            "outSR": 4326,
            "outFields": AADT_FIELDS,
            "returnGeometry": "true",
        }
        payload = arcgis_query(AADT_URL, params, fetcher=fetcher)
        if cache is not None:
            cache["aadt_raw.json"] = json.dumps(payload).encode("utf-8")
        stations = [parse_aadt_feature(f, retrieved_at)
                    for f in payload.get("features", [])]
        leg["stations"] = stations
        leg["station_count_bbox"] = len(stations)
        leg["station_count_corridor_near"] = sum(
            1 for s in stations if s["corridor_near"])
        for s in stations:
            if s["county"]:
                leg["counties"][s["county"]] = leg["counties"].get(s["county"], 0) + 1
            yr = s["latest_aadt_year"]
            if yr is not None:
                leg["latest_years"][str(yr)] = leg["latest_years"].get(str(yr), 0) + 1
        if not stations:
            leg["status"] = "UNKNOWN"
            leg["error"] = "AADT query returned zero stations in the corridor bbox."
    except Exception as exc:  # noqa: BLE001 — record, don't crash the run
        leg["status"] = "UNKNOWN"
        leg["error"] = f"AADT fetch failed: {exc}"
    return leg


def parse_hwy_event(feature: dict, retrieved_at: str) -> dict:
    """One highway event -> one observation (REPORTED, not WZDx)."""
    attrs = feature.get("attributes", {}) or {}

    def _ms_to_iso(ms):
        if isinstance(ms, (int, float)):
            return datetime.fromtimestamp(ms / 1000.0,
                                          tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return None

    return {
        "metric": "highway_event",
        "route_name": attrs.get("route_name"),
        "route_prefix_type": attrs.get("route_prefix_type"),
        "roadbed_type": attrs.get("roadbed_type"),
        "event_type": attrs.get("event_type"),
        "event_status": attrs.get("event_status"),
        "lat": attrs.get("latitude"),
        "lon": attrs.get("longitude"),
        "created_at_utc": _ms_to_iso(attrs.get("event_created_timestamp")),
        "modified_at_utc": _ms_to_iso(attrs.get("event_modified_timestamp")),
        "retired_at_utc": _ms_to_iso(attrs.get("event_retired_timestamp")),
        "unit": "event",
        "status": "REPORTED",
        "note": ("TxDOT-published highway event feed (ArcGIS mirror), not the "
                 "WZDx standard feed; route names are internal IDs."),
        "source": "TxDOT ArcGIS — Highway_Events_LN",
        "source_url": HWY_EVENTS_URL,
        "retrieved_at_utc": retrieved_at,
    }


def fetch_hwy_events(retrieved_at: str, cache: dict | None = None,
                     fetcher=_http_get) -> dict:
    """Fetch active highway events in the corridor bbox. Returns leg dict."""
    leg = {"name": "highway_events", "status": "REPORTED",
           "source_url": HWY_EVENTS_URL, "retrieved_at_utc": retrieved_at,
           "events": [], "event_count": 0, "error": None}
    try:
        params = {
            "where": "1=1",
            "geometry": f"{BBOX['xmin']},{BBOX['ymin']},{BBOX['xmax']},{BBOX['ymax']}",
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": 4326,
            "outSR": 4326,
            "outFields": HWY_EVENT_FIELDS,
            "returnGeometry": "false",
        }
        payload = arcgis_query(HWY_EVENTS_URL, params, fetcher=fetcher)
        if cache is not None:
            cache["hwy_events_raw.json"] = json.dumps(payload).encode("utf-8")
        events = [parse_hwy_event(f, retrieved_at)
                  for f in payload.get("features", [])]
        events = [e for e in events if e["event_status"] == "Active"]
        leg["events"] = events
        leg["event_count"] = len(events)
        if not events:
            leg["note"] = ("No active highway events in the corridor bbox at "
                           "retrieval time (zero is a real result, not a failure).")
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"Highway-events fetch failed: {exc}"
    return leg


def fetch_wzdx(retrieved_at: str, fetcher=_http_get) -> dict:
    """Attempt the TxDOT WZDx v4.2 feed. No key is configured by default.

    Returns a BLOCKED leg unless the owner has supplied TXDOT_WZDX_API_KEY
    in the environment and the feed answers 200. The key is never written
    to any file.
    """
    leg = {"name": "wzdx_work_zones", "status": "BLOCKED",
           "source_url": WZDx_URL, "retrieved_at_utc": retrieved_at,
           "zones": [], "zone_count": 0, "http_status": None,
           "error": None,
           "owner_step": ("Obtain a free DriveTexas API key at "
                          "https://api.drivetexas.org/ and set it as "
                          "TXDOT_WZDX_API_KEY; no signup has been performed "
                          "by this collector."),
           "registry_url": WZDx_REGISTRY_URL}
    key = os.environ.get("TXDOT_WZDX_API_KEY", "").strip()
    url = WZDx_URL + ("?key=" + urllib.parse.quote(key) if key else "")
    try:
        raw = fetcher(url, None, 90)
        payload = json.loads(raw.decode("utf-8"))
        features = payload.get("features", [])
        leg["status"] = "VERIFIED"
        leg["http_status"] = 200
        leg["zone_count"] = len(features)
        leg["zones"] = features
        leg["error"] = None
        leg["owner_step"] = None
    except urllib.error.HTTPError as exc:
        leg["http_status"] = exc.code
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            body = ""
        leg["error"] = (f"WZDx feed answered HTTP {exc.code} "
                        f"({body.strip() or 'no body'}). Key required per "
                        "USDOT WZDx Feed Registry entry txdot_v4_2 "
                        "(needapikey: true).")
    except Exception as exc:  # noqa: BLE001
        leg["error"] = f"WZDx fetch failed: {exc}"
    return leg


def collect(fetcher=_http_get, cache: dict | None = None) -> dict:
    """Run all three legs and assemble the sensor document."""
    retrieved_at = utc_now_iso()
    aadt = fetch_aadt(retrieved_at, cache=cache, fetcher=fetcher)
    wzdx = fetch_wzdx(retrieved_at, fetcher=fetcher)
    events = fetch_hwy_events(retrieved_at, cache=cache, fetcher=fetcher)

    observations = []
    observations.extend(aadt["stations"])
    observations.extend(events["events"])
    if wzdx["status"] == "BLOCKED":
        observations.append({
            "metric": "wzdx_work_zones",
            "value": None,
            "unit": "work zones",
            "status": "BLOCKED",
            "note": wzdx["error"],
            "owner_step": wzdx["owner_step"],
            "source": "TxDOT WZDx v4.2 feed via DriveTexas API",
            "source_url": WZDx_URL,
            "retrieved_at_utc": retrieved_at,
        })
    else:
        for zone in wzdx["zones"]:
            props = zone.get("properties", {}) or {}
            observations.append({
                "metric": "wzdx_work_zone",
                "zone": props,
                "status": "VERIFIED",
                "source": "TxDOT WZDx v4.2 feed via DriveTexas API",
                "source_url": WZDx_URL,
                "retrieved_at_utc": retrieved_at,
            })

    return {
        "sensor_id": SENSOR_ID,
        "sensor": SENSOR_NAME,
        "corridors": ["US-83 (Roma–Harlingen)", "I-2 (McAllen–Harlingen)"],
        "area": "Starr County / Rio Grande Valley, Texas",
        "bbox": BBOX,
        "corridor_radius_km": CORRIDOR_RADIUS_KM,
        "retrieved_at_utc": retrieved_at,
        "legs": {
            "aadt": {k: v for k, v in aadt.items() if k != "stations"},
            "wzdx_work_zones": {k: v for k, v in wzdx.items() if k != "zones"},
            "highway_events": {k: v for k, v in events.items() if k != "events"},
        },
        "summary": {
            "aadt_stations_bbox": aadt["station_count_bbox"],
            "aadt_stations_corridor_near": aadt["station_count_corridor_near"],
            "aadt_counties": aadt["counties"],
            "aadt_latest_years": aadt["latest_years"],
            "wzdx_zone_count": wzdx["zone_count"],
            "wzdx_status": wzdx["status"],
            "highway_events_active_corridor": events["event_count"],
            "highway_events_status": events["status"],
        },
        "observations": observations,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None,
                        help="Write the JSON document to this file as well as stdout.")
    parser.add_argument("--cache-dir", default=None,
                        help="Directory for raw-response caches (+ .meta.json sidecars).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Do not write raw-response caches.")
    args = parser.parse_args(argv)

    cache: dict | None = None if args.no_cache else {}
    doc = collect(cache=cache)

    if cache is not None and args.cache_dir:
        os.makedirs(args.cache_dir, exist_ok=True)
        for name, payload in cache.items():
            with open(os.path.join(args.cache_dir, name), "wb") as fh:
                fh.write(payload)
            meta = {"retrieved_at_utc": doc["retrieved_at_utc"],
                    "bytes": len(payload)}
            with open(os.path.join(args.cache_dir, name + ".meta.json"),
                      "w", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=1)

    text = json.dumps(doc, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    sys.stderr.write(
        f"[sensor #{SENSOR_ID}] AADT stations: bbox={doc['summary']['aadt_stations_bbox']} "
        f"corridor-near={doc['summary']['aadt_stations_corridor_near']} | "
        f"WZDx: {doc['summary']['wzdx_status']} "
        f"({doc['summary']['wzdx_zone_count']} zones) | "
        f"Highway events active in corridor: "
        f"{doc['summary']['highway_events_active_corridor']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
