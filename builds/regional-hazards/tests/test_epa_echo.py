"""Tests for sensors #53 + #75 (EPA ECHO + TCEQ/FRS registry) — stdlib unittest.

Fixture-based; no network is touched by these tests. Fixtures are trimmed
captures of the live EPA/TCEQ payloads (2026-11-26): ECHO all-data / CWA /
AIR / RCRA / SDWA summaries, a 4-facility get_facility_info slice, a
5-row FRS program-facility slice (with duplicate Registry IDs), the 3
Starr County TCEQ outfalls, an empty TRI result, and the literal ECHO
error payload for a bad query.
"""
import json
import os
import sys
import unittest
import urllib.error
import io

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import epa_echo  # noqa: E402

RETRIEVED = "2026-11-26T19:00:00Z"


def load_fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


def fetcher_for(mapping):
    """Build a stub fetcher serving fixture payloads by URL substring."""
    def fetcher(url, params, timeout):
        for needle, payload in mapping.items():
            if needle in url:
                return json.dumps(payload).encode("utf-8")
        raise AssertionError(f"unexpected URL {url}")
    return fetcher


class TestMoneyAndIntParsing(unittest.TestCase):
    def test_parse_money_dollar_comma(self):
        self.assertEqual(epa_echo.parse_money("$53,692"), 53692.0)
        self.assertEqual(epa_echo.parse_money("$52,492"), 52492.0)
        self.assertEqual(epa_echo.parse_money("$0"), 0.0)
        self.assertEqual(epa_echo.parse_money("$1,200"), 1200.0)

    def test_parse_money_missing_stays_none(self):
        self.assertIsNone(epa_echo.parse_money(None))
        self.assertIsNone(epa_echo.parse_money(""))
        self.assertIsNone(epa_echo.parse_money("not-a-number"))

    def test_parse_int_strings(self):
        self.assertEqual(epa_echo.parse_int("389"), 389)
        self.assertEqual(epa_echo.parse_int("0"), 0)
        self.assertIsNone(epa_echo.parse_int(None))
        self.assertIsNone(epa_echo.parse_int("n/a"))


class TestEchoSummaryParsing(unittest.TestCase):
    def test_all_data_summary_counts(self):
        s = epa_echo.parse_echo_summary(load_fixture("epa_echo_all_summary.json"))
        self.assertEqual(s["QueryRows"], 389)
        self.assertEqual(s["CAARows"], 12)
        self.assertEqual(s["CWARows"], 91)
        self.assertEqual(s["RCRRows"], 29)
        self.assertEqual(s["TRIRows"], 0)
        self.assertEqual(s["SVRows"], 1)
        self.assertEqual(s["CVRows"], 6)
        self.assertEqual(s["V3Rows"], 7)
        self.assertEqual(s["FEARows"], 3)
        self.assertEqual(s["INSPRows"], 8)
        self.assertEqual(s["total_penalties_usd"], 53692.0)
        self.assertEqual(s["message"], "Success")

    def test_cwa_summary_violations_last_4q(self):
        s = epa_echo.parse_echo_summary(load_fixture("epa_echo_cwa_summary.json"))
        self.assertEqual(s["QueryRows"], 112)
        self.assertEqual(s["VioLast4QRows"], 5)
        self.assertEqual(s["total_penalties_usd"], 52492.0)

    def test_air_summary(self):
        s = epa_echo.parse_echo_summary(load_fixture("epa_echo_air_summary.json"))
        self.assertEqual(s["QueryRows"], 12)
        self.assertEqual(s["INSPRows"], 2)
        self.assertEqual(s["total_penalties_usd"], 0.0)

    def test_rcra_summary_zero_violations(self):
        s = epa_echo.parse_echo_summary(load_fixture("epa_echo_rcra_summary.json"))
        self.assertEqual(s["QueryRows"], 29)
        self.assertEqual(s["SVRows"], 0)
        self.assertEqual(s["CVRows"], 0)
        self.assertEqual(s["FEARows"], 0)

    def test_sdwa_summary(self):
        s = epa_echo.parse_echo_summary(load_fixture("epa_echo_sdwa_summary.json"))
        self.assertEqual(s["QueryRows"], 22)
        self.assertEqual(s["SVRows"], 3)
        self.assertEqual(s["CVRows"], 10)
        self.assertEqual(s["V3Rows"], 10)
        self.assertEqual(s["INSPRows"], 12)

    def test_error_payload_is_recorded_not_crash(self):
        s = epa_echo.parse_echo_summary(load_fixture("epa_echo_error.json"))
        self.assertIn("error", s)
        self.assertIn("could not process", s["error"]["ErrorMessage"])


