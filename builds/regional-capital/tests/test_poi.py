"""Tests for poi.py (sensor #87). Stdlib unittest only, no network.

Run:  python3 -m unittest discover -s tests -v
from builds/regional-capital/
"""

import json
import sys
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import poi  # noqa: E402

NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)
RETRIEVED = "2026-11-26T12:00:00Z"

NODE_SHOP = {
    "type": "node", "id": 111, "lat": 26.405, "lon": -99.01,
    "timestamp": "2026-11-01T10:00:00Z", "version": 3, "changeset": 9001,
    "tags": {"shop": "convenience", "name": "Roma Mini Mart",
             "opening_hours": "Mo-Sa 08:00-20:00"},
}

WAY_AMENITY = {
    "type": "way", "id": 222,
    "center": {"lat": 26.41, "lon": -99.02},
    "timestamp": "2025-06-15T08:30:00Z", "version": 1, "changeset": 8001,
    "tags": {"amenity": "restaurant", "name": "Fronton Cafe"},
}

NODE_NO_TIMESTAMP = {
    "type": "node", "id": 333, "lat": 26.42, "lon": -99.0,
    "version": 2, "changeset": 7001,
    "tags": {"office": "lawyer"},
}

NODE_NO_CATEGORY = {
    "type": "node", "id": 444, "lat": 26.42, "lon": -99.0,
    "timestamp": "2026-10-01T00:00:00Z",
    "tags": {"name": "Mystery Place"},
}

OVERPASS_PAYLOAD = {
    "version": 0.6,
    "generator": "Overpass API",
    "elements": [NODE_SHOP, WAY_AMENITY, NODE_NO_TIMESTAMP],
}

STAC_PAYLOAD = {"latest": "2026-11-18.0", "id": "overturemaps"}


class FakeResp:
    """Minimal urlopen stand-in returning canned bytes."""

    def __init__(self, payload_bytes):
        self._payload = payload_bytes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def json_opener(payload):
    data = json.dumps(payload).encode("utf-8")
    return lambda req, timeout=None: FakeResp(data)


class TestQueryBuilder(unittest.TestCase):
    def test_query_covers_all_kinds_and_keys(self):
        q = poi.build_overpass_query()
        for kind in ("node", "way", "relation"):
            for key in ("shop", "amenity", "office"):
                self.assertIn(f'{kind}["{key}"]', q)
        self.assertIn("(26.3,-99.11,26.5,-98.91)", q)
        self.assertIn("out meta center;", q)

    def test_query_uses_given_bbox(self):
        q = poi.build_overpass_query((26.0, -99.5, 26.6, -98.5))
        self.assertIn("(26.0,-99.5,26.6,-98.5)", q)

    def test_default_bbox_contains_roma_centre(self):
        south, west, north, east = poi.DEFAULT_BBOX
        self.assertLess(south, 26.4094)
        self.assertLess(26.4094, north)
        self.assertLess(west, -99.0145)
        self.assertLess(-99.0145, east)


