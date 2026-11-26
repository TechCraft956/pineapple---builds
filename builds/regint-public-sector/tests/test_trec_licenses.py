#!/usr/bin/env python3
"""Tests for trec_licenses.py — synthetic fixtures only, no network."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trec_licenses as tl

# Fake Socrata rows (synthetic people — not real license holders).
FAKE_ROWS = [
    {"license_type": "Sales Agent", "license_number": "100001-SA",
     "full_name": "TEST PERSON ONE", "status": "Active",
     "original_license_date": "01/15/2020", "license_expiration_date": "01/31/2027",
     "designated_supervisor_flag": "0", "county": "Starr",
     "related_license_type": "Broker Individual", "related_license_number": "100-B",
     "related_license_full_name": "TEST BROKER", "agency_identifier": "1000000001",
     "updated": "2026-11-26T07:30:08.000"},
    {"license_type": "Broker Individual", "license_number": "100002-B",
     "full_name": "TEST PERSON TWO", "status": "Inactive",
     "original_license_date": "03/01/2019", "license_expiration_date": "03/31/2026",
     "designated_supervisor_flag": "1", "county": "Starr",
     "related_license_type": "", "related_license_number": "",
     "related_license_full_name": "", "agency_identifier": "1000000002",
     "updated": "2026-11-26T07:30:08.000"},
    {"license_type": "Sales Agent", "license_number": "100003-SA",
     "full_name": "TEST PERSON THREE", "status": "Active",
     "original_license_date": "06/10/2021", "license_expiration_date": "06/30/2028",
     "designated_supervisor_flag": "0", "county": "HIDALGO",
     "related_license_type": "", "related_license_number": "",
     "related_license_full_name": "", "agency_identifier": "1000000003",
     "updated": "2026-11-26T07:30:08.000"},
    {"license_type": "Broker Company", "license_number": "100004-BB",
     "full_name": "TEST COMPANY LP", "status": "Revoked",
     "original_license_date": "05/05/2018", "license_expiration_date": "05/31/2025",
     "designated_supervisor_flag": "0", "county": "Cameron",
     "related_license_type": "", "related_license_number": "",
     "related_license_full_name": "", "agency_identifier": "1000000004",
     "updated": "2026-11-26T07:30:08.000"},
]

RUN_DATE = dt.date(2026, 11, 26)


class TestDates(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(tl.parse_us_date("11/30/2028"), dt.date(2028, 11, 30))

    def test_parse_invalid_and_empty(self):
        self.assertIsNone(tl.parse_us_date(""))
        self.assertIsNone(tl.parse_us_date("not-a-date"))
        self.assertIsNone(tl.parse_us_date(None))


class TestQueryUrl(unittest.TestCase):
    def test_county_filter_case_insensitive(self):
        url = tl.build_query_url(["Starr", "Hidalgo"], 1000, 0)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertIn("upper(county) IN ('STARR','HIDALGO')", qs["$where"][0])
        self.assertEqual(qs["$limit"], ["1000"])
        self.assertEqual(qs["$offset"], ["0"])
        self.assertEqual(qs["$order"], ["license_number"])

    def test_pagination_offset(self):
        url = tl.build_query_url(["Starr"], 1000, 1000)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(qs["$offset"], ["1000"])


class TestNormalize(unittest.TestCase):
    def test_county_case_variant_groups(self):
        row = tl.normalize_row(FAKE_ROWS[2])
        self.assertEqual(row["county"], "Hidalgo")

    def test_fields_kept_and_dates_parsed(self):
        row = tl.normalize_row(FAKE_ROWS[0])
        self.assertEqual(row["license_number"], "100001-SA")
        self.assertEqual(row["status"], "Active")
        self.assertEqual(row["license_expiration_date_parsed"], "2027-01-31")
        self.assertEqual(row["original_license_date_parsed"], "2020-01-15")

    def test_missing_fields_default_empty(self):
        row = tl.normalize_row({"license_number": "X", "county": "Starr"})
        self.assertEqual(row["full_name"], "")
        self.assertEqual(row["license_expiration_date_parsed"], "")


class TestAggregate(unittest.TestCase):
    def test_counts(self):
        rows = [tl.normalize_row(r) for r in FAKE_ROWS]
        agg = tl.aggregate(rows, RUN_DATE)
        self.assertEqual(agg["total_rows"], 4)
        self.assertEqual(agg["by_county"]["Starr"]["total"], 2)
        self.assertEqual(agg["by_county"]["Hidalgo"]["total"], 1)
        self.assertEqual(agg["by_county"]["Cameron"]["total"], 1)
        self.assertEqual(agg["by_county"]["Starr"]["by_status"]["Active"], 1)
        self.assertEqual(agg["by_county"]["Starr"]["by_status"]["Inactive"], 1)
        self.assertEqual(agg["by_county"]["Starr"]["by_license_type"]["Sales Agent"], 1)
        self.assertEqual(agg["by_county"]["Cameron"]["by_license_type"]["Broker Company"], 1)

    def test_expiring_soon_window(self):
        rows = [tl.normalize_row(r) for r in FAKE_ROWS]
        agg = tl.aggregate(rows, RUN_DATE)
        # Only the 2027-01-31 expiry is within 90 days of 2026-11-26.
        self.assertEqual(agg["expiring_soon_90d"], 1)
        self.assertEqual(agg["by_county"]["Starr"]["expiring_soon_90d"], 1)
        self.assertEqual(agg["by_county"]["Hidalgo"]["expiring_soon_90d"], 0)


class TestCollect(unittest.TestCase):
    def test_pagination_two_pages(self):
        pages = [FAKE_ROWS[:2], FAKE_ROWS[2:], []]
        calls = []

        def fake_fetch(url, timeout=30):
            calls.append(url)
            return pages.pop(0)

        rows, notes = tl.collect(["Starr"], fetch=fake_fetch, page_size=2, delay=0)
        self.assertEqual(len(rows), 4)
        self.assertEqual(notes, [])
        # Page 1 full -> page 2 full -> page 3 empty (proves exhaustion).
        self.assertEqual(len(calls), 3)

    def test_fetch_error_recorded_not_invented(self):
        def failing_fetch(url, timeout=30):
            raise ConnectionError("boom")

        rows, notes = tl.collect(["Starr"], fetch=failing_fetch, delay=0)
        self.assertEqual(rows, [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["verification"], "UNKNOWN")


class TestRun(unittest.TestCase):
    def _fake_fetch(self, url, timeout=30):
        return list(FAKE_ROWS)

    def test_output_structure(self):
        doc = tl.run(fetch=self._fake_fetch, page_size=1000, delay=0)
        self.assertEqual(doc["sensor"], 104)
        self.assertEqual(doc["verification"], "VERIFIED")
        self.assertEqual(doc["totals"]["total_rows"], 4)
        self.assertEqual(len(doc["starr_rows"]), 2)
        self.assertEqual(len(doc["county_samples"]["Hidalgo"]), 1)
        self.assertEqual(len(doc["county_samples"]["Cameron"]), 1)
        self.assertEqual(doc["source"]["counties"], tl.DEFAULT_COUNTIES)

    def test_failed_run_is_unknown(self):
        def failing_fetch(url, timeout=30):
            raise ConnectionError("boom")

        doc = tl.run(fetch=failing_fetch, delay=0)
        self.assertEqual(doc["verification"], "UNKNOWN")
        self.assertEqual(doc["totals"]["total_rows"], 0)


class TestMain(unittest.TestCase):
    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.json")
            with open(out, "w") as f:
                f.write("{}")
            rc = tl.main(["--out", out])
            self.assertEqual(rc, 2)
            with open(out) as f:
                self.assertEqual(f.read(), "{}")


if __name__ == "__main__":
    unittest.main()