class TestEchoFacilityParsing(unittest.TestCase):
    def setUp(self):
        payload = load_fixture("epa_echo_facility_info.json")
        self.facilities = [epa_echo.parse_echo_facility(f, RETRIEVED)
                           for f in payload["Results"]["Facilities"]]

    def test_four_facilities_parsed(self):
        self.assertEqual(len(self.facilities), 4)

    def test_plain_facility_no_programs(self):
        cafe = [f for f in self.facilities
                if f["facility_name"] == "1017 CAFE"][0]
        self.assertEqual(cafe["city"], "SAN ISIDRO")
        self.assertEqual(cafe["registry_id"], "110054092110")
        self.assertEqual(cafe["programs"], {"CAA": False, "CWA": False,
                                            "RCRA": False, "SDWA": False,
                                            "TRI": False, "GHG": False})
        self.assertIsNone(cafe["quarters_with_noncompliance"])
        self.assertEqual(cafe["total_penalties_usd"], 0.0)
        self.assertEqual(cafe["status"], "VERIFIED")
        self.assertTrue(cafe["programs_inferred"])

    def test_rcra_facility_inferred(self):
        mmm = [f for f in self.facilities
               if f["facility_name"] == "3M NATIONAL ADVTSNG"][0]
        self.assertTrue(mmm["programs"]["RCRA"])
        self.assertFalse(mmm["programs"]["CWA"])
        self.assertEqual(mmm["rcra_permit_types"], "VSQG")
        self.assertEqual(mmm["quarters_with_noncompliance"], 0)

    def test_snc_facility_with_penalties(self):
        union = [f for f in self.facilities
                 if f["facility_name"] == "UNION WATER SUPPLY WWTP"][0]
        self.assertEqual(union["snc_flag"], "Y")
        self.assertEqual(union["quarters_with_noncompliance"], 11)
        self.assertEqual(union["total_penalties_usd"], 52492.0)
        self.assertTrue(union["programs"]["CWA"])

    def test_water_plant_noncompliance_quarters(self):
        swtp = [f for f in self.facilities
                if "SWTP 1" in f["facility_name"]][0]
        self.assertEqual(swtp["quarters_with_noncompliance"], 7)
        self.assertEqual(swtp["total_penalties_usd"], 0.0)

    def test_every_facility_has_source_and_timestamp(self):
        for f in self.facilities:
            self.assertTrue(f["source_url"].startswith("https://echodata.epa.gov/"))
            self.assertEqual(f["retrieved_at_utc"], RETRIEVED)
            self.assertIn(f["status"], ("VERIFIED", "REPORTED", "UNKNOWN", "BLOCKED"))


class TestTri(unittest.TestCase):
    def test_starr_tri_is_verified_zero(self):
        fetcher = fetcher_for({"tri.tri_facility": load_fixture("epa_echo_tri_empty.json")})
        leg = epa_echo.fetch_tri(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "VERIFIED")
        self.assertEqual(leg["facility_count"], 0)
        self.assertEqual(leg["facilities"], [])
        self.assertIn("TRIRows=0", leg["cross_check"])

    def test_harris_control_query_returns_rows(self):
        # Proves the county filter syntax works: Starr [] is real, not a bug.
        rows = load_fixture("epa_echo_tri_harris_sample.json")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["county_name"], "HARRIS")
        obs = epa_echo.parse_tri_row(rows[0], RETRIEVED)
        self.assertEqual(obs["facility_name"], "DOW HALTERMANN PLANT 2")
        self.assertEqual(obs["status"], "VERIFIED")