class TestObservationBuilding(unittest.TestCase):
    def test_node_shop_verified(self):
        o = poi.build_observation(NODE_SHOP, poi.OVERPASS_URL, RETRIEVED,
                                  now=NOW)
        self.assertEqual(o["label"], "VERIFIED")
        self.assertEqual(o["category"], "shop:convenience")
        self.assertEqual(o["category_key"], "shop")
        self.assertEqual(o["name"], "Roma Mini Mart")
        self.assertEqual(o["opening_hours"], "Mo-Sa 08:00-20:00")
        self.assertEqual(o["lat"], 26.405)
        self.assertEqual(o["lon"], -99.01)
        self.assertEqual(o["last_edited"], "2026-11-01T10:00:00Z")
        self.assertEqual(o["osm_version"], 3)
        self.assertEqual(o["changeset"], 9001)

    def test_recent_flags_against_retrieval_time(self):
        o = poi.build_observation(NODE_SHOP, poi.OVERPASS_URL, RETRIEVED,
                                  now=NOW)
        self.assertTrue(o["edited_within_90d"])   # 25 days old
        self.assertTrue(o["edited_within_180d"])
        self.assertTrue(o["edited_within_365d"])
        old = poi.build_observation(WAY_AMENITY, poi.OVERPASS_URL, RETRIEVED,
                                    now=NOW)
        self.assertFalse(old["edited_within_90d"])  # ~529 days old
        self.assertFalse(old["edited_within_180d"])
        self.assertFalse(old["edited_within_365d"])

    def test_way_uses_center_coordinates(self):
        o = poi.build_observation(WAY_AMENITY, poi.OVERPASS_URL, RETRIEVED,
                                  now=NOW)
        self.assertEqual(o["label"], "VERIFIED")
        self.assertEqual(o["category"], "amenity:restaurant")
        self.assertEqual(o["lat"], 26.41)
        self.assertEqual(o["lon"], -99.02)

    def test_missing_timestamp_is_reported_not_invented(self):
        o = poi.build_observation(NODE_NO_TIMESTAMP, poi.OVERPASS_URL,
                                  RETRIEVED, now=NOW)
        self.assertEqual(o["label"], "REPORTED")
        self.assertIsNone(o["last_edited"])
        self.assertIsNone(o["edited_within_90d"])
        self.assertIsNone(o["edited_within_180d"])
        self.assertIsNone(o["edited_within_365d"])
        self.assertIsNone(o["name"])  # unnamed POI: null, not invented

    def test_missing_category_is_unknown(self):
        o = poi.build_observation(NODE_NO_CATEGORY, poi.OVERPASS_URL,
                                  RETRIEVED, now=NOW)
        self.assertEqual(o["label"], "UNKNOWN")
        self.assertIsNone(o["category"])

    def test_shop_takes_priority_over_amenity(self):
        el = {"type": "node", "id": 555, "lat": 26.4, "lon": -99.0,
              "timestamp": "2026-11-20T00:00:00Z",
              "tags": {"shop": "bakery", "amenity": "cafe"}}
        o = poi.build_observation(el, poi.OVERPASS_URL, RETRIEVED, now=NOW)
        self.assertEqual(o["category"], "shop:bakery")


class TestOverpassFetch(unittest.TestCase):
    def test_fetch_parses_elements(self):
        leg = poi.fetch_overpass(opener=json_opener(OVERPASS_PAYLOAD))
        self.assertEqual(leg["status"], "OK")
        self.assertEqual(leg["elements_returned"], 3)
        self.assertEqual(len(leg["observations"]), 3)
        labels = [o["label"] for o in leg["observations"]]
        self.assertEqual(labels.count("VERIFIED"), 2)
        self.assertEqual(labels.count("REPORTED"), 1)
        self.assertIn("out meta center;", leg["query"])

    def test_fetch_http_error_recorded_not_raised(self):
        def boom(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 406,
                                         "Not Acceptable", {}, None)

        leg = poi.fetch_overpass(opener=boom)
        self.assertEqual(leg["status"], "ERROR: HTTP 406")
        self.assertEqual(leg["observations"], [])
        self.assertEqual(leg["elements_returned"], 0)

    def test_fetch_connection_error_recorded_not_raised(self):
        def boom(req, timeout=None):
            raise ConnectionError("no network")

        leg = poi.fetch_overpass(opener=boom)
        self.assertTrue(leg["status"].startswith("ERROR:"))
        self.assertEqual(leg["observations"], [])

    def test_empty_elements_is_ok_with_zero_observations(self):
        leg = poi.fetch_overpass(opener=json_opener({"elements": []}))
        self.assertEqual(leg["status"], "OK")
        self.assertEqual(leg["observations"], [])


