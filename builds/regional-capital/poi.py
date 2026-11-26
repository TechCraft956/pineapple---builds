#!/usr/bin/env python3
"""Local POI & business changes — Pineapple sensor #87 (regional capital).

Read-only collector for points of interest (shops, amenities, offices)
in the Roma / Fronton, TX area, from two sources:

1. OpenStreetMap Overpass API (keyless, no signup, $0):
       https://overpass-api.de/api/interpreter
   Nodes, ways and relations tagged shop=*, amenity=* or office=*
   inside a ~0.2-degree bbox around Roma, TX. Elements are returned
   with ``out meta center`` so each one carries its last-edit
   timestamp (the "change" signal) and a centre coordinate for ways
   and relations. Counts by category, names, opening_hours and
   edit recency are emitted as observations.

2. Overture Maps places / buildings (public GeoParquet on S3, no key):
   the STAC catalog is read to record the current release, but the
   data itself is GeoParquet (zstd-compressed) and stdlib Python has
   no Parquet reader. No keyless non-Parquet Overture API exists
   (Overture publishes GeoParquet on S3/Azure plus a STAC index only).
   The Overture leg is therefore BLOCKED-needs-feed until Parquet
   tooling (pyarrow / DuckDB / GDAL) is available — it is recorded,
   never faked, and no non-stdlib dependency is added here.

Labels
------
VERIFIED  element has a category, coordinates, and an edit timestamp.
REPORTED  element has a category but no edit timestamp (real POI;
          edit recency unknown, never guessed).
UNKNOWN   element has no usable category value (defensive; the query
          filters on the tag keys, so this should not occur).
BLOCKED   a whole leg could not be fetched (Overpass unreachable, or
          Overture Parquet tooling missing). Recorded on the leg,
          never as invented observations.

Missing values stay None — never zero-filled, never invented. Every
observation records its source URL and retrieval timestamp (UTC).

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
STAC_CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
OVERTURE_S3_BUCKET = "overturemaps-us-west-2"
OVERTURE_S3_PREFIX_TEMPLATE = "release/{release}/theme={theme}/type={type}/"

# Bbox around Roma, TX: south, west, north, east. Roma city centre
# (26.4094, -99.0145, verified via Nominatim 2026-11-26) sits inside.
# ~0.2 degrees each side, covering Roma / Fronton.
DEFAULT_BBOX = (26.30, -99.11, 26.50, -98.91)

# OSM tag keys that define a place of business / public amenity.
POI_KEYS = ("shop", "amenity", "office")

# Edit-recency windows (days) for the "change" signal.
RECENT_WINDOWS = (90, 180, 365)

# Parquet tooling a future Overture leg would need. Checked at run
# time; all absent in this environment (verified 2026-11-26).
PARQUET_MODULES = ("pyarrow", "duckdb", "osgeo")

SENSOR_ID = "poi-87"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timestamp(value):
    """Parse an ISO-8601 timestamp to an aware datetime, or None."""
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_overpass_query(bbox=DEFAULT_BBOX) -> str:
    """Build the Overpass QL query for POIs inside ``bbox``.

    ``bbox`` is (south, west, north, east). One union arm per element
    type (node / way / relation) and tag key, so ways and relations
    are not silently dropped. ``out meta center`` returns each
    element's last-edit timestamp plus a centre coordinate for ways
    and relations.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    arms = []
    for kind in ("node", "way", "relation"):
        for key in POI_KEYS:
            arms.append(f'  {kind}["{key}"]({box});')
    body = "\n".join(arms)
    return (f"[out:json][timeout:60];\n(\n{body}\n);\n"
            "out meta center;")