class TestFrs(unittest.TestCase):
    def test_registry_ids_are_record_ids_not_facility_count(self):
        # The live fixture shows the same site under two Registry IDs
        # (EXPANDO: AIRS/AFS vs TX-TCEQ ACR), so distinct IDs != facilities.
        fetcher = fetcher_for(
            {"frs_program_facility": load_fixture("epa_echo_frs_sample.json")})
        leg = epa_echo.fetch_frs(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "VERIFIED")
        self.assertEqual(leg["program_row_count"], 5)
        self.assertEqual(leg["distinct_registry_ids"], 5)
        self.assertEqual(len(leg["facilities"]), 5)
        self.assertIn("upper bound", leg["note"])

    def test_same_registry_id_merges_programs(self):
        rows = [
            {"registry_id": "110000000001", "primary_name": "TEST PLANT",
             "city_name": "ROMA", "county_name": "STARR",
             "location_address": "1 TEST RD", "postal_code": "78582",
             "pgm_sys_acrnm": "NPDES", "pgm_sys_id": "TX0000001",
             "epa_region_code": "06"},
            {"registry_id": "110000000001", "primary_name": "TEST PLANT",
             "city_name": "ROMA", "county_name": "STARR",
             "location_address": "1 TEST RD", "postal_code": "78582",
             "pgm_sys_acrnm": "RCRAINFO", "pgm_sys_id": "TXD000000001",
             "epa_region_code": "06"},
        ]
        fetcher = fetcher_for({"frs_program_facility": rows})
        leg = epa_echo.fetch_frs(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["program_row_count"], 2)
        self.assertEqual(leg["distinct_registry_ids"], 1)
        self.assertEqual(len(leg["facilities"]), 1)
        self.assertEqual(sorted(leg["facilities"][0]["program_acronyms"]),
                         ["NPDES", "RCRAINFO"])

    def test_walmart_programs_merged(self):
        fetcher = fetcher_for(
            {"frs_program_facility": load_fixture("epa_echo_frs_sample.json")})
        leg = epa_echo.fetch_frs(RETRIEVED, fetcher=fetcher)
        walmart = [f for f in leg["facilities"]
                   if f["primary_name"] == "WAL MART SUPERCENTER 1958"][0]
        self.assertEqual(len(walmart["program_acronyms"]),
                         len(set(walmart["program_acronyms"])))
        self.assertIn("TX-TCEQ ACR", walmart["program_acronyms"])

    def test_frs_row_parsing_trims_postal(self):
        rec = epa_echo.parse_frs_row({
            "registry_id": "110034210477",
            "primary_name": "EXPANDO COMPRESSOR STATION",
            "city_name": "DELMITA", "county_name": "STARR",
            "location_address": "5 1 2 MILES S OF FM 490",
            "postal_code": "78596 ", "pgm_sys_acrnm": "TX-TCEQ ACR",
            "pgm_sys_id": "RN102326915", "epa_region_code": "06"})
        self.assertEqual(rec["postal_code"], "78596")
        self.assertEqual(rec["registry_id"], "110034210477")


