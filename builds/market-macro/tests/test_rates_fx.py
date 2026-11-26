"""Tests for rates_fx.py (sensor #64). Stdlib unittest only, no network
(all HTTP calls are faked).

Run:  python3 -m unittest discover -s tests -v
from builds/market-macro/
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rates_fx  # noqa: E402

BIS_DOC = {
    "meta": {"prepared": "2026-11-26T20:04:38", "test": False},
    "data": {
        "dataSets": [{
            "series": {
                "0:0": {"observations": {
                    "0": ["3.875", 0, 0, None],
                    "1": ["3.875", 0, 0, None],
                }},
                "0:1": {"observations": {
                    "0": ["2.5", 0, 0, None],
                }},
            },
        }],
        "structure": {
            "dimensions": {
                "series": [
                    {"id": "FREQ", "values": [{"id": "D"}]},
                    {"id": "REF_AREA", "values": [{"id": "US"},
                                                  {"id": "XM"}]},
                ],
                "observation": [
                    {"id": "TIME_PERIOD", "values": [
                        {"id": "2026-11-24"},
                        {"id": "2026-11-23"},
                    ]},
                ],
            },
        },
    },
}

ECB_DOC = {
    "header": {"prepared": "2026-11-26T20:03:48.293+00:00"},
    "dataSets": [{
        "series": {
            "0:0:0:0:0": {"observations": {
                "0": [1.0963, 0, 0, None, None],
                "1": [1.0935, 0, 0, None, None],
            }},
        },
    }],
    "structure": {
        "dimensions": {
            "observation": [
                {"id": "TIME_PERIOD", "values": [
                    {"id": "2026-11-25"},
                    {"id": "2026-11-24"},
                ]},
            ],
        },
    },
}


class TestBisParser(unittest.TestCase):
    def test_series_and_dates(self):
        rows = rates_fx._bis_series(BIS_DOC)
        self.assertEqual(len(rows), 3)
        us = [r for r in rows if r["area"] == "US"]
        self.assertEqual(len(us), 2)
        self.assertEqual(us[0]["date"], "2026-11-24")
        self.assertEqual(us[0]["value"], 3.875)
        self.assertEqual(us[0]["freq"], "D")
        self.assertEqual(us[0]["label"], "VERIFIED")
        xm = [r for r in rows if r["area"] == "XM"]
        self.assertEqual(xm[0]["value"], 2.5)

    def test_empty_doc(self):
        self.assertEqual(rates_fx._bis_series({}), [])
        self.assertEqual(rates_fx._bis_series({"data": {"dataSets": []}}), [])

    def test_unparseable_value_is_reported(self):
        doc = {"data": {"dataSets": [{"series": {"0:0": {"observations": {
            "0": ["n/a", 0, 0, None]}}}}],
            "structure": {"dimensions": {
                "series": [{"id": "FREQ", "values": [{"id": "M"}]},
                           {"id": "REF_AREA", "values": [{"id": "US"}]}],
                "observation": [{"id": "TIME_PERIOD", "values": [
                    {"id": "2026-10-01"}]}]}}}}
        rows = rates_fx._bis_series(doc)
        self.assertEqual(rows[0]["value"], None)
        self.assertEqual(rows[0]["label"], "REPORTED")


class TestEcbParser(unittest.TestCase):
    def test_fx_observations(self):
        rows = rates_fx._ecb_series(ECB_DOC, "fx_reference_rate", "USD/EUR")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["value"], 1.0963)
        self.assertEqual(rows[0]["date"], "2026-11-25")
        self.assertEqual(rows[1]["value"], 1.0935)
        self.assertEqual(rows[0]["label"], "VERIFIED")

    def test_empty_doc(self):
        self.assertEqual(rates_fx._ecb_series({}, "fx", "USD/EUR"), [])


class TestCollect(unittest.TestCase):
    def fake_fetch(self, url, accept=None, timeout=30):
        if "stats.bis.org" in url:
            return BIS_DOC, "OK"
        if "data-api.ecb.europa.eu" in url:
            return ECB_DOC, "OK"
        return None, "HTTP_404"

    @patch.object(rates_fx, "fetch_json_url")
    def test_collect_all_legs(self, mock_fetch):
        mock_fetch.side_effect = self.fake_fetch
        result = rates_fx.collect(last_n=2)
        self.assertEqual(result["sensor"], "64")
        s = result["summary"]
        # 14 monthly + 2 daily BIS areas x 2 obs each from the fake doc
        # (fake returns the same doc for every BIS call) + ECB legs
        self.assertEqual(s["bis_series_ok"], 16)
        self.assertEqual(s["ecb_series_ok"], 14)
        self.assertEqual(s["observations_total"],
                         16 * 3 + 14 * 2)
        self.assertTrue(all(o["label"] == "VERIFIED"
                            for o in result["observations"]))

    @patch.object(rates_fx, "fetch_json_url",
                  return_value=(None, "HTTP_500"))
    def test_all_legs_fail(self, mock_fetch):
        result = rates_fx.collect(last_n=2)
        self.assertEqual(result["summary"]["observations_total"], 0)
        self.assertEqual(result["summary"]["bis_series_ok"], 0)
        self.assertTrue(all(l["label"] == "UNKNOWN"
                            for l in result["leg_status"]))


if __name__ == "__main__":
    unittest.main()
