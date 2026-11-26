#!/usr/bin/env python3
"""Tests for openfema.py — Pineapple sensors #57 + #73.

Offline only: fixtures are trimmed real OpenFEMA captures
(retrieved 2026-11-26). No network calls.
"""

import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openfema

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures")
RETRIEVED = "2026-11-26T19:00:00Z"
FIPS = "48427"


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeResponse:
    """Minimal urlopen stand-in returning canned JSON bytes."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def envelope(entity, records, count=None):
    return {"metadata": {"skip": 0, "top": 1000, "filter": "",
                         "entityname": entity, "version": "v2",
                         "count": len(records) if count is None else count},
            entity: records}


class TestFipsAndUrls(unittest.TestCase):
    def test_split_fips(self):
        self.assertEqual(openfema.split_fips("48427"), ("48", "427"))

    def test_split_fips_rejects_bad(self):
        for bad in ("4842", "484270", "48A27", ""):
            with self.assertRaises(ValueError, msg=bad):
                openfema.split_fips(bad)

    def test_disaster_filter_uses_3_digit_county(self):
        filt = openfema.build_filter("disasters", FIPS)
        self.assertIn("fipsCountyCode eq '427'", filt)
        self.assertIn("state eq 'TX'", filt)
        self.assertNotIn("48427", filt)

    def test_pa_filter_uses_state_and_county_codes(self):
        filt = openfema.build_filter("public_assistance", FIPS)
        self.assertIn("stateNumberCode eq '48'", filt)
        self.assertIn("countyCode eq '427'", filt)

    def test_nfip_filter_uses_full_fips(self):
        self.assertEqual(openfema.build_filter("nfip_claims", FIPS),
                         "countyCode eq '48427'")

    def test_build_url_versions_and_count(self):
        self.assertIn("/v2/DisasterDeclarationsSummaries",
                      openfema.build_url("disasters", FIPS))
        self.assertIn("/v2/PublicAssistanceFundedProjectsDetails",
                      openfema.build_url("public_assistance", FIPS))
        self.assertIn("/v3/NfipClaims",
                      openfema.build_url("nfip_claims", FIPS))
        self.assertIn("$count=true", openfema.build_url("disasters", FIPS))


class TestCleanAndConvert(unittest.TestCase):
    def test_to_float_null_string_is_none(self):
        self.assertIsNone(openfema._to_float("null"))
        self.assertIsNone(openfema._to_float("Null"))
        self.assertIsNone(openfema._to_float(""))
        self.assertIsNone(openfema._to_float(None))

    def test_to_float_numbers(self):
        self.assertEqual(openfema._to_float(8172.4), 8172.4)
        self.assertEqual(openfema._to_float("  12.5 "), 12.5)

    def test_clean_empty_is_none(self):
        self.assertIsNone(openfema._clean("   "))
        self.assertEqual(openfema._clean(" Starr "), "Starr")


class TestParseDisaster(unittest.TestCase):
    def setUp(self):
        self.recs = load_fixture("openfema_disasters.json")

    def test_real_record_verified(self):
        obs = openfema.parse_disaster(self.recs[0], FIPS,
                                      "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(obs["disaster_number"], 4871)
        self.assertEqual(obs["declaration_date"], "2025-05-21T00:00:00.000Z")
        self.assertEqual(obs["incident_type"], "Flood")
        self.assertEqual(obs["designated_area"], "Starr (County)")
        self.assertIs(obs["pa_program_declared"], False)
        self.assertEqual(obs["county_fips"], FIPS)

    def test_missing_declaration_date_is_reported(self):
        rec = dict(self.recs[0])
        rec["declarationDate"] = None
        obs = openfema.parse_disaster(rec, FIPS, "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "REPORTED")
        self.assertIsNone(obs["declaration_date"])

    def test_wrong_county_is_unknown(self):
        rec = dict(self.recs[0])
        rec["fipsCountyCode"] = "001"
        obs = openfema.parse_disaster(rec, FIPS, "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "UNKNOWN")


class TestParsePaProject(unittest.TestCase):
    def setUp(self):
        self.recs = load_fixture("openfema_pa_projects.json")

    def test_real_record_verified(self):
        obs = openfema.parse_pa_project(self.recs[0], FIPS,
                                        "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(obs["disaster_number"], 1931)
        self.assertEqual(obs["project_amount"], 8172.4)
        self.assertEqual(obs["federal_share_obligated"], 6129.3)
        self.assertEqual(obs["damage_category"], "Roads and Bridges")
        self.assertEqual(obs["county"], "Starr County")

    def test_missing_amount_is_reported_not_zero(self):
        rec = dict(self.recs[0])
        rec["projectAmount"] = None
        obs = openfema.parse_pa_project(rec, FIPS, "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "REPORTED")
        self.assertIsNone(obs["project_amount"])


class TestParseNfipClaim(unittest.TestCase):
    def setUp(self):
        self.recs = load_fixture("openfema_nfip_claims.json")

    def test_real_record_verified(self):
        obs = openfema.parse_nfip_claim(self.recs[0], FIPS,
                                        "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(obs["claim_id"], 9390406)
        self.assertEqual(obs["date_of_loss"], "1981-06-01T00:00:00.000Z")
        self.assertEqual(obs["amount_paid_building"], 353.35)
        self.assertEqual(obs["county_code"], "48427")

    def test_lat_lon_dropped(self):
        obs = openfema.parse_nfip_claim(self.recs[0], FIPS,
                                        "http://x", RETRIEVED)
        self.assertNotIn("latitude", obs)
        self.assertNotIn("longitude", obs)

    def test_null_building_payment_stays_null_not_zero(self):
        obs = openfema.parse_nfip_claim(self.recs[1], FIPS,
                                        "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertIsNone(obs["amount_paid_building"])
        self.assertIsNone(obs["amount_paid_contents"])

    def test_missing_date_of_loss_is_reported(self):
        rec = dict(self.recs[0])
        rec["dateOfLoss"] = None
        obs = openfema.parse_nfip_claim(rec, FIPS, "http://x", RETRIEVED)
        self.assertEqual(obs["label"], "REPORTED")


class TestSummarize(unittest.TestCase):
    def test_pa_totals(self):
        recs = load_fixture("openfema_pa_projects.json")
        obs = [openfema.parse_pa_project(r, FIPS, "http://x", RETRIEVED)
               for r in recs]
        s = openfema.summarize("public_assistance", obs)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["project_amount_total"], 8172.4 + 16760)
        self.assertEqual(s["federal_share_obligated_total"],
                         6129.3 + 12570)
        self.assertEqual(s["by_disaster_number"], {"1709": 1, "1931": 1})

    def test_nfip_totals_skip_nulls(self):
        recs = load_fixture("openfema_nfip_claims.json")
        obs = [openfema.parse_nfip_claim(r, FIPS, "http://x", RETRIEVED)
               for r in recs]
        s = openfema.summarize("nfip_claims", obs)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["amount_paid_building_total"], 353.35)
        self.assertEqual(s["amount_paid_contents_total"], 0)
        self.assertEqual(s["amount_paid_all_total"], 353.35)
        self.assertEqual(s["by_year_of_loss"], {"1981": 1, "1985": 1})

    def test_disaster_summary(self):
        recs = load_fixture("openfema_disasters.json")
        obs = [openfema.parse_disaster(r, FIPS, "http://x", RETRIEVED)
               for r in recs]
        s = openfema.summarize("disasters", obs)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["disaster_numbers"], [4586, 4871])
        self.assertEqual(s["declaration_date_range"],
                         ["2021-02-19T00:00:00.000Z",
                          "2025-05-21T00:00:00.000Z"])
        self.assertEqual(s["by_incident_type"],
                         {"Flood": 1, "Severe Ice Storm": 1})

    def test_sum_all_null_is_none(self):
        self.assertIsNone(openfema._sum([None, None]))
        self.assertEqual(openfema._date_range([]), [None, None])


class TestFetchWithFakeOpener(unittest.TestCase):
    def _opener(self, payloads):
        seen = []

        def fake(request, timeout=None):
            seen.append(request)
            url = request.full_url
            for key, payload in payloads.items():
                if key in url:
                    return FakeResponse(payload)
            raise AssertionError(f"unexpected URL {url}")

        fake.seen = seen
        return fake

    def test_full_run_offline(self):
        payloads = {
            "DisasterDeclarationsSummaries": envelope(
                "DisasterDeclarationsSummaries",
                load_fixture("openfema_disasters.json")),
            "PublicAssistanceFundedProjectsDetails": envelope(
                "PublicAssistanceFundedProjectsDetails",
                load_fixture("openfema_pa_projects.json")),
            "NfipClaims": envelope(
                "NfipClaims", load_fixture("openfema_nfip_claims.json")),
        }
        result = openfema.fetch_observations(
            fips=FIPS, opener=self._opener(payloads))
        self.assertEqual(result["county_fips"], FIPS)
        self.assertEqual(result["summary"]["observations_total"], 6)
        self.assertEqual(result["summary"]["disasters_count"], 2)
        self.assertEqual(result["summary"]["public_assistance_projects"], 2)
        self.assertEqual(result["summary"]["nfip_claims"], 2)
        self.assertEqual(result["summary"]["by_label"]["VERIFIED"], 6)
        self.assertEqual(
            result["legs"]["public_assistance"]["summary"]
            ["project_amount_total"], 8172.4 + 16760)
        self.assertEqual(
            result["summary"]["nfip_amount_paid_all_total"], 353.35)
        for leg in result["legs"].values():
            self.assertEqual(leg["status"], "OK")

    def test_accept_json_header_sent(self):
        payloads = {
            "DisasterDeclarationsSummaries": envelope(
                "DisasterDeclarationsSummaries", []),
            "PublicAssistanceFundedProjectsDetails": envelope(
                "PublicAssistanceFundedProjectsDetails", []),
            "NfipClaims": envelope("NfipClaims", []),
        }
        opener = self._opener(payloads)
        openfema.fetch_observations(fips=FIPS, opener=opener)
        self.assertEqual(len(opener.seen), 3)
        for req in opener.seen:
            self.assertEqual(req.get_header("Accept"), "application/json")

    def test_one_dead_leg_does_not_kill_others(self):
        def flaky(request, timeout=None):
            if "NfipClaims" in request.full_url:
                raise IOError("connection refused")
            entity = ("DisasterDeclarationsSummaries"
                      if "DisasterDeclarationsSummaries" in request.full_url
                      else "PublicAssistanceFundedProjectsDetails")
            return FakeResponse(envelope(entity, []))

        result = openfema.fetch_observations(fips=FIPS, opener=flaky)
        self.assertTrue(
            result["legs"]["nfip_claims"]["status"].startswith("ERROR:"))
        self.assertEqual(result["legs"]["disasters"]["status"], "OK")
        self.assertEqual(result["legs"]["public_assistance"]["status"], "OK")
        self.assertEqual(result["summary"]["nfip_claims"], 0)
        self.assertIsNone(
            result["summary"]["nfip_amount_paid_all_total"])


if __name__ == "__main__":
    unittest.main()
