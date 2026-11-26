"""Tests for procurement.py (sensor #82). Stdlib unittest only, no network.

Run:  python3 -m unittest discover -s tests -v
from builds/regional-capital/
"""

import json
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import procurement  # noqa: E402

ESBD_PAGE_HTML = """
<html><body>
<div>Page 1 of 2,531 Pages</div>
<div class="esbd-result-row"><div class="esbd-result-title"><a href="/esbd/6512-28-001_1126">
6512-28-001_1126 Roadwork in Starr County </a></div>
<div class="esbd-result-body-columns"><div class="esbd-result-column">
<p><strong>Solicitation ID: </strong> 6512-28-001_1126 </p>
<p><strong>Due Date: </strong> 12/15/2026 </p>
<p><strong>Due Time: </strong> 2:00 PM </p></div>
<div class="esbd-result-column">
<p><strong>Agency/Texas SmartBuy Member Number: </strong> 601 </p>
<p><strong>Status: </strong> Posted </p>
<p><strong>Posting Date: </strong> 11/20/2026 </p></div>
<div class="esbd-result-body-secondary">
<p class="esbd-small"><strong>Created Date: </strong> 11/20/2026 9:00 am </p>
<p class="esbd-separator"> | </p>
<p class="esbd-small"><strong>Last Updated: </strong> 11/22/2026 3:01 pm </p>
</div></div></div>
<div class="esbd-result-row"><div class="esbd-result-title"><a href="/esbd/ABC123">
Office Supplies for Hidalgo County </a></div>
<div class="esbd-result-body-columns"><div class="esbd-result-column">
<p><strong>Solicitation ID: </strong> ABC123 </p>
<p><strong>Due Date: </strong> </p>
<p><strong>Due Time: </strong> 2:00 PM </p></div>
<div class="esbd-result-column">
<p><strong>Agency/Texas SmartBuy Member Number: </strong> C1080 </p>
<p><strong>Status: </strong> Posted </p>
<p><strong>Posting Date: </strong> 11/21/2026 </p></div>
<div class="esbd-result-body-secondary">
<p class="esbd-small"><strong>Created Date: </strong> 11/21/2026 8:00 am </p>
<p class="esbd-separator"> | </p>
<p class="esbd-small"><strong>Last Updated: </strong> 11/21/2026 8:00 am </p>
</div></div></div>
<div class="esbd-result-row"><div class="esbd-result-title"><a href="/esbd/ZZZ999">
Lawn Care in Dallas </a></div>
<div class="esbd-result-body-columns"><div class="esbd-result-column">
<p><strong>Solicitation ID: </strong> ZZZ999 </p>
<p><strong>Due Date: </strong> 12/01/2026 </p>
<p><strong>Due Time: </strong> 2:00 PM </p></div>
<div class="esbd-result-column">
<p><strong>Agency/Texas SmartBuy Member Number: </strong> 601 </p>
<p><strong>Status: </strong> Posted </p>
<p><strong>Posting Date: </strong> 11/19/2026 </p></div>
<div class="esbd-result-body-secondary">
<p class="esbd-small"><strong>Created Date: </strong> 11/19/2026 8:00 am </p>
<p class="esbd-separator"> | </p>
<p class="esbd-small"><strong>Last Updated: </strong> 11/19/2026 8:00 am </p>
</div></div></div>
</body></html>
"""

ESBD_PAGE2_HTML = """
<html><body>
<div>Page 2 of 2,531 Pages</div>
<div class="esbd-result-row"><div class="esbd-result-title"><a href="/esbd/RGV001">
UTRGV Campus Renovation </a></div>
<div class="esbd-result-body-columns"><div class="esbd-result-column">
<p><strong>Solicitation ID: </strong> RGV001 </p>
<p><strong>Due Date: </strong> 12/20/2026 </p>
<p><strong>Due Time: </strong> 3:00 PM </p></div>
<div class="esbd-result-column">
<p><strong>Agency/Texas SmartBuy Member Number: </strong> 746 </p>
<p><strong>Status: </strong> Posted </p>
<p><strong>Posting Date: </strong> 11/18/2026 </p></div>
<div class="esbd-result-body-secondary">
<p class="esbd-small"><strong>Created Date: </strong> 11/18/2026 8:00 am </p>
<p class="esbd-separator"> | </p>
<p class="esbd-small"><strong>Last Updated: </strong> 11/18/2026 8:00 am </p>
</div></div></div>
</body></html>
"""