def _clean(value):
    """Strip whitespace; empty strings become None (never zero-filled)."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def label_element(obs: dict) -> str:
    if not obs.get("category"):
        return "UNKNOWN"
    if obs.get("last_edited") is None:
        return "REPORTED"
    if obs.get("lat") is None or obs.get("lon") is None:
        return "REPORTED"
    return "VERIFIED"


def build_observation(element: dict, source_url: str,
                      retrieved_at: str, now=None) -> dict:
    """Project one Overpass element onto the emitted observation schema.

    Coordinates come from the node's lat/lon, or from ``center`` for
    ways/relations. Edit recency is computed against ``retrieved_at``
    (or ``now`` when injected by tests); missing timestamps stay None.
    """
    tags = element.get("tags") or {}
    category_key = None
    category_value = None
    for key in POI_KEYS:
        value = _clean(tags.get(key))
        if value is not None:
            category_key = key
            category_value = value
            break
    lat = element.get("lat")
    lon = element.get("lon")
    center = element.get("center") or {}
    if lat is None and center.get("lat") is not None:
        lat = center.get("lat")
    if lon is None and center.get("lon") is not None:
        lon = center.get("lon")
    try:
        lat = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        lat = None
    try:
        lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lon = None
    last_edited = _clean(element.get("timestamp"))
    ref = now or parse_timestamp(retrieved_at) or datetime.now(timezone.utc)
    edited = parse_timestamp(last_edited)
    recency = {}
    for days in RECENT_WINDOWS:
        if edited is None:
            recency[f"edited_within_{days}d"] = None
        else:
            recency[f"edited_within_{days}d"] = (ref - edited).days <= days
    obs = {
        "osm_type": element.get("type"),
        "osm_id": element.get("id"),
        "category": (f"{category_key}:{category_value}"
                     if category_key else None),
        "category_key": category_key,
        "category_value": category_value,
        "name": _clean(tags.get("name")),
        "opening_hours": _clean(tags.get("opening_hours")),
        "lat": lat,
        "lon": lon,
        "last_edited": last_edited,
        "osm_version": element.get("version"),
        "changeset": element.get("changeset"),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs.update(recency)
    obs["label"] = label_element(obs)
    return obs


def parse_overpass_payload(payload: dict) -> list[dict]:
    """Return the raw element list from a decoded Overpass response."""
    if not isinstance(payload, dict):
        return []
    elements = payload.get("elements")
    return elements if isinstance(elements, list) else []


def fetch_overpass(bbox=DEFAULT_BBOX, timeout: int = 90,
                   opener=None) -> dict:
    """POST the POI query to Overpass and return the leg report.

    Returns a dict with ``status`` ("OK" or "ERROR: ..."), the raw
    element count, and the parsed observations. Network/HTTP failures
    are recorded, never raised and never papered over with invented
    elements.
    """
    retrieved_at = utcnow_iso()
    query = build_overpass_query(bbox)
    open_fn = opener or urllib.request.urlopen
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    try:
        req = urllib.request.Request(OVERPASS_URL, data=data, method="POST")
        with open_fn(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        elements = parse_overpass_payload(payload)
        observations = [build_observation(el, OVERPASS_URL, retrieved_at)
                        for el in elements]
        status = "OK"
        error = None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            body = ""
        status = f"ERROR: HTTP {exc.code}"
        error = f"HTTP {exc.code}: {body}".strip()
        elements = []
        observations = []
    except Exception as exc:  # URLError, timeout, bad JSON: recorded
        status = f"ERROR: {type(exc).__name__}: {exc}"
        error = status
        elements = []
        observations = []
    return {
        "leg": "overpass",
        "source_url": OVERPASS_URL,
        "retrieved_at": retrieved_at,
        "bbox": {"south": bbox[0], "west": bbox[1],
                 "north": bbox[2], "east": bbox[3]},
        "query": query,
        "status": status,
        "error": error,
        "elements_returned": len(elements),
        "observations": observations,
    }


def check_parquet_tooling() -> dict:
    """Report which Parquet readers (if any) are importable."""
    return {mod: importlib.util.find_spec(mod) is not None
            for mod in PARQUET_MODULES}


def fetch_overture_leg(opener=None, tooling=None) -> dict:
    """Assess the Overture Maps leg honestly.

    Reads the public STAC catalog (plain JSON, stdlib-readable) to
    record the current release, then checks for Parquet tooling.
    Overture publishes places/buildings as GeoParquet (zstd) on S3 /
    Azure only — there is no keyless non-Parquet API — so with no
    Parquet reader available the leg is BLOCKED-needs-feed. No Parquet
    file is downloaded and no rows are invented.
    """
    retrieved_at = utcnow_iso()
    open_fn = opener or urllib.request.urlopen
    release = None
    stac_status = "OK"
    stac_error = None
    try:
        with open_fn(STAC_CATALOG_URL, timeout=30) as resp:
            catalog = json.loads(resp.read().decode("utf-8", "replace"))
        release = catalog.get("latest") if isinstance(catalog, dict) else None
        if not release:
            stac_status = "ERROR: no 'latest' field in STAC catalog"
            stac_error = stac_status
    except Exception as exc:
        stac_status = f"ERROR: {type(exc).__name__}: {exc}"
        stac_error = stac_status
    available = tooling if tooling is not None else check_parquet_tooling()
    have_reader = any(available.values())
    if have_reader:
        status = "READY-NOT-IMPLEMENTED"
        reason = ("A Parquet reader is available, but no Overture "
                  "GeoParquet reader is implemented in this collector.")
    else:
        status = "BLOCKED-needs-feed"
        reason = ("Overture places/buildings are published only as "
                  "GeoParquet (zstd-compressed) on public S3/Azure; "
                  "there is no keyless non-Parquet API. Stdlib Python "
                  "has no Parquet reader and none of pyarrow / duckdb / "
                  "GDAL (osgeo) is installed here, so no Overture rows "
                  "can be read without adding Parquet tooling.")
    prefix = None
    if release:
        prefix = ("s3://" + OVERTURE_S3_BUCKET + "/" +
                  OVERTURE_S3_PREFIX_TEMPLATE.format(release=release,
                                                     theme="places",
                                                     type="place"))
    return {
        "leg": "overture",
        "source_url": STAC_CATALOG_URL,
        "retrieved_at": retrieved_at,
        "stac_status": stac_status,
        "stac_error": stac_error,
        "latest_release": release,
        "s3_places_prefix": prefix,
        "parquet_tooling": available,
        "status": status,
        "reason": reason,
        "observations": [],
    }


def summarize(observations: list[dict]) -> dict:
    """Aggregate counts for the run summary (no invention)."""
    by_category = Counter(o["category"] for o in observations
                          if o.get("category"))
    by_key = Counter(o["category_key"] for o in observations
                     if o.get("category_key"))
    by_label = {lab: sum(1 for o in observations if o["label"] == lab)
                for lab in ("VERIFIED", "REPORTED", "UNKNOWN")}
    edited = [o["last_edited"] for o in observations if o.get("last_edited")]
    recent = {}
    for days in RECENT_WINDOWS:
        key = f"edited_within_{days}d"
        recent[key] = sum(1 for o in observations
                          if o.get(key) is True)
    return {
        "observations_total": len(observations),
        "by_label": by_label,
        "by_category": dict(sorted(by_category.items(),
                                   key=lambda kv: (-kv[1], kv[0] or ""))),
        "by_key": dict(by_key),
        "named": sum(1 for o in observations if o.get("name")),
        "with_opening_hours": sum(1 for o in observations
                                  if o.get("opening_hours")),
        "recent_edits": recent,
        "edit_timestamp_range": [min(edited, default=None),
                                 max(edited, default=None)],
    }


def fetch_observations(bbox=DEFAULT_BBOX, timeout: int = 90,
                       opener=None, overture_opener=None,
                       tooling=None) -> dict:
    """Run both legs and return the full result document."""
    retrieved_at = utcnow_iso()
    overpass = fetch_overpass(bbox=bbox, timeout=timeout, opener=opener)
    overture = fetch_overture_leg(opener=overture_opener, tooling=tooling)
    observations = overpass["observations"]
    observations.sort(key=lambda o: (o["category"] or "",
                                     o["name"] or "",
                                     o["osm_type"] or "",
                                     o["osm_id"] or 0))
    overpass_blocked = overpass["status"] != "OK"
    return {
        "sensor": SENSOR_ID,
        "source": ("OpenStreetMap Overpass API (POIs) + "
                   "Overture Maps STAC catalog (release check only)"),
        "retrieved_at": retrieved_at,
        "bbox": {"south": bbox[0], "west": bbox[1],
                 "north": bbox[2], "east": bbox[3]},
        "bbox_note": ("~0.2-degree box around Roma, TX "
                      "(city centre 26.4094, -99.0145); covers Roma / "
                      "Fronton area."),
        "legs": {
            "overpass": {k: v for k, v in overpass.items()
                         if k != "observations"},
            "overture": overture,
        },
        "overpass_blocked": overpass_blocked,
        "overture_blocked": overture["status"].startswith("BLOCKED"),
        "summary": summarize(observations),
        "observations": observations,
    }


def parse_bbox(text: str):
    parts = text.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "bbox must be 'south,west,north,east'")
    try:
        values = tuple(float(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "bbox values must be numbers")
    south, west, north, east = values
    if not (south < north and west < east):
        raise argparse.ArgumentTypeError(
            "bbox must satisfy south < north and west < east")
    return values


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch local POIs (shops/amenities/offices) for the "
                    "Roma, TX area via OSM Overpass; check the Overture "
                    "Maps release (Parquet leg is tooling-blocked).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--bbox", type=parse_bbox, default=DEFAULT_BBOX,
                    help="south,west,north,east (default: "
                         "26.30,-99.11,26.50,-98.91).")
    ap.add_argument("--timeout", type=int, default=90,
                    help="Overpass request timeout in seconds.")
    args = ap.parse_args(argv)
    result = fetch_observations(bbox=args.bbox, timeout=args.timeout)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"(overpass: {result['legs']['overpass']['status']}; "
              f"overture: {result['legs']['overture']['status']})")
    else:
        print(text)
    # Non-zero when the primary (Overpass) leg is blocked, mirroring
    # usaspending.py: the run document itself still records the block.
    return 2 if result["overpass_blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
