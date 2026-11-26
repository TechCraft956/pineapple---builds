"""Tests for sensor #31 (USAspending, Starr County). Stdlib unittest only.

All tests run offline on fixtures / a fake ``post`` transport — no live
API calls. Run from the package dir:

    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usaspending as u

RETR = "2026-11-26T18:00:00Z"


def award(**kw):
    row = {
        "Award ID": "36C25724K0908",
        "Recipient Name": "STARR COUNTY HOSPITAL DISTRICT",
        "Award Amount": 928146.94,
        "Awarding Agency": "Department of Veterans Affairs",
        "Awarding Sub Agency": "Department of Veterans Affairs",
        "Start Date": "2022-10-01",
        "End Date": "2023-09-30",
        "Description": "EXPRESS REPORT: OPTION YEAR 4 CLOSEOUT",
        "generated_internal_id": "CONT_AWD_36C25724K0908_3600_36C25719D0025_3600",
    }
    row.update(kw)
    return row


class TestBuildRequest(unittest.TestCase):
    def test_recipient_location_starr_county_3digit(self):
        body = u.build_request("contracts", "2025-01-01", "2026-11-26")
        locs = body["filters"]["recipient_locations"]
        self.assertEqual(locs, [{"country": "USA", "state": "TX", "county": "427"}])
        self.assertEqual(body["filters"]["award_type_codes"], ["A", "B", "C", "D"])

    def test_grants_use_grant_codes_only(self):
        body = u.build_request("grants", "2025-01-01", "2026-11-26")
        self.assertEqual(body["filters"]["award_type_codes"], ["02", "03", "04", "05"])

    def test_contract_and_grant_codes_never_mixed(self):
        c = set(u.build_request("contracts", "2025-01-01", "2026-11-26")
                ["filters"]["award_type_codes"])
        g = set(u.build_request("grants", "2025-01-01", "2026-11-26")
                ["filters"]["award_type_codes"])
        self.assertFalse(c & g, "contract and grant code sets must be disjoint")

    def test_unknown_group_rejected(self):
        with self.assertRaises(ValueError):
            u.build_request("loans", "2025-01-01", "2026-11-26")

    def test_time_period_and_sort(self):
        body = u.build_request("grants", "2025-01-01", "2026-11-26")
        self.assertEqual(body["filters"]["time_period"],
                         [{"start_date": "2025-01-01", "end_date": "2026-11-26"}])
        self.assertEqual(body["sort"], "Start Date")
        self.assertEqual(body["order"], "desc")


class TestNormalize(unittest.TestCase):
    def test_full_record_is_verified(self):
        obs = u.normalize_record(award(), "contracts", RETR)
        self.assertEqual(obs["quality"], "VERIFIED")
        self.assertEqual(obs["award_amount_usd"], 928146.94)
        self.assertEqual(obs["sensor_id"], 31)
        self.assertEqual(obs["geo"], "Starr County, TX (FIPS 48427)")
        self.assertEqual(obs["source_url"],
                         "https://www.usaspending.gov/award/"
                         "CONT_AWD_36C25724K0908_3600_36C25719D0025_3600")
        self.assertEqual(obs["retrieved_at_utc"], RETR)

    def test_missing_amount_is_reported_never_zero_filled(self):
        obs = u.normalize_record(award(**{"Award Amount": None}), "contracts", RETR)
        self.assertEqual(obs["quality"], "REPORTED")
        self.assertIsNone(obs["award_amount_usd"])  # never 0

    def test_missing_start_date_is_reported(self):
        obs = u.normalize_record(award(**{"Start Date": None}), "grants", RETR)
        self.assertEqual(obs["quality"], "REPORTED")
        self.assertIsNone(obs["start_date"])

    def test_missing_recipient_and_amount_is_unknown(self):
        obs = u.normalize_record(
            award(**{"Recipient Name": None, "Award Amount": None}), "grants", RETR)
        self.assertEqual(obs["quality"], "UNKNOWN")

    def test_row_without_award_id_is_skipped(self):
        self.assertIsNone(u.normalize_record(award(**{"Award ID": None}),
                                             "contracts", RETR))
        self.assertIsNone(u.normalize_record(award(**{"Award ID": ""}),
                                             "contracts", RETR))

    def test_pii_redacted_recipient_kept_verbatim_and_flagged(self):
        obs = u.normalize_record(
            award(**{"Recipient Name": "REDACTED DUE TO PII",
                     "Award Amount": 5000.0}), "grants", RETR)
        self.assertEqual(obs["recipient_name"], "REDACTED DUE TO PII")
        self.assertTrue(obs["recipient_redacted"])
        self.assertEqual(obs["quality"], "VERIFIED")  # redaction is not missing data

    def test_award_url_falls_back_to_api_url(self):
        row = award()
        row.pop("generated_internal_id")
        obs = u.normalize_record(row, "contracts", RETR)
        self.assertEqual(obs["source_url"], u.API_URL)


class FakePost:
    """Fake transport: per-group page scripts + count replies."""

    def __init__(self, pages, counts):
        self.pages = pages      # {(group, page): payload}
        self.counts = counts    # {group: {"all": n, "window": n}}
        self.calls = []

    def __call__(self, url, body):
        self.calls.append((url, body))
        if url == u.COUNT_URL:
            group = "contracts" if body["filters"]["award_type_codes"][0] == "A" else "grants"
            key = "window" if "time_period" in body["filters"] else "all"
            n = self.counts[group][key]
            return {"results": {"contracts": n if group == "contracts" else 0,
                                "grants": n if group == "grants" else 0}}
        group = "contracts" if body["filters"]["award_type_codes"][0] == "A" else "grants"
        return self.pages[(group, body["page"])]


def page(rows, has_next):
    return {"results": rows, "page_metadata": {"page": 1, "hasNext": has_next}}


class TestFetchGroup(unittest.TestCase):
    def test_paginates_until_has_next_false(self):
        fake = FakePost(
            {("grants", 1): page([award(**{"Award ID": "G1"})], True),
             ("grants", 2): page([award(**{"Award ID": "G2"})], False)},
            {"grants": {"all": 2, "window": 2}, "contracts": {"all": 0, "window": 0}})
        out = u.fetch_group("grants", "2025-01-01", "2026-11-26", RETR,
                            post=fake, limit=1)
        self.assertEqual([o["award_id"] for o in out["observations"]], ["G1", "G2"])
        self.assertFalse(out["pagination"]["truncated"])
        self.assertEqual(out["pagination"]["pages_fetched"], 2)

    def test_cap_hit_while_has_next_is_flagged_truncated(self):
        fake = FakePost(
            {("contracts", p): page([award(**{"Award ID": f"C{p}"})], True)
             for p in (1, 2, 3)},
            {"grants": {"all": 0, "window": 0}, "contracts": {"all": 99, "window": 99}})
        out = u.fetch_group("contracts", "2025-01-01", "2026-11-26", RETR,
                            post=fake, limit=1, max_pages=2)
        self.assertEqual(len(out["observations"]), 2)
        self.assertTrue(out["pagination"]["truncated"])
        self.assertTrue(out["pagination"]["has_next_at_stop"])

    def test_unkeyable_rows_skipped_and_counted(self):
        fake = FakePost(
            {("grants", 1): page([award(**{"Award ID": None}),
                                  award(**{"Award ID": "G9"})], False)},
            {"grants": {"all": 2, "window": 2}, "contracts": {"all": 0, "window": 0}})
        out = u.fetch_group("grants", "2025-01-01", "2026-11-26", RETR, post=fake)
        self.assertEqual(len(out["observations"]), 1)
        self.assertEqual(out["skipped_no_award_id"], 1)


class TestCollect(unittest.TestCase):
    def test_collect_merges_groups_counts_and_summary(self):
        fake = FakePost(
            {("contracts", 1): page([award()], False),
             ("grants", 1): page([award(**{"Award ID": "SFHDG0047145859",
                                           "Recipient Name": "REDACTED DUE TO PII",
                                           "Award Amount": 5000.0})], False)},
            {"contracts": {"all": 126, "window": 3},
             "grants": {"all": 816, "window": 139}})
        report = u.collect("2025-01-01", "2026-11-26", post=fake)
        self.assertEqual(report["sensor_id"], 31)
        self.assertEqual(report["groups"]["contracts"]["api_total_all_time"], 126)
        self.assertEqual(report["groups"]["grants"]["api_total_in_window"], 139)
        self.assertEqual(report["summary"]["observations_total"], 2)
        self.assertEqual(report["summary"]["by_quality"], {"VERIFIED": 2})
        self.assertEqual(report["summary"]["redacted_recipients"], 1)
        # Dollars summed only over records with an amount.
        self.assertAlmostEqual(
            report["summary"]["total_award_dollars_by_group (records with an amount only)"]["contracts"],
            928146.94)
        self.assertFalse(report["summary"]["truncated_any_group"])

    def test_collect_summary_excludes_missing_amounts_from_dollars(self):
        fake = FakePost(
            {("contracts", 1): page([award(**{"Award Amount": None})], False),
             ("grants", 1): page([], False)},
            {"contracts": {"all": 1, "window": 1},
             "grants": {"all": 0, "window": 0}})
        report = u.collect("2025-01-01", "2026-11-26", post=fake)
        self.assertEqual(report["summary"]["by_quality"], {"REPORTED": 1})
        self.assertEqual(
            report["summary"]["total_award_dollars_by_group (records with an amount only)"],
            {})

    def test_blocked_error_propagates_no_workaround(self):
        def failing_post(url, body):
            raise u.BlockedError("USAspending API HTTP 401 on " + url)
        with self.assertRaises(u.BlockedError):
            u.collect("2025-01-01", "2026-11-26", post=failing_post)


class TestMain(unittest.TestCase):
    def test_main_blocked_exits_nonzero(self):
        import usaspending
        orig = usaspending.default_post

        def boom(url, body):
            raise u.BlockedError("USAspending API unreachable")
        usaspending.default_post = boom
        try:
            self.assertEqual(u.main(["--start", "2025-01-01", "--end", "2026-11-26"]), 2)
        finally:
            usaspending.default_post = orig


if __name__ == "__main__":
    unittest.main()