class TestOvertureLeg(unittest.TestCase):
    def test_blocked_without_parquet_tooling(self):
        leg = poi.fetch_overture_leg(
            opener=json_opener(STAC_PAYLOAD),
            tooling={"pyarrow": False, "duckdb": False, "osgeo": False})
        self.assertEqual(leg["status"], "BLOCKED-needs-feed")
        self.assertEqual(leg["latest_release"], "2026-11-18.0")
        self.assertIn("2026-11-18.0", leg["s3_places_prefix"])
        self.assertIn("places", leg["s3_places_prefix"])
        self.assertEqual(leg["observations"], [])
        self.assertIn("Parquet", leg["reason"])

    def test_ready_flag_when_tooling_present_but_unimplemented(self):
        leg = poi.fetch_overture_leg(
            opener=json_opener(STAC_PAYLOAD),
            tooling={"pyarrow": True, "duckdb": False, "osgeo": False})
        self.assertEqual(leg["status"], "READY-NOT-IMPLEMENTED")
        self.assertEqual(leg["observations"], [])

    def test_stac_failure_recorded(self):
        def boom(url, timeout=None):
            raise ConnectionError("no network")

        leg = poi.fetch_overture_leg(opener=boom, tooling={
            "pyarrow": False, "duckdb": False, "osgeo": False})
        self.assertIsNone(leg["latest_release"])
        self.assertTrue(leg["stac_status"].startswith("ERROR:"))
        self.assertEqual(leg["status"], "BLOCKED-needs-feed")


class TestSummaryAndAssembly(unittest.TestCase):
    def test_summary_counts(self):
        obs = [poi.build_observation(el, poi.OVERPASS_URL, RETRIEVED,
                                     now=NOW)
               for el in (NODE_SHOP, WAY_AMENITY, NODE_NO_TIMESTAMP)]
        s = poi.summarize(obs)
        self.assertEqual(s["observations_total"], 3)
        self.assertEqual(s["by_label"], {"VERIFIED": 2, "REPORTED": 1,
                                         "UNKNOWN": 0})
        self.assertEqual(s["by_category"],
                         {"shop:convenience": 1,
                          "amenity:restaurant": 1,
                          "office:lawyer": 1})
        self.assertEqual(s["by_key"], {"shop": 1, "amenity": 1,
                                       "office": 1})
        self.assertEqual(s["named"], 2)
        self.assertEqual(s["with_opening_hours"], 1)
        self.assertEqual(s["recent_edits"]["edited_within_90d"], 1)
        self.assertEqual(s["recent_edits"]["edited_within_365d"], 1)
        self.assertEqual(s["edit_timestamp_range"],
                         ["2025-06-15T08:30:00Z", "2026-11-01T10:00:00Z"])

    def test_fetch_observations_assembles_both_legs(self):
        doc = poi.fetch_observations(
            opener=json_opener(OVERPASS_PAYLOAD),
            overture_opener=json_opener(STAC_PAYLOAD),
            tooling={"pyarrow": False, "duckdb": False, "osgeo": False})
        self.assertEqual(doc["sensor"], "poi-87")
        self.assertFalse(doc["overpass_blocked"])
        self.assertTrue(doc["overture_blocked"])
        self.assertEqual(doc["summary"]["observations_total"], 3)
        self.assertEqual(doc["legs"]["overture"]["latest_release"],
                         "2026-11-18.0")
        # Observations sorted by category then name.
        self.assertEqual([o["category"] for o in doc["observations"]],
                         ["amenity:restaurant", "office:lawyer",
                          "shop:convenience"])

    def test_fetch_observations_blocked_overpass(self):
        def boom(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 406,
                                         "Not Acceptable", {}, None)

        doc = poi.fetch_observations(
            opener=boom, overture_opener=json_opener(STAC_PAYLOAD),
            tooling={"pyarrow": False, "duckdb": False, "osgeo": False})
        self.assertTrue(doc["overpass_blocked"])
        self.assertEqual(doc["summary"]["observations_total"], 0)
        self.assertIsNone(doc["summary"]["edit_timestamp_range"][0])

    def test_parse_bbox_valid_and_invalid(self):
        self.assertEqual(poi.parse_bbox("26.30,-99.11,26.50,-98.91"),
                         (26.30, -99.11, 26.50, -98.91))
        import argparse as _ap
        with self.assertRaises(_ap.ArgumentTypeError):
            poi.parse_bbox("26.30,-99.11")
        with self.assertRaises(_ap.ArgumentTypeError):
            poi.parse_bbox("26.50,-99.11,26.30,-98.91")


if __name__ == "__main__":
    unittest.main()