class TestTceqOutfalls(unittest.TestCase):
    def test_three_starr_outfalls(self):
        fetcher = fetcher_for(
            {"TCEQ_Permitted_Wastewater_Outfalls":
             load_fixture("epa_echo_tceq_outfalls.json")})
        leg = epa_echo.fetch_tceq_outfalls(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "VERIFIED")
        self.assertEqual(leg["outfall_count"], 3)
        self.assertEqual(leg["permittees"],
                         {"CITY OF ROMA": 2, "CITY OF RIO GRANDE CITY": 1})

    def test_outfall_fields(self):
        payload = load_fixture("epa_echo_tceq_outfalls.json")
        obs = epa_echo.parse_tceq_outfall(payload["features"][0], RETRIEVED)
        self.assertEqual(obs["permittee"], "CITY OF ROMA")
        self.assertEqual(obs["county"], "STARR")
        self.assertEqual(obs["permit_number"], "11212-003")
        self.assertEqual(obs["status"], "VERIFIED")

    def test_arcgis_error_raises(self):
        def fetcher(url, params, timeout):
            return json.dumps({"error": {"code": 400, "message": "bad"}}).encode("utf-8")

        with self.assertRaises(RuntimeError):
            epa_echo.arcgis_query("https://example.invalid/query",
                                  {"where": "1=1"}, fetcher=fetcher)


class TestCollectEndToEnd(unittest.TestCase):
    def test_collect_with_stubbed_fetchers(self):
        mapping = {
            "echo_rest_services.get_facilities": load_fixture("epa_echo_all_summary.json"),
            "echo_rest_services.get_facility_info": load_fixture("epa_echo_facility_info.json"),
            "cwa_rest_services": load_fixture("epa_echo_cwa_summary.json"),
            "air_rest_services": load_fixture("epa_echo_air_summary.json"),
            "rcra_rest_services": load_fixture("epa_echo_rcra_summary.json"),
            "sdw_rest_services": load_fixture("epa_echo_sdwa_summary.json"),
            "tri.tri_facility": load_fixture("epa_echo_tri_empty.json"),
            "frs_program_facility": load_fixture("epa_echo_frs_sample.json"),
            "TCEQ_Permitted_Wastewater_Outfalls": load_fixture("epa_echo_tceq_outfalls.json"),
        }
        doc = epa_echo.collect(fetcher=fetcher_for(mapping))
        self.assertEqual(doc["sensor_ids"], [53, 75])
        self.assertEqual(doc["county_fips"], "48427")
        s = doc["summary"]
        self.assertEqual(s["echo_facilities_total"], 4)
        self.assertEqual(s["echo_program_rows"], {"CAA": 12, "CWA": 91,
                                                  "RCRA": 29, "TRI": 0})
        self.assertEqual(s["echo_total_penalties_usd"], 53692.0)
        self.assertEqual(s["cwa_facilities"], 112)
        self.assertEqual(s["cwa_violations_last_4q"], 5)
        self.assertEqual(s["sdwa_systems"], 22)
        self.assertEqual(s["tri_facilities"], 0)
        self.assertEqual(s["frs_program_rows"], 5)
        self.assertEqual(s["frs_distinct_registry_ids"], 5)
        self.assertEqual(s["tceq_outfalls_starr"], 3)
        self.assertEqual(s["facilities_with_noncompliance_quarters"], 2)
        self.assertEqual(s["facilities_with_penalties"], 1)
        self.assertEqual(s["facilities_flagged_snc"], 1)
        # Observations: 4 ECHO facilities + 5 FRS registry records
        # + 3 outfalls + 1 TRI zero record.
        self.assertEqual(len(doc["observations"]), 13)
        for obs in doc["observations"]:
            self.assertIn(obs["status"],
                          ("VERIFIED", "REPORTED", "UNKNOWN", "BLOCKED"))
            self.assertIn("source_url", obs)
            self.assertIn("retrieved_at_utc", obs)
        self.assertIn("ofmpub_echo_404", doc["superseded_paths"])

    def test_failed_leg_is_unknown_not_crash(self):
        def failing(url, params, timeout):
            raise urllib.error.URLError("boom")

        leg = epa_echo.fetch_echo_summary("echo_all_summary",
                                          epa_echo.ECHO_ALL_SUMMARY_URL,
                                          RETRIEVED, fetcher=failing)
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertIn("boom", leg["error"])


if __name__ == "__main__":
    unittest.main()
