"""Tests for events_8k.py (sensor #60) and ipo_pipeline.py (#62).
Stdlib unittest only, no network (all EDGAR calls are faked).

Run:  python3 -m unittest discover -s tests -v
from builds/market-macro/
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edgar  # noqa: E402
import events_8k  # noqa: E402
import ipo_pipeline  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MASTER_INDEX = (FIXTURES / "master_index_sample.idx").read_text(
    encoding="utf-8")

EIGHT_K_TEXT = """<SEC-DOCUMENT>0001045810-26-000789.txt
<TEXT>
<p>Item 1.01 Entry into a Material Definitive Agreement.</p>
<p>Item 5.02 Departure of Directors or Certain Officers.</p>
</TEXT>
</SEC-DOCUMENT>
"""

SUBMISSIONS = {
    "cik": "0001045810",
    "name": "NVIDIA CORP",
    "filings": {"recent": {
        "form": ["8-K", "10-Q"],
        "filingDate": ["2026-11-25", "2026-11-01"],
        "reportDate": ["2026-11-25", "2026-09-26"],
        "accessionNumber": ["0001045810-26-000789",
                            "0001045810-26-000700"],
        "primaryDocument": ["nvda-8k.htm", "nvda-10q.htm"],
        "primaryDocDescription": ["8-K", "10-Q"],
    }},
}


def fake_master_index(year, month, day):
    return edgar.parse_master_index(MASTER_INDEX), "OK"


class TestEvents8K(unittest.TestCase):
    @patch.object(edgar, "fetch_master_index", fake_master_index)
    @patch.object(edgar, "fetch_text",
                  lambda url: (EIGHT_K_TEXT, "OK"))
    @patch.object(edgar, "fetch_submissions",
                  lambda cik: (SUBMISSIONS, "OK"))
    def test_8k_listed_and_items_parsed(self):
        result = events_8k.collect(
            days=1, max_items=5,
            watchlist={"0001045810": "NVIDIA CORP"})
        self.assertEqual(result["sensor"], "60")
        self.assertEqual(result["summary"]["observations_total"], 1)
        obs = result["observations"][0]
        self.assertEqual(obs["company"], "NVIDIA CORP")
        self.assertEqual(obs["items"], ["1.01", "5.02"])
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(result["summary"]["top_items"],
                         {"1.01": 1, "5.02": 1})
        self.assertEqual(result["summary"]["watchlist_filings"], 1)

    @patch.object(edgar, "fetch_master_index", fake_master_index)
    @patch.object(edgar, "fetch_text", lambda url: (None, "HTTP_404"))
    @patch.object(edgar, "fetch_submissions",
                  lambda cik: (SUBMISSIONS, "OK"))
    def test_failed_text_fetch_stays_reported(self):
        result = events_8k.collect(
            days=1, max_items=5,
            watchlist={"0001045810": "NVIDIA CORP"})
        obs = result["observations"][0]
        self.assertEqual(obs["label"], "REPORTED")
        self.assertIsNone(obs["items"])
        self.assertIn("HTTP_404", obs["note"])

    @patch.object(edgar, "fetch_master_index",
                  lambda y, m, d: ([], "HTTP_404"))
    def test_no_index_day(self):
        result = events_8k.collect(days=1, watchlist={})
        self.assertEqual(result["day_status"][0]["label"], "UNKNOWN")
        self.assertEqual(result["summary"]["observations_total"], 0)


class TestIpoPipeline(unittest.TestCase):
    @patch.object(edgar, "fetch_master_index", fake_master_index)
    def test_pipeline_forms(self):
        result = ipo_pipeline.collect(days=1)
        self.assertEqual(result["sensor"], "62")
        self.assertEqual(result["summary"]["observations_total"], 3)
        self.assertEqual(result["summary"]["by_form"],
                         {"424B4": 1, "S-1": 1, "S-4": 1})
        self.assertEqual(result["summary"]["priced_424b4"], 1)
        forms = {o["form"] for o in result["observations"]}
        self.assertEqual(forms, {"S-1", "424B4", "S-4"})
        self.assertTrue(all(o["label"] == "VERIFIED"
                            for o in result["observations"]))

    @patch.object(edgar, "fetch_master_index",
                  lambda y, m, d: ([], "HTTP_404"))
    def test_no_index_day(self):
        result = ipo_pipeline.collect(days=1)
        self.assertEqual(result["day_status"][0]["label"], "UNKNOWN")
        self.assertEqual(result["summary"]["observations_total"], 0)


if __name__ == "__main__":
    unittest.main()
