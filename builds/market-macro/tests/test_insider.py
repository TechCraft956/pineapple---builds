"""Tests for insider.py (sensor #18). Stdlib unittest only, no network
(all EDGAR calls are faked).

Run:  python3 -m unittest discover -s tests -v
from builds/market-macro/
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edgar  # noqa: E402
import insider  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FORM4_XML = (FIXTURES / "form4_sample.xml").read_text(encoding="utf-8")
MASTER_INDEX = (FIXTURES / "master_index_sample.idx").read_text(
    encoding="utf-8")

SUBMISSIONS = {
    "cik": "0000320193",
    "name": "Apple Inc.",
    "filings": {"recent": {
        "form": ["4", "10-Q", "13F-HR"],
        "filingDate": ["2026-11-20", "2026-11-01", "2026-11-14"],
        "reportDate": ["2026-11-20", "2026-09-26", "2026-09-30"],
        "accessionNumber": ["0000320193-26-000123",
                            "0000320193-26-000100",
                            "0000320193-26-000090"],
        "primaryDocument": ["wf-form4_123.xml", "aapl-10q.htm",
                            "13f.htm"],
        "primaryDocDescription": ["FORM 4", "10-Q", "13F-HR"],
    }},
}


def fake_master_index(year, month, day):
    return edgar.parse_master_index(MASTER_INDEX), "OK"


def fake_fetch_json(url):
    if "index.json" in url:
        return ({"directory": {"item": [
            {"name": "wf-form4_123.xml"}]}}, "OK")
    return None, "HTTP_404"


def fake_fetch_text(url):
    if url.endswith(".xml"):
        return FORM4_XML, "OK"
    return None, "HTTP_404"


def fake_submissions(cik):
    return SUBMISSIONS, "OK"


class TestCollect(unittest.TestCase):
    @patch.object(edgar, "fetch_master_index", fake_master_index)
    @patch.object(edgar, "fetch_json", fake_fetch_json)
    @patch.object(edgar, "fetch_text", fake_fetch_text)
    @patch.object(edgar, "fetch_submissions", fake_submissions)
    def test_market_wide_counts_and_parsed_trades(self):
        result = insider.collect(days=1, max_form4=5,
                                 watchlist={"0000320193": "Apple Inc."})
        self.assertEqual(result["sensor"], "18")
        s = result["summary"]
        self.assertEqual(s["form4_filings_total"], 1)
        self.assertEqual(s["form13f_filings_total"], 1)
        self.assertEqual(s["form4_transactions_parsed"], 1)
        self.assertEqual(s["insider_buys_P_verified"], 1)
        self.assertEqual(s["insider_sells_S_verified"], 1)
        txns = [o for o in result["observations"]
                if o.get("kind") == "insider_transaction"]
        self.assertEqual(len(txns), 2)
        self.assertEqual(txns[0]["owner"], "DOE JANE")
        self.assertEqual(txns[0]["price"], 275.50)
        self.assertEqual(s["watchlist_filings"], 2)

    @patch.object(edgar, "fetch_master_index",
                  lambda y, m, d: ([], "HTTP_404"))
    @patch.object(edgar, "fetch_submissions",
                  lambda cik: (None, "HTTP_404"))
    def test_no_index_day_is_unknown(self):
        result = insider.collect(days=1, watchlist={"0000320193": "X"})
        self.assertEqual(result["day_status"][0]["label"], "UNKNOWN")
        self.assertEqual(result["summary"]["observations_total"], 0)
        self.assertEqual(result["watchlist"][0]["label"], "UNKNOWN")

    @patch.object(edgar, "fetch_master_index", fake_master_index)
    @patch.object(edgar, "fetch_json", fake_fetch_json)
    @patch.object(edgar, "fetch_text", fake_fetch_text)
    @patch.object(edgar, "fetch_submissions", fake_submissions)
    def test_max_form4_cap_leaves_rest_reported(self):
        result = insider.collect(days=1, max_form4=0,
                                 watchlist={"0000320193": "Apple Inc."})
        filings = [o for o in result["observations"]
                   if o.get("kind") == "form4_filing"]
        self.assertEqual(len(filings), 1)
        self.assertEqual(filings[0]["label"], "REPORTED")
        self.assertEqual(result["summary"]["form4_transactions_parsed"], 0)


if __name__ == "__main__":
    unittest.main()
