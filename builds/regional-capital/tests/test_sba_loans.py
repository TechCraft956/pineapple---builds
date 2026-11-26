"""Tests for sba_loans.py (sensor #72). Stdlib unittest only, no network.

Run:  python3 -m unittest discover -s tests -v
from builds/regional-capital/
"""

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sba_loans  # noqa: E402

SEVEN_A_HEADER = (
    '"AsOfDate","Program","LocationID","BorrName","BorrStreet","BorrCity",'
    '"BorrState","BorrZip","BankName","GrossApproval","SBAGuaranteedApproval",'
    '"ApprovalDate","ApprovalFY","NaicsCode","NaicsDescription",'
    '"ProjectCounty","ProjectState","LoanStatus","TermInMonths",'
    '"JobsSupported","GrossChargeOffAmount"\n'
)

ROW_7A_STARR = (
    '"2026-09-30"," 7A","0000001","Rio Grande Bakery LLC","123 Main St",'
    '"RIO GRANDE CITY","TX","78582","First National Bank","250000.0",'
    '"187500.0","2023-04-12","2023","311811","Retail Bakeries","STARR",'
    '"TX","P I F","120.0","4.0","0.0"\n'
)

ROW_7A_MISSING_AMOUNT = (
    '"2026-09-30"," 7A","0000002","Roma Tire Shop","9 Elm St","ROMA","TX",'
    '"78584","Second Bank","","","2024-01-05","2024","441110",'
    '"New Car Dealers","STARR","TX","EXEMPT","84.0","",""\n'
)

ROW_7A_HIDALGO = (
    '"2026-09-30"," 7A","0000003","McAllen Cafe LLC","5 Oak Ave","MCALLEN",'
    '"TX","78501","Third Bank","100000.0","75000.0","2022-06-01","2022",'
    '"722511","Full-Service Restaurants","HIDALGO","TX","P I F","60.0",'
    '"2.0","0.0"\n'
)

ROW_7A_OTHER_STATE = (
    '"2026-09-30"," 7A","0000004","Phoenix Diner LLC","1 Desert Rd",'
    '"PHOENIX","AZ","85001","Fourth Bank","90000.0","67500.0","2021-03-03",'
    '"2021","722511","Full-Service Restaurants","MARICOPA","AZ","P I F",'
    '"60.0","1.0","0.0"\n'
)

ROW_7A_CITY_FALLBACK = (
    '"2026-09-30"," 7A","0000005","La Grulla Market","77 County Rd",'
    '"LA GRULLA","TX","78548","Fifth Bank","60000.0","45000.0","2020-11-20",'
    '"2021","445110","Supermarkets","","TX","EXEMPT","120.0","3.0","0.0"\n'
)

ROW_504_STARR = (
    '"2026-09-30","504","0000006","Starr Storage LLC","200 Industrial Pkwy",'
    '"RIO GRANDE CITY","TX","78582","South TX CDC","",'
    '"RIO GRANDE CITY","TX","78582","Lone Star Bank","RIO GRANDE CITY",'
    '"TX","400000.0","500000.0","2019-05-15","2019","",'
    '"240.0","531130","Lessors of Miniwarehouses","",'
    '"STARR","TX","PIF","","","0.0"\n'
)


class TestCountyMatching(unittest.TestCase):
    def test_starr_primary_match(self):
        row = {"ProjectCounty": "STARR", "ProjectState": "TX"}
        self.assertEqual(sba_loans.match_county(row), "starr")

    def test_case_and_whitespace_tolerant(self):
        row = {"ProjectCounty": "  Starr ", "ProjectState": " tx "}
        self.assertEqual(sba_loans.match_county(row), "starr")

    def test_non_starr_filtered(self):
        self.assertIsNone(sba_loans.match_county(
            {"ProjectCounty": "HIDALGO", "ProjectState": "TX"}))
        self.assertIsNone(sba_loans.match_county(
            {"ProjectCounty": "STARR", "ProjectState": "NM"}))

    def test_rgv_secondary_opt_in(self):
        row = {"ProjectCounty": "HIDALGO", "ProjectState": "TX"}
        self.assertEqual(sba_loans.match_county(row, include_rgv=True), "rgv")
        self.assertIsNone(sba_loans.match_county(row, include_rgv=False))

    def test_city_fallback_when_county_blank(self):
        row = {"ProjectCounty": "", "ProjectState": "TX",
               "BorrCity": "ROMA", "BorrState": "TX"}
        self.assertEqual(sba_loans.match_county(row), "starr")

    def test_city_fallback_rejected_for_unknown_city(self):
        row = {"ProjectCounty": "", "ProjectState": "TX",
               "BorrCity": "MCALLEN", "BorrState": "TX"}
        self.assertIsNone(sba_loans.match_county(row))


