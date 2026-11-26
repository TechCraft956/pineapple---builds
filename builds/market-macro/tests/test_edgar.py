"""Tests for edgar.py (shared EDGAR client). Stdlib unittest only,
no network.

Run:  python3 -m unittest discover -s tests -v
from builds/market-macro/
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edgar  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

FORM4_XML = (FIXTURES / "form4_sample.xml").read_text(encoding="utf-8")
MASTER_INDEX = (FIXTURES / "master_index_sample.idx").read_text(
    encoding="utf-8")

EIGHT_K_TEXT = """<SEC-DOCUMENT>0001045810-26-000789.txt : 20261125
<SEC-HEADER>0001045810-26-000789.hdr.sgml : 20261125
<ACCEPTANCE-DATETIME>20261125120000
</SEC-HEADER>
<DOCUMENT>
<TYPE>8-K
<SEQUENCE>1
<FILENAME>nvda-8k.htm
<TEXT>
<html><body>
<p>Item 1.01 Entry into a Material Definitive Agreement.</p>
<p>Item 2.03 Creation of a Direct Financial Obligation.</p>
<p>Item 5.02 Departure of Directors or Certain Officers.</p>
<p>Item 9.01 Financial Statements and Exhibits.</p>
<p>Item 1.01 mentioned again in the body text.</p>
</body></html>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
"""

SUBMISSIONS = {
    "cik": "0000320193",
    "name": "Apple Inc.",
    "filings": {"recent": {
        "form": ["4", "10-Q", "13F-HR", "4/A", "8-K"],
        "filingDate": ["2026-11-20", "2026-11-01", "2026-11-14",
                       "2026-11-19", "2026-11-18"],
        "reportDate": ["2026-11-20", "2026-09-26", "2026-09-30",
                       "2026-11-19", "2026-11-18"],
        "accessionNumber": ["0000320193-26-000123",
                            "0000320193-26-000100",
                            "0000320193-26-000090",
                            "0000320193-26-000110",
                            "0000320193-26-000105"],
        "primaryDocument": ["wf-form4_123.xml", "aapl-10q.htm",
                            "13f.htm", "wf-form4_110.xml", "aapl-8k.htm"],
        "primaryDocDescription": ["FORM 4", "10-Q", "13F-HR", "FORM 4",
                                  "8-K"],
    }},
}


class TestMasterIndex(unittest.TestCase):
    def test_parse_rows(self):
        rows = edgar.parse_master_index(MASTER_INDEX)
        good = [r for r in rows if r.get("label") == "VERIFIED"]
        self.assertEqual(len(good), 6)
        self.assertEqual(good[0]["cik"], "0000320193")
        self.assertEqual(good[0]["form"], "4")
        self.assertEqual(good[3]["form"], "S-1")
        self.assertEqual(good[4]["form"], "424B4")
        self.assertEqual(good[4]["filename"],
                         "edgar/data/1234567/0001234567-26-000002.txt")

    def test_malformed_row_is_reported_not_dropped(self):
        rows = edgar.parse_master_index(MASTER_INDEX)
        bad = [r for r in rows if r.get("label") == "REPORTED"]
        self.assertEqual(len(bad), 1)
        self.assertIn("BAD ROW", bad[0]["raw"])

    def test_quarter_and_url(self):
        self.assertEqual(edgar.quarter_for(1), 1)
        self.assertEqual(edgar.quarter_for(11), 4)
        self.assertEqual(edgar.quarter_for(12), 4)
        self.assertEqual(
            edgar.master_index_url(2026, 11, 25),
            "https://www.sec.gov/Archives/edgar/daily-index/"
            "2026/QTR4/master.20261125.idx")
        self.assertEqual(
            edgar.submissions_url("320193"),
            "https://data.sec.gov/submissions/CIK0000320193.json")
        self.assertEqual(edgar.accession_path("0000320193-26-000123"),
                         "000032019326000123")

    def test_filing_doc_url(self):
        self.assertEqual(
            edgar.filing_doc_url("320193", "0000320193-26-000123",
                                 "wf-form4_123.xml"),
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000123/wf-form4_123.xml")


class TestRecentFilings(unittest.TestCase):
    def test_form_filter_and_limit(self):
        got = edgar.recent_filings(SUBMISSIONS, {"4", "13F-HR"}, limit=10)
        self.assertEqual([g["form"] for g in got], ["4", "13F-HR"])
        self.assertEqual(got[0]["accessionNumber"],
                         "0000320193-26-000123")
        self.assertEqual(got[1]["primaryDocument"], "13f.htm")

    def test_limit_applies(self):
        got = edgar.recent_filings(SUBMISSIONS, {"4", "13F-HR"}, limit=1)
        self.assertEqual(len(got), 1)

    def test_empty_submissions(self):
        self.assertEqual(edgar.recent_filings({}, {"4"}), [])
        self.assertEqual(edgar.recent_filings({"filings": {}}, {"4"}), [])


class TestForm4Xml(unittest.TestCase):
    def test_transactions(self):
        txns = edgar.parse_form4_xml(FORM4_XML)
        self.assertEqual(len(txns), 2)
        sell, buy = txns
        self.assertEqual(sell["owner"], "DOE JANE")
        self.assertEqual(sell["title"], "Common Stock")
        self.assertEqual(sell["code"], "S")
        self.assertEqual(sell["acquiredDisposed"], "D")
        self.assertEqual(sell["shares"], 5000.0)
        self.assertEqual(sell["price"], 275.50)
        self.assertEqual(sell["date"], "2026-11-20")
        self.assertEqual(sell["label"], "VERIFIED")
        self.assertEqual(buy["code"], "P")
        self.assertEqual(buy["shares"], 1000.0)
        self.assertEqual(buy["price"], 270.25)

    def test_bad_xml_returns_empty(self):
        self.assertEqual(edgar.parse_form4_xml("not xml at all"), [])
        self.assertEqual(edgar.parse_form4_xml("<ownershipDocument/>"), [])


class TestEightKItems(unittest.TestCase):
    def test_items_deduped_in_order(self):
        self.assertEqual(edgar.parse_8k_items(EIGHT_K_TEXT),
                         ["1.01", "2.03", "5.02", "9.01"])

    def test_no_items(self):
        self.assertEqual(edgar.parse_8k_items("nothing here"), [])

    def test_nbsp_and_deep_items(self):
        # Real 8-K .txt files bury item headings behind KBs of HTML/CSS
        # and sometimes behind a non-breaking-space entity.
        text = "<style>" + ("x" * 20000) + "</style>\n" \
            "<p>Item&nbsp;2.02 Results of Operations.</p>\n" \
            "<p>Item 9.01 Financial Statements.</p>"
        self.assertEqual(edgar.parse_8k_items(text), ["2.02", "9.01"])


if __name__ == "__main__":
    unittest.main()
