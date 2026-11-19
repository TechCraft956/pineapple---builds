"""adapters/fema.py — FEMA NFHL flood-zone join.

Service verified live 2026-11-17:
  https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
  layer 28 "Flood Hazard Zones" (esriGeometryPolygon, maxRecordCount 2000)
  fields include FLD_ZONE (zone code), ZONE_SUBTY, SFHA_TF, DFIRM_ID.
  /28/query?f=geojson with an envelope + inSR=4326/outSR=4326 returns the
  zone polygons intersecting the envelope. Live evidence: AE polygons for
  coastal Cameron County (DFIRM 48061C); 808 X-polygons in an RGV-wide bbox;
  a central-McAllen envelope returns 0 polygons — high-ground areas are
  simply not polygonized in layer 28, which the join records honestly
  instead of treating absence as a polygon-confirmed X.

Join semantics (GPT-folded hardening, BUILD-20261117-005):
  * The parcel bbox envelope is queried; the parcel centroid is tested
    point-in-polygon against the returned zone polygons.
  * method "centroid_in_polygon": centroid falls inside one zone polygon.
    The record carries the caveat "partial coverage — centroid only, cannot
    establish parcel-wide hazard". A parcel-wide hazard claim requires
    polygon intersection, not a centroid point.
  * method "polygon_contained": every parcel vertex lies inside the SAME
    zone polygon — only then is the zone treated as parcel-wide.
  * method "no_intersection": no NFHL polygon intersects the parcel bbox.
    flood_zone is recorded as "X" (inferred — outside mapped SFHA), with
    the caveat "no NFHL polygon intersected — verify on FEMA FIRMette;
    zone X inferred, not polygon-confirmed". It is NOT a polygon-confirmed X.
  * A zone code outside the module's discount table (e.g. "D") is kept
    verbatim; the patched module scores it conservatively HIGH (0.70).
"""
from __future__ import annotations

import urllib.parse

from .client import arcgis_query, fetch_json

NFHL_BASE = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
NFHL_LAYER = 28
FEMA_FIELDS = "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID,FLD_AR_ID"

CAVEAT_CENTROID = ("partial coverage — centroid only, cannot establish "
                   "parcel-wide hazard")
CAVEAT_NO_POLYGON = ("no NFHL polygon intersected — verify on FEMA FIRMette; "
                     "zone X inferred, not polygon-confirmed")


def point_in_ring(point, ring) -> bool:
    """Ray-casting point-in-polygon for one linear ring (lon/lat)."""
    x, y = point
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xinters = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xinters:
                inside = not inside
    return inside


def point_in_polygon(point, geometry: dict) -> bool:
    """True if point is inside a GeoJSON Polygon (holes excluded) / MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        if not coords or not point_in_ring(point, coords[0]):
            return False
        return not any(point_in_ring(point, hole) for hole in coords[1:])
    if gtype == "MultiPolygon":
        return any(point_in_polygon(point, {"type": "Polygon", "coordinates": poly})
                   for poly in coords)
    return False


def _feature_centroid(feature: dict):
    """Mean of vertices (same representative point as gis_parcels._feature_point)."""
    pts = []

    def walk(coords, depth):
        if depth == 0:
            pts.append((coords[0], coords[1]))
            return
        for c in coords:
            walk(c, depth - 1)

    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    depth = {"Point": 0, "MultiPoint": 1, "LineString": 1,
             "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}.get(gtype)
    if depth is None or not coords:
        return None
    walk(coords, depth)
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _feature_vertices(feature: dict):
    pts = []

    def walk(coords, depth):
        if depth == 0:
            pts.append((coords[0], coords[1]))
            return
        for c in coords:
            walk(c, depth - 1)

    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    depth = {"Polygon": 2, "MultiPolygon": 3}.get(geom.get("type"))
    if depth is None:
        return []
    walk(coords, depth)
    return pts


def _feature_bbox(feature: dict):
    pts = _feature_vertices(feature)
    if not pts:
        centroid = _feature_centroid(feature)
        if centroid is None:
            return None
        return (centroid[0], centroid[1], centroid[0], centroid[1])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def query_zones_for_bbox(bbox, out_fields: str = FEMA_FIELDS) -> dict:
    """Query NFHL layer 28 for zone polygons intersecting a lon/lat bbox."""
    params = {
        "where": "1=1",
        "outFields": out_fields,
        "geometry": "%s,%s,%s,%s" % bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "f": "geojson",
        "resultRecordCount": "2000",
    }
    url = ("%s/%d/query?%s" % (NFHL_BASE, NFHL_LAYER, urllib.parse.urlencode(params)))
    return fetch_json(url)


def join_flood_zone(feature: dict, zones_fc: dict | None = None) -> dict:
    """Join a FEMA zone onto one canonical parcel feature (mutates props).

    Returns the feature. Sets flood_zone, flood_join_method, flood_caveat,
    and fema_* provenance on properties. If zones_fc is None the live NFHL
    endpoint is queried for the parcel bbox.
    """
    props = feature.setdefault("properties", {})
    bbox = _feature_bbox(feature)
    if bbox is None:
        props["flood_zone"] = None
        props["flood_join_method"] = "no_geometry"
        props["flood_caveat"] = "parcel has no usable geometry; flood zone unknown"
        return feature
    if zones_fc is None:
        zones_fc = query_zones_for_bbox(bbox)
    zones = zones_fc.get("features", []) if isinstance(zones_fc, dict) else []
    centroid = _feature_centroid(feature)
    if centroid is None:
        props["flood_zone"] = None
        props["flood_join_method"] = "no_geometry"
        props["flood_caveat"] = "parcel has no usable geometry; flood zone unknown"
        return feature
    if not zones:
        props["flood_zone"] = "X"
        props["flood_join_method"] = "no_intersection"
        props["flood_caveat"] = CAVEAT_NO_POLYGON
        props["fema_dfirm_id"] = None
        return feature
    hit = None
    for zf in zones:
        zgeom = zf.get("geometry") or {}
        if zgeom.get("type") in ("Polygon", "MultiPolygon") and point_in_polygon(centroid, zgeom):
            hit = zf
            break
    if hit is None:
        # Polygons intersect the bbox but the centroid is in none of them:
        # the parcel straddles a zone boundary (or sits in an unmapped gap).
        props["flood_zone"] = "X"
        props["flood_join_method"] = "no_intersection"
        props["flood_caveat"] = ("NFHL polygons intersect the parcel bbox but the "
                                 "centroid falls in none — zone X inferred, not "
                                 "polygon-confirmed; verify on FEMA FIRMette")
        props["fema_dfirm_id"] = None
        return feature
    zprops = hit.get("properties", {}) or {}
    zone = str(zprops.get("FLD_ZONE", "")).strip().upper()
    props["flood_zone"] = zone or None
    props["fema_dfirm_id"] = zprops.get("DFIRM_ID")
    props["fema_sfha"] = zprops.get("SFHA_TF")
    props["fema_zone_subty"] = zprops.get("ZONE_SUBTY")
    # Parcel-wide only if every vertex is inside the SAME zone polygon.
    vertices = _feature_vertices(feature)
    hit_geom = hit.get("geometry") or {}
    if vertices and all(point_in_polygon(v, hit_geom) for v in vertices):
        props["flood_join_method"] = "polygon_contained"
        props["flood_caveat"] = None
    else:
        props["flood_join_method"] = "centroid_in_polygon"
        props["flood_caveat"] = CAVEAT_CENTROID
    return feature