class TestObservationBuilding(unittest.TestCase):
    def _obs(self, csv_text, program="7a"):
        stream = io.StringIO(csv_text)
        obs = list(sba_loans.iter_matching_rows(
            stream, program,
            "https://example.invalid/FOIA.csv", "2026-11-26T00:00:00Z"))
        return obs

    def test_starr_7a_row_verified(self):
        obs = self._obs(SEVEN_A_HEADER + ROW_7A_STARR)
        self.assertEqual(len(obs), 1)
        o = obs[0]
        self.assertEqual(o["label"], "VERIFIED")
        self.assertEqual(o["program"], "7a")
        self.assertEqual(o["borrower_name"], "Rio Grande Bakery LLC")
        self.assertEqual(o["gross_approval"], 250000.0)
        self.assertEqual(o["approval_date"], "2023-04-12")
        self.assertEqual(o["loan_status"], "P I F")
        self.assertEqual(o["county_fips"], "48427")
        self.assertEqual(o["scope"], "starr")

    def test_street_addresses_never_emitted(self):
        obs = self._obs(SEVEN_A_HEADER + ROW_7A_STARR)
        blob = json.dumps(obs)
        self.assertNotIn("123 Main St", blob)
        self.assertNotIn("BorrStreet", blob)
        self.assertNotIn("BankStreet", blob)

    def test_missing_amount_is_reported_not_zero(self):
        obs = self._obs(SEVEN_A_HEADER + ROW_7A_MISSING_AMOUNT)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["label"], "REPORTED")
        self.assertIsNone(obs[0]["gross_approval"])
        self.assertIsNone(obs[0]["sba_guaranteed_approval"])

    def test_other_rows_filtered_out(self):
        obs = self._obs(SEVEN_A_HEADER + ROW_7A_HIDALGO + ROW_7A_OTHER_STATE)
        self.assertEqual(obs, [])

    def test_rgv_rows_included_with_flag(self):
        stream = io.StringIO(SEVEN_A_HEADER + ROW_7A_HIDALGO)
        obs = list(sba_loans.iter_matching_rows(
            stream, "7a", "https://example.invalid/x.csv",
            "2026-11-26T00:00:00Z", include_rgv=True))
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["scope"], "rgv")
        self.assertIsNone(obs[0]["county_fips"])

    def test_city_fallback_row_is_unknown(self):
        obs = self._obs(SEVEN_A_HEADER + ROW_7A_CITY_FALLBACK)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["label"], "UNKNOWN")
        self.assertIsNone(obs[0]["project_county"])

    def test_504_row_uses_cdc_lender(self):
        header_504 = (
            '"AsOfDate","Program","LocationID","BorrName","BorrStreet",'
            '"BorrCity","BorrState","BorrZip","CDC_Name","CDC_Street",'
            '"CDC_City","CDC_State","CDC_Zip","ThirdPartyLender_Name",'
            '"ThirdPartyLender_City","ThirdPartyLender_State",'
            '"ThirdPartyDollars","GrossApproval","ApprovalDate","ApprovalFY",'
            '"FirstDisbursementDate","TermInMonths","NaicsCode",'
            '"NaicsDescription","FranchiseCode","ProjectCounty",'
            '"ProjectState","LoanStatus","PaidInFullDate","ChargeOffDate",'
            '"GrossChargeOffAmount"\n'
        )
        obs = self._obs(header_504 + ROW_504_STARR, program="504")
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["label"], "VERIFIED")
        self.assertEqual(obs[0]["lender"], "South TX CDC / Lone Star Bank")
        self.assertEqual(obs[0]["third_party_dollars"], 400000.0)
        self.assertEqual(obs[0]["gross_approval"], 500000.0)


class TestDiscovery(unittest.TestCase):
    def test_discovers_current_stamp_from_dataset_page(self):
        html = ('<a href="x">FOIA_7a_FY2020_Present_asof_260930.csv</a>'
                '<a href="y">FOIA_504_FY2010_Present_asof_260930.csv</a>')

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return html.encode()

        urls, stamp, discovered = sba_loans.discover_file_urls(
            opener=lambda url, timeout=60: FakeResp())
        self.assertTrue(discovered)
        self.assertEqual(stamp, "260930")
        self.assertIn("FOIA_7a_FY2020_Present_asof_260930.csv", urls)
        self.assertIn("FOIA_504_FY2010_Present_asof_260930.csv", urls)

    def test_discovery_failure_falls_back(self):
        def boom(url, timeout=60):
            raise ConnectionError("no network")

        urls, stamp, discovered = sba_loans.discover_file_urls(opener=boom)
        self.assertFalse(discovered)
        self.assertEqual(stamp, sba_loans.FALLBACK_ASOF)
        self.assertTrue(any("FOIA_7a_FY2020_Present" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
