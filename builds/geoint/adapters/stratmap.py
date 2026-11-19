"""adapters/stratmap.py — TxGIO StratMap fallback adapter (Hidalgo + Cameron).

Verified live 2026-11-17: the StratMap MapServer layer 0
  https://feature.geographic.texas.gov/arcgis/rest/services/Parcels/
  stratmap_land_parcels_48_most_recent/MapServer/0
("StratMap Land Parcels 48 Most Recent", maxRecordCount 2000) does NOT
return features for /0/query with an envelope (0 features for central
McAllen and central Austin; attribute-only query -> HTTP 200 with 400
"Requested operation is not supported by this service"). The working path
is /MapServer/identify at a point (verified: a McAllen point returned a
Hidalgo parcel, SOURCE "HIDALGO APPRAISAL DISTRICT", TAX_YEAR 2026; a
Brownsville point returned a Cameron parcel). This adapter therefore pulls
via an identify point grid over a bbox and dedupes by PROP_ID.
"""
from __future__ import annotations

import urllib.parse

from .client import fetch_json

STRATMAP_BASE = ("https://feature.geographic.texas.gov/arcgis/rest/services/"
                 "Parcels/stratmap_land_parcels_48_most_recent/MapServer")


def identify_point(lon: float, lat: float, bbox, tolerance: int = 5) -> dict:
    """Identify parcels at one point. bbox is the map extent for scale."""
    params = {
        "geometry": "%s,%s" % (lon, lat),
        "geometryType": "esriGeometryPoint",
        "sr": "4326",
        "layers": "all:0",
        "tolerance": str(tolerance),
        "mapExtent": "%s,%s,%s,%s" % bbox,
        "imageDisplay": "800,600,96",
        "returnGeometry": "true",
        "f": "json",
    }
    url = STRATMAP_BASE + "/identify?" + urllib.parse.urlencode(params)
    return fetch_json(url)


def identify_grid(bbox, nx: int = 3, ny: int = 3) -> list:
    """Identify parcels at an nx*ny grid over a lon/lat bbox. Dedupes by PROP_ID.

    Returns the raw identify result dicts (attributes + geometry).
    """
    xmin, ymin, xmax, ymax = bbox
    seen: dict[str, dict] = {}
    for ix in range(nx):
        lon = xmin + (xmax - xmin) * (ix + 0.5) / nx
        for iy in range(ny):
            lat = ymin + (ymax - ymin) * (iy + 0.5) / ny
            payload = identify_point(lon, lat, bbox)
            for res in payload.get("results", []):
                pid = str((res.get("attributes") or {}).get("PROP_ID"))
                if pid and pid not in seen:
                    seen[pid] = res
    return list(seen.values())