DIR_CONTRACT_ROW = {
    "rfo_number": "DIR-CPO-TMP-608",
    "rfo_description": "Flood Early Warning Systems",
    "contract_number": "DIR-CPO-6269",
    "primary_vendor_name": "AT&T Enterprises, LLC",
    "primary_vendor_hub_status": "N/A",
    "reseller_name": "Acme Reseller",
    "reseller_hub_status": "Non HUB",
    "contract_manager": "cheryl dukes",
    "contract_manager_email": "cheryl.dukes@dir.texas.gov",
    "vendor_contact": "Sonia Cardenas",
    "vendor_contact_email": "sc5467@att.com",
    "vendor_contact_phone_number": "555-0100",
    "contract_start": "2026-10-30T00:00:00.000",
    "contract_termination_date": "2028-10-30T00:00:00.000",
    "contract_type": "Hardware",
    "contract_subtype": "FEWS",
}

DIR_SALE_ROW = {
    "fiscal_year": "2026",
    "customer_name": "Starr County",
    "customer_state": "TX",
    "customer_type": "County",
    "customer_contact": "Jane Doe",
    "vendor_name": "Xerox Corporation",
    "purchase_amount": "200.380000",
    "contract_number": "DIR-CPO-5425",
    "contract_category": "Cooperative",
    "rfo_number": "DIR-CPO-TMP-123",
    "rfo_description": "Managed Print Services",
    "contract_type": "Hardware",
    "contract_subtype": "Printers",
    "reporting_month": "2026-10-01T00:00:00.000",
    "order_date": "2026-10-05T00:00:00.000",
    "invoice_date": "2026-10-12T00:00:00.000",
}

TXDOT_ROW_A = {
    "controlling_project_id_ccsj": "1057-03-060",
    "county": "Starr",
    "highway": "US 83",
    "project_classification": "Widen Non-Freeway",
    "let_type": "Statewide Let",
    "district_division": "Pharr",
    "bids_will_be_opened_date": "2027-01-06T13:00:00.000",
    "bid_recieved_until_date_and": "2027-01-06T13:00:00.000",
    "sealed_engineer_s_estimate": "5174096.72",
    "bid_item_code": "100",
    "bid_item_description": "PREPARING ROW",
}
TXDOT_ROW_B = dict(TXDOT_ROW_A, bid_item_code="200",
                   bid_item_description="EXCAVATION",
                   sealed_engineer_s_estimate="6000000.00")


class FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def make_opener(routes, seen=None):
    """routes: list of (substring, payload-bytes). Records requested URLs."""
    def opener(req, timeout=60):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if seen is not None:
            seen.append(url)
        for needle, payload in routes:
            if needle in url:
                return FakeResp(payload)
        raise AssertionError(f"unexpected URL: {url}")
    return opener


def jbytes(obj):
    return json.dumps(obj).encode()


class TestEsbdParsing(unittest.TestCase):
    def test_parse_full_page(self):
        rows, total = procurement.parse_esbd_listing(ESBD_PAGE_HTML)
        self.assertEqual(len(rows), 3)
        self.assertEqual(total, 2531)
        r = rows[0]
        self.assertEqual(r["solicitation_id"], "6512-28-001_1126")
        self.assertEqual(r["title"],
                         "6512-28-001_1126 Roadwork in Starr County")
        self.assertEqual(r["due_date"], "12/15/2026")
        self.assertEqual(r["due_time"], "2:00 PM")
        self.assertEqual(r["agency_number"], "601")
        self.assertEqual(r["status"], "Posted")
        self.assertEqual(r["posting_date"], "11/20/2026")
        self.assertEqual(r["url_path"], "/esbd/6512-28-001_1126")

    def test_missing_due_date_parses_as_none(self):
        rows, _ = procurement.parse_esbd_listing(ESBD_PAGE_HTML)
        self.assertIsNone(rows[1]["due_date"])

    def test_total_pages_none_when_absent(self):
        rows, total = procurement.parse_esbd_listing("<html></html>")
        self.assertEqual(rows, [])
        self.assertIsNone(total)


class TestEsbdMatching(unittest.TestCase):
    def test_starr_title_match(self):
        row = {"title": "Roadwork in Starr County", "agency_number": "601"}
        self.assertEqual(procurement.match_esbd_row(row),
                         ("starr", "title_keyword", "starr"))

    def test_starr_beats_rgv(self):
        row = {"title": "Starr County / Hidalgo Joint Project",
               "agency_number": "601"}
        scope, _, term = procurement.match_esbd_row(row)
        self.assertEqual(scope, "starr")

    def test_rgv_title_match(self):
        row = {"title": "Office Supplies for Hidalgo County",
               "agency_number": "601"}
        self.assertEqual(procurement.match_esbd_row(row),
                         ("rgv", "title_keyword", "hidalgo"))

    def test_rgv_agency_number_match(self):
        row = {"title": "Generic Janitorial Services",
               "agency_number": "C1080"}
        self.assertEqual(procurement.match_esbd_row(row),
                         ("rgv", "agency_number", "C1080"))

    def test_no_match(self):
        row = {"title": "Lawn Care in Dallas", "agency_number": "601"}
        self.assertIsNone(procurement.match_esbd_row(row))

    def test_mission_inside_transmission_is_not_a_match(self):
        # Regression: "mission" must match as a whole word only.
        row = {"title": "Request for Proposals for Transmission to "
                        "Information Returns Intake System (IRIS) Services",
               "agency_number": "327"}
        self.assertIsNone(procurement.match_esbd_row(row))

    def test_mission_as_place_name_matches(self):
        row = {"title": "Mission, TX Road Resurfacing",
               "agency_number": "601"}
        self.assertEqual(procurement.match_esbd_row(row),
                         ("rgv", "title_keyword", "mission"))

    def test_case_insensitive(self):
        row = {"title": "ROMA ISD Roofing", "agency_number": "601"}
        scope, _, _ = procurement.match_esbd_row(row)
        self.assertEqual(scope, "starr")


