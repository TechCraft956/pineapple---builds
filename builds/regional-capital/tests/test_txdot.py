"""Tests for sensor #52 (TxDOT traffic counts / work zones) — stdlib unittest.

Fixture-based; no network is touched by these tests. Fixtures are trimmed
captures of the live TxDOT ArcGIS payloads (2026-11-26) plus the literal
HTTP 401 body the DriveTexas WZDx feed returns without an API key.
"""
import io
import json
import os
import sys
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import txdot  # noqa: E402

RETRIEVED = "2026-11-26T18:00:00Z"


def load_fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


def station_by_id(stations, station_id):
    return [s for s in stations if s["station_id"] == station_id][0]


class TestAadtParsing(unittest.TestCase):
    def setUp(self):
        self.payload = load_fixture("aadt_sample.json")
        self.stations = [txdot.parse_aadt_feature(f, RETRIEVED)
                         for f in self.payload["features"]]

    def test_latest_year_2025_uses_current_column(self):
        s = station_by_id(self.stations, "109HP131")
        self.assertEqual(s["latest_aadt_year"], 2025)
        self.assertEqual(s["latest_aadt"], 1468)
        self.assertEqual(s["status"], "VERIFIED")
        self.assertEqual(s["history_aadt"]["2023"], 2717)

    def test_latest_year_2024_uses_hist01_column(self):
        s = station_by_id(self.stations, "109CE101")
        self.assertEqual(s["latest_aadt_year"], 2024)
        self.assertEqual(s["latest_aadt"], 859)
        self.assertEqual(s["status"], "VERIFIED")

    def test_latest_year_2022_uses_hist03_column(self):
        s = station_by_id(self.stations, "109CR114")
        self.assertEqual(s["latest_aadt_year"], 2022)
        self.assertEqual(s["latest_aadt"], 67)

    def test_missing_values_stay_none_never_zero_filled(self):
        s = station_by_id(self.stations, "109CE101")
        # 2025 column is empty in the source for this 2024-latest station.
        self.assertIsNone(s["history_aadt"]["2025"])
        self.assertIsNone(s["history_aadt"]["2023"])
        self.assertIsNone(s["history_aadt"]["2022"])
        self.assertIsNone(s["history_aadt"]["2021"])

    def test_station_with_no_counts_is_unknown_not_zero(self):
        feat = {"attributes": {
            "DIST_NM": "Pharr", "CNTY_NM": "Starr",
            "TRFC_STATN_ID": "999XX000", "LATEST_AADT_YR": 2024,
            "AADT_RPT_QTY": None, "AADT_RPT_HIST_01_QTY": None,
            "AADT_RPT_HIST_02_QTY": None, "AADT_RPT_HIST_03_QTY": None,
            "AADT_RPT_HIST_04_QTY": None},
            "geometry": {"x": -98.824, "y": 26.380}}
        s = txdot.parse_aadt_feature(feat, RETRIEVED)
        self.assertIsNone(s["latest_aadt"])
        self.assertEqual(s["status"], "UNKNOWN")
        self.assertIn("not zero-filled", s["note"])

    def test_year_outside_window_is_unknown(self):
        feat = {"attributes": {
            "DIST_NM": "Pharr", "CNTY_NM": "Starr",
            "TRFC_STATN_ID": "999XX001", "LATEST_AADT_YR": 2020,
            "AADT_RPT_QTY": 100, "AADT_RPT_HIST_01_QTY": 90,
            "AADT_RPT_HIST_02_QTY": 80, "AADT_RPT_HIST_03_QTY": 70,
            "AADT_RPT_HIST_04_QTY": 60},
            "geometry": {"x": -98.824, "y": 26.380}}
        s = txdot.parse_aadt_feature(feat, RETRIEVED)
        self.assertIsNone(s["latest_aadt"])
        self.assertEqual(s["status"], "UNKNOWN")

    def test_starr_county_station_present(self):
        s = station_by_id(self.stations, "214CR10")
        self.assertEqual(s["county"], "Starr")
        self.assertEqual(s["latest_aadt"], 854)

    def test_every_station_has_source_and_timestamp(self):
        for s in self.stations:
            self.assertTrue(s["source_url"].startswith("https://services.arcgis.com/"))
            self.assertEqual(s["retrieved_at_utc"], RETRIEVED)
            self.assertIn(s["status"], ("VERIFIED", "REPORTED", "UNKNOWN", "BLOCKED"))


