#!/usr/bin/env python3
"""Offline tests for tea_certification.py (SBEC VirtCert lookup).

All fixtures are synthetic HTML mimicking the live page structure
(fake names, fake spids, placeholder tokens) — no network calls.
Run from builds/regint-public-sector:  python -m unittest -v
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import tea_certification as tc

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class StubClient:
    """Fake VirtCert client backed by fixture pages."""

    def __init__(self, search_page, details=None, delay=0):
        self._search_page = search_page
        self._details = details or {}
        self.delay = delay
        self.detail_calls = []

    def search(self, last_name, first_name, middle_name=""):
        return tc.parse_search_page(self._search_page), self._search_page

    def detail(self, token, spid):
        self.detail_calls.append(spid)
        return tc.parse_detail_page(self._details[spid])


def entry(**over):
    base = {"key": "test-entry", "district": "Test ISD",
            "district_id": "000000", "role": "Superintendent",
            "last_name": "Example", "first_name": "Carlos",
            "expected_credential": "Superintendent"}
    base.update(over)
    return base


class TestSearchParsing(unittest.TestCase):
    def test_list_parses_triples_in_order(self):
        result = tc.parse_search_page(load("virtcert_search_list.html"))
        self.assertEqual(result["kind"], "list")
        self.assertEqual(len(result["matches"]), 3)
        self.assertEqual(result["matches"][0]["display_name"], "Carlos Example")
        self.assertEqual(result["matches"][0]["spid"], "9000001")
        self.assertEqual(result["matches"][0]["token"], "FIXTURE-TOKEN-0001")
        self.assertEqual(result["matches"][2]["display_name"],
                         "Carlos Miguel Example")
        self.assertEqual(result["matches"][2]["spid"], "9000003")

    def test_zero_matches(self):
        result = tc.parse_search_page(load("virtcert_search_zero.html"))
        self.assertEqual(result, {"kind": "zero", "matches": []})

    def test_direct_detail_kind(self):
        result = tc.parse_search_page(load("virtcert_detail.html"))
        self.assertEqual(result, {"kind": "detail", "matches": []})

    def test_ragged_match_list_raises(self):
        page = load("virtcert_search_list.html").replace(
            'value="9000003"', 'value="9000003" data-x="1"', 1)
        # Remove one token so counts disagree.
        page = page.replace(
            '<input name="__RequestVerificationToken" type="hidden" '
            'value="FIXTURE-TOKEN-0003" />', '', 1)
        with self.assertRaises(ValueError):
            tc.parse_search_page(page)

    def test_unrecognized_page_raises(self):
        with self.assertRaises(ValueError):
            tc.parse_search_page("<html><body>hello</body></html>")


class TestDetailParsing(unittest.TestCase):
    def setUp(self):
        self.detail = tc.parse_detail_page(load("virtcert_detail.html"))

    def test_record_name_and_date(self):
        self.assertEqual(self.detail["record_name"], "Carlos Miguel Example Jr")
        self.assertEqual(self.detail["official_record_date"],
                         "Thursday, November 26, 2026")

    def test_current_and_history_sections(self):
        certs = self.detail["certificates"]
        current = [c for c in certs if c["section"] == "current"]
        history = [c for c in certs if c["section"] == "history"]
        self.assertEqual(len(current), 3)  # Principal, Superintendent, PE
        self.assertEqual(len(history), 2)  # expired Principal + Superintendent
        self.assertTrue(all(c["status"] == "Valid" for c in current))
        self.assertTrue(all(c["status"] == "Expired" for c in history))

    def test_categories_and_grades(self):
        current = [c for c in self.detail["certificates"]
                   if c["section"] == "current"]
        by_desc = {c["description"]: c for c in current}
        sup = by_desc["Superintendent"]
        self.assertEqual(sup["category"], "STANDARD")
        self.assertEqual(sup["grades"], "Grades (EC-12)")
        self.assertEqual(sup["effective"], "07/01/2024")
        self.assertEqual(sup["expiration"], "06/30/2030")
        pe = by_desc["Secondary Physical Education"]
        self.assertEqual(pe["category"], "PROVISIONAL")
        self.assertEqual(pe["expiration"], "Life")
        self.assertEqual(pe["grades"], "Grades (6-12)")

    def test_duplicate_row_deduped(self):
        sups = [c for c in self.detail["certificates"]
                if c["description"] == "Superintendent"
                and c["section"] == "current"]
        self.assertEqual(len(sups), 1)

    def test_empty_page_raises(self):
        with self.assertRaises(ValueError):
            tc.parse_detail_page("<html><body>nothing here</body></html>")


class TestNames(unittest.TestCase):
    def test_valid_names(self):
        for name in ("Gonzalez", "Villarreal Morris", "Gomez-Martin",
                     "O'Brien", "De La Cruz"):
            tc.validate_name(name, "last")

    def test_invalid_names_rejected(self):
        for name in ("", "A" * 31, "Gonzalez; DROP", "Smiley :)"):
            with self.assertRaises(ValueError, msg=name):
                tc.validate_name(name, "last")

    def test_exact_match_ignores_middle_and_suffix(self):
        self.assertTrue(tc.is_exact_match("Carlos Miguel Example Jr",
                                          "Example", "Carlos"))
        self.assertTrue(tc.is_exact_match("Elsa V Morris",
                                          "Morris", "Elsa"))
        self.assertTrue(tc.is_exact_match("CARLOS  EXAMPLE",
                                          "Example", "Carlos"))
        self.assertTrue(tc.is_exact_match("Carlos Alberto Example",
                                          "Example", "Carlos"))
        self.assertFalse(tc.is_exact_match("Miguel Example",
                                           "Example", "Carlos"))

    def test_holds_credential(self):
        certs = [{"description": "Superintendent"},
                 {"description": "Principal"}]
        self.assertTrue(tc.holds_credential(certs, "Superintendent"))
        self.assertFalse(tc.holds_credential(certs, "Teacher"))


class TestCollectEntry(unittest.TestCase):
    def test_verified_single_holder(self):
        detail = load("virtcert_detail.html")
        client = StubClient(load("virtcert_search_list.html"),
                            {"9000001": detail, "9000002": detail,
                             "9000003": detail})
        # Only spid 9000003 (Carlos Miguel Example) holds Superintendent;
        # make the other two hold something else.
        aide = detail.replace("Superintendent", "Educational Aide III")
        client._details = {"9000001": aide, "9000002": aide,
                           "9000003": detail}
        obs = tc.collect_entry(client, entry())
        self.assertEqual(obs["status"], "VERIFIED")
        self.assertEqual(obs["spid"], "9000003")
        self.assertEqual(obs["record_name"], "Carlos Miguel Example Jr")
        self.assertTrue(obs["expected_credential_found"])
        self.assertEqual(obs["match_count"], 3)
        self.assertEqual(obs["exact_match_count"], 3)

    def test_no_holder_reported_with_summaries(self):
        aide = load("virtcert_detail.html").replace(
            "Superintendent", "Educational Aide III")
        client = StubClient(load("virtcert_search_list.html"),
                            {"9000001": aide, "9000002": aide,
                             "9000003": aide})
        obs = tc.collect_entry(client, entry())
        self.assertEqual(obs["status"], "REPORTED")
        self.assertIsNone(obs["spid"])
        self.assertFalse(obs["expected_credential_found"])
        self.assertEqual(len(obs["exact_match_summaries"]), 3)
        self.assertEqual(obs["exact_match_summaries"][0]["spid"], "9000001")

    def test_multiple_holders_reported(self):
        detail = load("virtcert_detail.html")
        client = StubClient(load("virtcert_search_list.html"),
                            {"9000001": detail, "9000002": detail,
                             "9000003": detail})
        obs = tc.collect_entry(client, entry())
        self.assertEqual(obs["status"], "REPORTED")
        self.assertIsNone(obs["spid"])
        self.assertIn("3 exact-name matches hold", obs["note"])

    def test_zero_matches_unknown(self):
        client = StubClient(load("virtcert_search_zero.html"))
        obs = tc.collect_entry(client, entry())
        self.assertEqual(obs["status"], "UNKNOWN")
        self.assertEqual(obs["match_count"], 0)

    def test_direct_detail_verified(self):
        client = StubClient(load("virtcert_detail.html"))
        obs = tc.collect_entry(client, entry())
        self.assertEqual(obs["status"], "VERIFIED")
        self.assertEqual(obs["record_name"], "Carlos Miguel Example Jr")
        self.assertEqual(obs["match_count"], 1)
        self.assertIsNone(obs["spid"])  # direct pages carry no spid

    def test_too_many_exact_matches_reported(self):
        detail = load("virtcert_detail.html")
        client = StubClient(load("virtcert_search_list.html"),
                            {"9000001": detail, "9000002": detail,
                             "9000003": detail})
        obs = tc.collect_entry(client, entry(), max_details=2)
        self.assertEqual(obs["status"], "REPORTED")
        self.assertEqual(client.detail_calls, [])
        self.assertIn("cap 2", obs["note"])

    def test_collect_continues_on_entry_error(self):
        class Boom:
            delay = 0

            def search(self, *a, **k):
                raise RuntimeError("network down")

            def detail(self, *a, **k):
                raise RuntimeError("network down")

        out = tc.collect([entry(), entry(key="second")], Boom())
        self.assertEqual(out["observations"], [])
        self.assertEqual(len(out["errors"]), 2)
        self.assertEqual(out["errors"][0]["roster_key"], "test-entry")


if __name__ == "__main__":
    unittest.main()