class TestEsbdFetch(unittest.TestCase):
    def test_fetch_scans_pages_and_filters(self):
        seen = []
        opener = make_opener([
            ("?page=2", ESBD_PAGE2_HTML.encode()),
            ("txsmartbuy.gov/esbd", ESBD_PAGE_HTML.encode()),
        ], seen)
        obs, leg = procurement.fetch_esbd(page_count=2, opener=opener)
        self.assertEqual(leg["total_pages"], 2531)
        self.assertEqual(leg["pages_scanned"], 2)
        self.assertEqual(leg["rows_scanned"], 4)
        self.assertEqual(leg["status"], "OK")
        self.assertEqual(len(obs), 3)  # Starr + Hidalgo + UTRGV rows
        self.assertEqual({o["scope"] for o in obs}, {"starr", "rgv"})
        starr = [o for o in obs if o["scope"] == "starr"][0]
        self.assertEqual(starr["label"], "VERIFIED")
        self.assertEqual(starr["solicitation_id"], "6512-28-001_1126")
        self.assertTrue(starr["source_url"].endswith(
            "/esbd/6512-28-001_1126"))
        hidalgo = [o for o in obs
                   if o["solicitation_id"] == "ABC123"][0]
        # Missing due date -> REPORTED, never zero-filled.
        self.assertEqual(hidalgo["label"], "REPORTED")
        self.assertIsNone(hidalgo["due_date"])
        self.assertIn("?page=2", " ".join(seen))

    def test_fetch_error_recorded_not_raised(self):
        def boom(req, timeout=60):
            raise ConnectionError("no network")
        obs, leg = procurement.fetch_esbd(page_count=2, opener=boom)
        self.assertEqual(obs, [])
        self.assertTrue(leg["status"].startswith("ERROR:"))
        self.assertEqual(leg["pages_scanned"], 0)


class TestDirObservations(unittest.TestCase):
    def test_active_contract_verified_and_contacts_dropped(self):
        obs = procurement.build_dir_contract_observation(
            DIR_CONTRACT_ROW, "https://example.invalid/d",
            "2026-11-26T00:00:00Z")
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(obs["contract_number"], "DIR-CPO-6269")
        self.assertEqual(obs["vendor_name"], "AT&T Enterprises, LLC")
        self.assertEqual(obs["contract_start"], "2026-10-30T00:00:00.000")
        blob = json.dumps(obs)
        self.assertNotIn("sc5467@att.com", blob)
        self.assertNotIn("cheryl.dukes@dir.texas.gov", blob)
        self.assertNotIn("555-0100", blob)
        self.assertNotIn("Sonia Cardenas", blob)

    def test_active_contract_missing_number_is_reported(self):
        row = dict(DIR_CONTRACT_ROW, contract_number="")
        obs = procurement.build_dir_contract_observation(
            row, "https://example.invalid/d", "2026-11-26T00:00:00Z")
        self.assertEqual(obs["label"], "REPORTED")
        self.assertIsNone(obs["contract_number"])

    def test_sale_row_verified_amount_float_contacts_dropped(self):
        obs = procurement.build_dir_sale_observation(
            DIR_SALE_ROW, "https://example.invalid/d",
            "2026-11-26T00:00:00Z")
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(obs["purchase_amount"], 200.38)
        self.assertEqual(obs["customer_name"], "Starr County")
        self.assertEqual(obs["scope"], "starr")
        blob = json.dumps(obs)
        self.assertNotIn("Jane Doe", blob)

    def test_sale_row_bad_amount_is_reported_not_zero(self):
        row = dict(DIR_SALE_ROW, purchase_amount="n/a")
        obs = procurement.build_dir_sale_observation(
            row, "https://example.invalid/d", "2026-11-26T00:00:00Z")
        self.assertEqual(obs["label"], "REPORTED")
        self.assertIsNone(obs["purchase_amount"])