class TestCorridorDistance(unittest.TestCase):
    def test_point_on_us83_is_near(self):
        # Rio Grande City waypoint, on US-83.
        self.assertAlmostEqual(txdot.distance_to_corridor_km(-98.824, 26.380), 0.0, places=1)
        self.assertLess(txdot.distance_to_corridor_km(-98.824, 26.380),
                        txdot.CORRIDOR_RADIUS_KM)

    def test_point_far_north_is_not_near(self):
        self.assertGreater(txdot.distance_to_corridor_km(-98.5, 26.9), 50.0)

    def test_station_near_flag(self):
        near = {"attributes": {
            "DIST_NM": "Pharr", "CNTY_NM": "Starr", "TRFC_STATN_ID": "N1",
            "LATEST_AADT_YR": 2024, "AADT_RPT_QTY": None,
            "AADT_RPT_HIST_01_QTY": 500, "AADT_RPT_HIST_02_QTY": None,
            "AADT_RPT_HIST_03_QTY": None, "AADT_RPT_HIST_04_QTY": None},
            "geometry": {"x": -98.824, "y": 26.380}}
        far = dict(near)
        far = {"attributes": dict(near["attributes"], TRFC_STATN_ID="F1"),
               "geometry": {"x": -98.5, "y": 26.9}}
        self.assertTrue(txdot.parse_aadt_feature(near, RETRIEVED)["corridor_near"])
        self.assertFalse(txdot.parse_aadt_feature(far, RETRIEVED)["corridor_near"])

    def test_station_without_geometry_has_null_distance(self):
        feat = {"attributes": {
            "DIST_NM": "Pharr", "CNTY_NM": "Starr", "TRFC_STATN_ID": "G0",
            "LATEST_AADT_YR": 2024, "AADT_RPT_QTY": None,
            "AADT_RPT_HIST_01_QTY": 500, "AADT_RPT_HIST_02_QTY": None,
            "AADT_RPT_HIST_03_QTY": None, "AADT_RPT_HIST_04_QTY": None},
            "geometry": {}}
        s = txdot.parse_aadt_feature(feat, RETRIEVED)
        self.assertIsNone(s["corridor_distance_km"])
        self.assertIsNone(s["corridor_near"])


class TestHwyEvents(unittest.TestCase):
    def test_event_parses_and_is_reported_not_verified(self):
        payload = load_fixture("hwy_events_sample.json")
        ev = txdot.parse_hwy_event(payload["features"][0], RETRIEVED)
        self.assertEqual(ev["event_type"], "Pothole")
        self.assertEqual(ev["event_status"], "Retired")
        self.assertEqual(ev["status"], "REPORTED")  # not WZDx: never VERIFIED
        self.assertEqual(ev["route_name"], "SH0130-LG")
        self.assertEqual(ev["created_at_utc"], "2025-07-21T15:28:08Z")
        self.assertEqual(ev["retrieved_at_utc"], RETRIEVED)
        self.assertIn("not the WZDx", ev["note"])

    def test_event_missing_timestamps_stay_none(self):
        ev = txdot.parse_hwy_event({"attributes": {"event_type": "Construction",
                                                   "event_status": "Active"}},
                                   RETRIEVED)
        self.assertIsNone(ev["created_at_utc"])
        self.assertIsNone(ev["lat"])


