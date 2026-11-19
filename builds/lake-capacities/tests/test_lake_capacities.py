#!/usr/bin/env python3
"""Offline fixture tests — no network. Run:
  python3 -m unittest discover -s tests -v   (from the build root)
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
FIX = os.path.join(ROOT, "tests", "fixtures")

import twdb_client  # noqa: E402
import usgs_client  # noqa: E402
from normalize import (build_record, classify_trend, compare_sources,  # noqa: E402
                       compute_pct, record_to_item)
from render import brief_line, render_brief  # noqa: E402


def load_json(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def load_text(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


PROV = {"current": {"source_url": "https://example.test/recent.json",
                    "retrieved_at_utc": "2026-11-18T05:00:00Z"}}

FALCON_ENTRY = {
    "name": "Falcon International Reservoir", "aliases": ["Falcon Reservoir"],
    "region": "Starr/Zapata Counties, TX", "river": "Rio Grande",
    "usgs_site_id": "08461200", "usgs_status": "NOT WIRED",
    "twdb_slug": "falcon", "twdb_status": "WIRED",
    "conservation": {"capacity_acre_ft": 1562367, "pool_elevation_ft": 301.2,
                     "source": "TWDB", "as_of": "2026-11-17"},
}


def falcon_record():
    recent = twdb_client.parse_recent(load_json("twdb_recent_sample.json"),
                                      "Falcon")
    hist = twdb_client.parse_history_csv(
        load_text("twdb_falcon_30day_sample.csv"))
    return build_record(FALCON_ENTRY, None, None, recent, hist, PROV)


class TestParsing(unittest.TestCase):
    def test_usgs_iv_parsing(self):
        parsed = usgs_client.parse_iv(load_json("usgs_iv_sample.json"))
        storage, elev, obs = usgs_client.split_current(parsed["08025350"])
        self.assertEqual(storage, 3714000.0)
        self.assertEqual(elev, 167.54)
        self.assertEqual(obs, "2026-11-18T04:45:00Z")  # -06:00 -> UTC
        # elevation-only site
        s2, e2, _ = usgs_client.split_current(parsed["08167700"])
        self.assertIsNone(s2)
        self.assertEqual(e2, 907.63)
        # empty series site is absent, not zero
        self.assertNotIn("08461200", parsed)

    def test_usgs_dv_parsing(self):
        parsed = usgs_client.parse_dv(load_json("usgs_dv_sample.json"))
        series = parsed["08210500"]["00054"]
        self.assertEqual(len(series), 3)
        self.assertEqual(series[-1], ("2026-11-16", 210400.0))
        self.assertNotIn("08039300", parsed)  # empty storage series dropped

    def test_twdb_recent_parsing(self):
        rec = twdb_client.parse_recent(load_json("twdb_recent_sample.json"),
                                       "Falcon")
        self.assertEqual(rec["conservation_storage_acre_ft"], 355620.0)
        self.assertEqual(rec["total_storage_acre_ft"], 488850.0)
        self.assertEqual(rec["conservation_capacity_acre_ft"], 1562367.0)
        self.assertEqual(rec["timestamp"], "2026-11-17")
        self.assertIsNone(twdb_client.parse_recent(
            load_json("twdb_recent_sample.json"), "NoSuchLake"))

    def test_twdb_csv_parsing_skips_comments(self):
        rows = twdb_client.parse_history_csv(
            load_text("twdb_falcon_30day_sample.csv"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["date"], "2026-10-18")
        self.assertEqual(rows[-1]["conservation_storage_acre_ft"], 355620.0)


class TestPctMath(unittest.TestCase):
    def test_pct_normal(self):
        self.assertEqual(
            compute_pct(355620, 1562367, "2026-11-17", "2026-11-17"), 22.8)

    def test_pct_null_without_capacity(self):
        self.assertIsNone(compute_pct(355620, None, "2026-11-17", None))

    def test_pct_null_without_storage(self):
        self.assertIsNone(compute_pct(None, 1562367, None, "2026-11-17"))

    def test_pct_null_without_dates(self):
        # both figures present but undated -> still null (contract)
        self.assertIsNone(compute_pct(355620, 1562367, None, "2026-11-17"))
        self.assertIsNone(compute_pct(355620, 1562367, "2026-11-17", None))

    def test_pct_null_zero_capacity(self):
        self.assertIsNone(
            compute_pct(10, 0, "2026-11-17", "2026-11-17"))


class TestTrend(unittest.TestCase):
    CAP = 1_000_000  # steady band = +/-5,000 ac-ft

    def test_steady_at_boundary(self):
        s = [("2026-10-18", 100000.0), ("2026-11-17", 105000.0)]
        self.assertEqual(classify_trend(s, self.CAP)["direction"], "steady")
        s = [("2026-10-18", 100000.0), ("2026-11-17", 95000.0)]
        self.assertEqual(classify_trend(s, self.CAP)["direction"], "steady")

    def test_rising_and_falling_just_outside_boundary(self):
        s = [("2026-10-18", 100000.0), ("2026-11-17", 105001.0)]
        t = classify_trend(s, self.CAP)
        self.assertEqual(t["direction"], "rising")
        self.assertEqual(t["change_acre_ft"], 5001.0)
        s = [("2026-10-18", 100000.0), ("2026-11-17", 94999.0)]
        self.assertEqual(classify_trend(s, self.CAP)["direction"], "falling")

    def test_unknown_when_short_or_missing(self):
        self.assertEqual(classify_trend([], self.CAP)["direction"], "unknown")
        self.assertEqual(classify_trend(None, self.CAP)["direction"],
                         "unknown")
        one = [("2026-11-17", 100000.0)]
        self.assertEqual(classify_trend(one, self.CAP)["direction"],
                         "unknown")
        short_span = [("2026-11-15", 100000.0), ("2026-11-17", 120000.0)]
        self.assertEqual(classify_trend(short_span, self.CAP)["direction"],
                         "unknown")


class TestCrossSource(unittest.TestCase):
    def test_agree_storage(self):
        c = compare_sources({"storage_acre_ft": 3714000.0,
                             "elevation_ft": 167.54},
                            {"storage_acre_ft": 3750147.0,
                             "elevation_ft": 167.57})
        self.assertEqual(c["status"], "agree")  # ~0.97% apart

    def test_disagree_keeps_both(self):
        c = compare_sources({"storage_acre_ft": 300000.0,
                             "elevation_ft": 200.0},
                            {"storage_acre_ft": 488850.0,
                             "elevation_ft": 262.25})
        self.assertEqual(c["status"], "disagree")
        self.assertEqual(c["usgs"]["storage_acre_ft"], 300000.0)
        self.assertEqual(c["twdb"]["storage_acre_ft"], 488850.0)

    def test_single_source(self):
        c = compare_sources(None, {"storage_acre_ft": 1.0,
                                   "elevation_ft": 2.0})
        self.assertEqual(c["status"], "single_source")


class TestBuildRecord(unittest.TestCase):
    def test_falcon_record_pct_handcheckable(self):
        r = falcon_record()
        # 355620 / 1562367 = 22.76% -> 22.8, matches TWDB published %
        self.assertEqual(r["pct_conservation"], 22.8)
        self.assertEqual(r["pct_published_twdb"], 22.8)
        self.assertEqual(r["current"]["storage_acre_ft"], 355620.0)
        self.assertEqual(r["current"]["total_storage_acre_ft"], 488850.0)
        self.assertEqual(r["trend"]["direction"], "rising")
        self.assertEqual(r["trend"]["change_acre_ft"], 33330.0)
        self.assertEqual(r["confidence"], 0.6)  # single source (TWDB)

    def test_elevation_only_record_pct_null(self):
        entry = dict(FALCON_ENTRY, name="Canyon Lake",
                     usgs_site_id="08167700", usgs_status="WIRED",
                     twdb_slug="canyon")
        iv = usgs_client.parse_iv(load_json("usgs_iv_sample.json"))
        r = build_record(entry, iv["08167700"], None, None, [], PROV)
        self.assertIsNone(r["pct_conservation"])
        self.assertEqual(r["current"]["elevation_ft"], 907.63)
        self.assertEqual(r["trend"]["direction"], "unknown")
        self.assertIn("% unknown (elevation only)", brief_line(r))

    def test_disagreement_record_confidence_and_detail(self):
        recent = twdb_client.parse_recent(
            load_json("twdb_recent_sample.json"), "Falcon")
        iv_site = {"00054": {"value": 300000.0,
                             "observed_at_utc": "2026-11-18T04:00:00Z"},
                   "62614": {"value": 200.0,
                             "observed_at_utc": "2026-11-18T04:00:00Z"}}
        r = build_record(FALCON_ENTRY, iv_site, None, recent, [], PROV)
        self.assertEqual(r["cross_source"]["status"], "disagree")
        self.assertEqual(r["confidence"], 0.6)
        self.assertEqual(r["sources_detail"]["usgs"]["storage_acre_ft"],
                         300000.0)
        self.assertEqual(r["sources_detail"]["twdb"]["storage_acre_ft"],
                         488850.0)
        self.assertIn("Sources disagree", brief_line(r))

    def test_two_source_agree_confidence(self):
        recent = {"timestamp": "2026-11-17", "elevation_ft": 167.57,
                  "total_storage_acre_ft": 3750147.0,
                  "conservation_storage_acre_ft": 1873024.0,
                  "conservation_capacity_acre_ft": 2236450.0,
                  "conservation_pool_elevation_ft": 172.0,
                  "percent_full_published": 83.7,
                  "total_capacity_at_conservation_pool_acre_ft": 4477000.0}
        iv = usgs_client.parse_iv(load_json("usgs_iv_sample.json"))
        entry = dict(FALCON_ENTRY, name="Toledo Bend Reservoir",
                     usgs_site_id="08025350", usgs_status="WIRED",
                     twdb_slug="toledo-bend")
        r = build_record(entry, iv["08025350"], None, recent, [], PROV)
        self.assertEqual(r["cross_source"]["status"], "agree")
        self.assertEqual(r["confidence"], 0.85)
        self.assertEqual(r["pct_conservation"], 83.7)


class TestRendererAndItem(unittest.TestCase):
    def test_brief_line_contract_shape(self):
        line = brief_line(falcon_record())
        self.assertIn("Falcon International Reservoir — 22.8% of "
                      "conservation capacity", line)
        self.assertIn("storage 355,620 ac-ft", line)
        self.assertIn("TWDB, retrieved 2026-11-18 05:00 UTC", line)
        self.assertIn("rising over 30 days (+33,330 ac-ft)", line)

    def test_render_brief_completeness(self):
        r2 = falcon_record()
        r2["lake"] = "Amistad International Reservoir"
        md = render_brief([falcon_record(), r2], "2026-11-18T05:00:00Z")
        self.assertIn("Falcon International Reservoir", md)
        self.assertIn("Amistad International Reservoir", md)
        self.assertIn("## Summary table", md)
        self.assertEqual(md.count("| Lake |"), 1)

    def test_item_shape(self):
        item = record_to_item(falcon_record(),
                              url="https://example.test/falcon")
        self.assertEqual(item["category"], "PLACES")
        self.assertIsNone(item["est_value"])
        self.assertEqual(item["confidence"], 0.6)
        self.assertIn("22.8%", item["title"])


if __name__ == "__main__":
    unittest.main()