class TestTxdotLeg(unittest.TestCase):
    def test_dedupe_line_items_to_one_project(self):
        projects = procurement._dedupe_txdot_projects(
            [TXDOT_ROW_A, TXDOT_ROW_B])
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["_bid_item_rows"], 2)
        # Largest engineer estimate kept.
        self.assertEqual(
            projects[0]["sealed_engineer_s_estimate"], "6000000.00")

    def test_project_observation_verified(self):
        projects = procurement._dedupe_txdot_projects([TXDOT_ROW_A])
        obs = procurement.build_txdot_project_observation(
            projects[0], "https://example.invalid/d",
            "2026-11-26T00:00:00Z")
        self.assertEqual(obs["label"], "VERIFIED")
        self.assertEqual(obs["project_id"], "1057-03-060")
        self.assertEqual(obs["county"], "Starr")
        self.assertEqual(obs["engineer_estimate"], 5174096.72)
        self.assertEqual(obs["bid_item_rows"], 1)

    def test_zero_starr_lettings_is_ok_not_error(self):
        opener = make_opener([
            ("Pharr", jbytes(
                [{"count_distinct_controlling_project_id_ccsj": "3"}])),
            ("count%28distinct", jbytes(
                [{"count_distinct_controlling_project_id_ccsj": "198"}])),
            ("Starr", jbytes([])),
            ("Hidalgo", jbytes([{"count": "258"}])),
            ("Cameron", jbytes([{"count": "133"}])),
            ("Willacy", jbytes([{"count": "0"}])),
        ])
        obs, leg = procurement.fetch_txdot_lettings(opener=opener)
        self.assertEqual(obs, [])
        self.assertEqual(leg["status"], "OK")
        self.assertEqual(leg["starr_projects"], 0)
        self.assertEqual(leg["starr_bid_item_rows"], 0)
        self.assertEqual(leg["distinct_projects_statewide"], 198)
        self.assertEqual(leg["rgv_context"]["Hidalgo"], 258)
        self.assertEqual(leg["rgv_context"]["pharr_district_projects"], 3)

    def test_distinct_count_url_has_no_raw_spaces(self):
        seen = []
        opener = make_opener([
            ("qh8x-rm8r.json", jbytes(
                [{"count_distinct_controlling_project_id_ccsj": "198"}])),
        ], seen)
        self.assertEqual(
            procurement._socrata_count_distinct_projects(opener), 198)
        self.assertTrue(seen)
        self.assertNotIn(" ", seen[0])
        self.assertIn("count%28distinct%20controlling_project_id_ccsj%29",
                      seen[0])


class TestFetchObservationsEndToEnd(unittest.TestCase):
    def test_full_run_with_fake_openers(self):
        opener = make_opener([
            ("?page=2", ESBD_PAGE2_HTML.encode()),
            ("txsmartbuy.gov/esbd", ESBD_PAGE_HTML.encode()),
            ("vipt-h4ye.json?$select=count", jbytes([{"count": "5214"}])),
            ("vipt-h4ye.json?$limit=50", jbytes([DIR_CONTRACT_ROW])),
            ("a743-wj72.json?$select=count", jbytes([{"count": "287"}])),
            ("a743-wj72.json?$limit=1000", jbytes([DIR_SALE_ROW])),
            ("Pharr", jbytes(
                [{"count_distinct_controlling_project_id_ccsj": "3"}])),
            ("qh8x-rm8r.json?$select=count%28distinct",
             jbytes([{"count_distinct_controlling_project_id_ccsj": "198"}])),
            ("Starr", jbytes([])),
            ("Hidalgo", jbytes([{"count": "258"}])),
            ("Cameron", jbytes([{"count": "133"}])),
            ("Willacy", jbytes([{"count": "0"}])),
        ])
        result = procurement.fetch_observations(
            esbd_pages=2, dir_sample_limit=50, opener=opener)
        self.assertEqual(result["sensor"], "procurement-82")
        self.assertEqual(result["county_fips"], "48427")
        self.assertEqual(len(result["legs"]), 3)
        # 3 ESBD + 1 DIR contract + 1 DIR sale + 0 TxDOT = 5
        self.assertEqual(result["summary"]["observations_total"], 5)
        self.assertEqual(result["summary"]["starr_scope"], 2)
        dir_leg = [l for l in result["legs"] if l["leg"] == "dir"][0]
        self.assertEqual(dir_leg["active_contracts_total"], 5214)
        self.assertEqual(dir_leg["starr_sales_total"], 287)
        self.assertEqual(
            dir_leg["starr_sales_by_customer"]["Starr County"]["rows"], 1)
        self.assertEqual(
            dir_leg["starr_sales_by_customer"]["Starr County"]
            ["total_purchase_amount"], 200.38)
        for obs in result["observations"]:
            self.assertIn("source_url", obs)
            self.assertIn("retrieved_at", obs)
            self.assertIn(obs["label"],
                          ("VERIFIED", "REPORTED", "UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