class TestWzdxBlocked(unittest.TestCase):
    def test_401_without_key_is_blocked_with_owner_step(self):
        def fetcher_401(url, params, timeout):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"Unauthorized"))

        leg = txdot.fetch_wzdx(RETRIEVED, fetcher=fetcher_401)
        self.assertEqual(leg["status"], "BLOCKED")
        self.assertEqual(leg["http_status"], 401)
        self.assertEqual(leg["zone_count"], 0)
        self.assertIn("api.drivetexas.org", leg["owner_step"])
        self.assertIn("401", leg["error"])

    def test_wzdx_success_path_when_keyed(self):
        feed = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "properties": {"road_name": "US-83", "work_zone_type": "static"},
             "geometry": {"type": "LineString",
                          "coordinates": [[-98.824, 26.380], [-98.5, 26.3]]}}]}

        def fetcher_ok(url, params, timeout):
            self.assertIn("key=", url)  # key is sent when configured
            return json.dumps(feed).encode("utf-8")

        import os as _os
        _os.environ["TXDOT_WZDX_API_KEY"] = "test-key-not-real"
        try:
            leg = txdot.fetch_wzdx(RETRIEVED, fetcher=fetcher_ok)
        finally:
            del _os.environ["TXDOT_WZDX_API_KEY"]
        self.assertEqual(leg["status"], "VERIFIED")
        self.assertEqual(leg["zone_count"], 1)

    def test_live_401_body_fixture_matches(self):
        with open(os.path.join(HERE, "fixtures", "wzdx_unauthorized_body.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "Unauthorized")


class TestArcgisPagination(unittest.TestCase):
    def test_pages_followed(self):
        pages = [
            {"features": [{"attributes": {"TRFC_STATN_ID": "A1"}},
                          {"attributes": {"TRFC_STATN_ID": "A2"}}],
             "exceededTransferLimit": True},
            {"features": [{"attributes": {"TRFC_STATN_ID": "A3"}}],
             "exceededTransferLimit": False},
        ]
        calls = []

        def fetcher(url, params, timeout):
            calls.append(params["resultOffset"])
            return json.dumps(pages[len(calls) - 1]).encode("utf-8")

        out = txdot.arcgis_query("https://example.invalid/query", {"where": "1=1"},
                                 fetcher=fetcher, page_size=2)
        self.assertEqual([f["attributes"]["TRFC_STATN_ID"]
                          for f in out["features"]], ["A1", "A2", "A3"])
        self.assertEqual(calls, [0, 2])

    def test_arcgis_error_raises(self):
        def fetcher(url, params, timeout):
            return json.dumps({"error": {"code": 400, "message": "bad"}}).encode("utf-8")

        with self.assertRaises(RuntimeError):
            txdot.arcgis_query("https://example.invalid/query", {"where": "1=1"},
                               fetcher=fetcher)


class TestCollectEndToEnd(unittest.TestCase):
    def test_collect_with_stubbed_fetchers(self):
        aadt_payload = {"features": [
            {"attributes": {"DIST_NM": "Pharr", "CNTY_NM": "Starr",
                            "TRFC_STATN_ID": "S1", "LATEST_AADT_YR": 2024,
                            "AADT_RPT_QTY": None, "AADT_RPT_HIST_01_QTY": 854,
                            "AADT_RPT_HIST_02_QTY": None, "AADT_RPT_HIST_03_QTY": None,
                            "AADT_RPT_HIST_04_QTY": None},
             "geometry": {"x": -98.824, "y": 26.380}},
            {"attributes": {"DIST_NM": "Pharr", "CNTY_NM": "Hidalgo",
                            "TRFC_STATN_ID": "S2", "LATEST_AADT_YR": 2025,
                            "AADT_RPT_QTY": 1468, "AADT_RPT_HIST_01_QTY": None,
                            "AADT_RPT_HIST_02_QTY": 2717, "AADT_RPT_HIST_03_QTY": 2088,
                            "AADT_RPT_HIST_04_QTY": 1752},
             "geometry": {"x": -98.5, "y": 26.9}},
        ]}
        events_payload = {"features": [
            {"attributes": {"route_name": "US0083-RG", "event_type": "Construction",
                            "event_status": "Active", "latitude": 26.38,
                            "longitude": -98.824,
                            "event_created_timestamp": 1764000000000,
                            "event_modified_timestamp": 1764000000000,
                            "event_retired_timestamp": None}},
            {"attributes": {"route_name": "IH0002-RG", "event_type": "Pothole",
                            "event_status": "Retired", "latitude": 26.2,
                            "longitude": -98.2,
                            "event_created_timestamp": 1764000000000,
                            "event_modified_timestamp": 1764000000000,
                            "event_retired_timestamp": None}},
        ]}

        def fetcher(url, params, timeout):
            if "AADT" in url:
                return json.dumps(aadt_payload).encode("utf-8")
            if "Highway_Events" in url:
                return json.dumps(events_payload).encode("utf-8")
            if "drivetexas.org" in url:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {},
                                             io.BytesIO(b"Unauthorized"))
            raise AssertionError(f"unexpected URL {url}")

        doc = txdot.collect(fetcher=fetcher)
        self.assertEqual(doc["sensor_id"], 52)
        self.assertEqual(doc["summary"]["aadt_stations_bbox"], 2)
        self.assertEqual(doc["summary"]["aadt_stations_corridor_near"], 1)
        self.assertEqual(doc["summary"]["aadt_counties"], {"Starr": 1, "Hidalgo": 1})
        self.assertEqual(doc["summary"]["wzdx_status"], "BLOCKED")
        self.assertEqual(doc["summary"]["wzdx_zone_count"], 0)
        # Only the Active event survives; the Retired one is dropped.
        self.assertEqual(doc["summary"]["highway_events_active_corridor"], 1)
        # Observations: 2 stations + 1 event + 1 BLOCKED wzdx record.
        self.assertEqual(len(doc["observations"]), 4)
        blocked = [o for o in doc["observations"]
                   if o["metric"] == "wzdx_work_zones"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["status"], "BLOCKED")
        self.assertIsNone(blocked[0]["value"])
        for obs in doc["observations"]:
            self.assertIn(obs["status"],
                          ("VERIFIED", "REPORTED", "UNKNOWN", "BLOCKED"))
            self.assertIn("source_url", obs)
            self.assertIn("retrieved_at_utc", obs)


if __name__ == "__main__":
    unittest.main()
