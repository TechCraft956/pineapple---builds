"""Tests for oflc.py (sensor #85). Stdlib unittest only, no network.

Run:  python3 -m unittest discover -s tests -v
from builds/regional-capital/

The synthetic .xlsx fixtures are built in-memory with stdlib zipfile
(sharedStrings + one worksheet), exactly the format the collector
parses — no binary fixture file is committed.
"""

import io
import json
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oflc  # noqa: E402

H2A_HEADER = [
    "CASE_NUMBER", "CASE_STATUS", "DECISION_DATE", "EMPLOYER_NAME",
    "EMPLOYER_CITY", "EMPLOYER_STATE", "WORKSITE_CITY", "WORKSITE_STATE",
    "WORKSITE_POSTAL_CODE", "JOB_TITLE", "SOC_CODE", "SOC_TITLE",
    "WAGE_RATE_OF_PAY_FROM", "WAGE_UNIT_OF_PAY",
    "TOTAL_WORKERS_H-2A_REQUESTED", "TOTAL_WORKERS_H-2A_CERTIFIED",
    "PERIOD_OF_EMPLOYMENT_START", "PERIOD_OF_EMPLOYMENT_END",
]

ROW_STARR = ["H-300-26001-000001", "Determination Issued - Certification",
             "2026-07-15", "Rio Grande Citrus LLC", "RIO GRANDE CITY", "TX",
             "RIO GRANDE CITY", "TX", "78582",
             "Farmworkers and Laborers, Crop", "45-2092.00",
             "Farmworkers and Laborers, Crop, Nursery, and Greenhouse",
             15.79, "Hour", 12, 12, "2026-08-01", "2026-11-30"]

ROW_ROMA = ["H-300-26001-000002", "Determination Issued - Certification",
            "2026-07-20", "Roma Harvesting Inc", "ROMA", "TX",
            "ROMA", "TX", "78584", "Farmworker", "45-2092.00",
            "Farmworkers and Laborers, Crop, Nursery, and Greenhouse",
            11.81, "Hour", 5, 4, "2026-08-15", "2026-12-15"]

ROW_MCAllen = ["H-300-26001-000003", "Determination Issued - Certification",
               "2026-08-02", "Valley Produce Co", "MCALLEN", "TX",
               "MCALLEN", "TX", "78501", "Farmworkers and Laborers, Crop",
               "45-2092.00",
               "Farmworkers and Laborers, Crop, Nursery, and Greenhouse",
               12.50, "Hour", 20, 18, "2026-09-01", "2026-12-31"]

ROW_FLORIDA = ["H-300-26001-000004", "Determination Issued - Certification",
               "2026-07-10", "Orlando Groves LLC", "ORLANDO", "FL",
               "ORLANDO", "FL", "32801", "Farmworkers and Laborers, Crop",
               "45-2092.00",
               "Farmworkers and Laborers, Crop, Nursery, and Greenhouse",
               14.00, "Hour", 8, 8, "2026-08-01", "2026-11-01"]

ROW_MISSING_STATUS = ["H-300-26001-000005", None, "2026-07-22",
                      "Starr Onion Farms", "RIO GRANDE CITY", "TX",
                      "RIO GRANDE CITY", "TX", "78582", "Farmworker",
                      "45-2092.00",
                      "Farmworkers and Laborers, Crop, Nursery, and Greenhouse",
                      13.10, "Hour", 3, None, "2026-08-01", "2026-10-31"]

ADDENDUM_B_HEADER = [
    "CASE_NUMBER", "NAME_OF_AGRICULTURAL_BUSINESS",
    "PLACE_OF_EMPLOYMENT_CITY", "PLACE_OF_EMPLOYMENT_STATE",
    "PLACE_OF_EMPLOYMENT_COUNTY", "PLACE_OF_EMPLOYMENT_POSTAL_CODE",
    "TOTAL_WORKERS",
]

ROW_ADDENDUM_STARR = ["H-300-26001-000001", "Rio Grande Citrus LLC",
                      "RIO GRANDE CITY", "TX", "STARR", "78582", 12]
ROW_ADDENDUM_HIDALGO = ["H-300-26001-000003", "Valley Produce Co",
                        "MCALLEN", "TX", "HIDALGO", "78501", 20]

MIRROR_PAYLOAD = {
    "_source": {"generated_at": "2026-11-26T19:41:01Z"},
    "count": 3,
    "items": [
        {"case_number": "H-300-26044-638565", "program": "H-2A",
         "case_status": "Determination Issued - Certification",
         "decision_date": "2026-03-31", "employer_name": "Scott Etheredge",
         "employer_city": "Unknown", "employer_state": "TX",
         "job_title": "Agricultural Equipment Operators",
         "soc_code": "45-2091.00", "soc_title": "Agricultural Equipment Operators",
         "total_workers": 2, "worksite_state": "TX",
         "wage_offer_from": 15.79, "wage_unit": "Hour",
         "canonical_url": "https://api.morvs.ai/visa-labor/H-300-26044-638565"},
        {"case_number": "H-300-26001-000001", "program": "H-2A",
         "case_status": "Determination Issued - Certification",
         "decision_date": "2026-03-31", "employer_name": "Rio Grande Citrus LLC",
         "employer_city": "RIO GRANDE CITY", "employer_state": "TX",
         "job_title": "Farmworkers and Laborers, Crop",
         "soc_code": "45-2092.00", "soc_title": "Farmworkers and Laborers, Crop",
         "total_workers": 12, "worksite_state": "TX",
         "wage_offer_from": 15.79, "wage_unit": "Hour",
         "canonical_url": "https://api.morvs.ai/visa-labor/H-300-26001-000001"},
        {"case_number": "H-300-26001-000099", "program": "H-2A",
         "case_status": "Determination Issued - Certification",
         "decision_date": "2026-03-30", "employer_name": "Orlando Groves LLC",
         "employer_city": "ORLANDO", "employer_state": "FL",
         "job_title": "Farmworker", "soc_code": "45-2092.00",
         "soc_title": "Farmworkers and Laborers, Crop",
         "total_workers": 8, "worksite_state": "FL",
         "wage_offer_from": 14.00, "wage_unit": "Hour",
         "canonical_url": "https://api.morvs.ai/visa-labor/H-300-26001-000099"},
    ],
}


def make_xlsx(rows):
    """Build a minimal .xlsx (bytes) from a list of value rows.

    Strings go through sharedStrings; numbers are numeric cells;
    None leaves the cell out entirely.
    """
    strings: list[str] = []
    index: dict[str, int] = {}

    def col_letter(idx):
        out = ""
        idx += 1
        while idx:
            idx, rem = divmod(idx - 1, 26)
            out = chr(ord("A") + rem) + out
        return out

    sheet_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value is None:
                continue
            ref = f"{col_letter(c)}{r}"
            if isinstance(value, str):
                if value not in index:
                    index[value] = len(strings)
                    strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{index[value]}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        sheet_rows.append(f"<row r=\"{r}\">{''.join(cells)}</row>")
    shared = "".join(f"<si><t>{_xml_escape(s)}</t></si>" for s in strings)
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
            'worksheet+xml"/></Types>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            '2006/main"><sheets><sheet name="Sheet1" sheetId="1" '
            'r:id="rId1"/></sheets></workbook>'),
        "xl/sharedStrings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{len(strings)}" uniqueCount="{len(strings)}">{shared}</sst>'),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            '2006/main"><sheetData>' + "".join(sheet_rows) +
            "</sheetData></worksheet>"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _xml_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


class TestScopeMatching(unittest.TestCase):
    def test_county_starr_wins(self):
        scope, fb = oflc.match_scope(
            {"worksite_county": "STARR", "worksite_state": "TX"})
        self.assertEqual(scope, "starr")
        self.assertFalse(fb)

    def test_county_rgv(self):
        for county in ("HIDALGO", "CAMERON", "WILLACY"):
            scope, _ = oflc.match_scope(
                {"worksite_county": county, "worksite_state": "TX"})
            self.assertEqual(scope, "rgv")

    def test_city_match_when_no_county(self):
        scope, fb = oflc.match_scope(
            {"worksite_city": "ROMA", "worksite_state": "TX"})
        self.assertEqual(scope, "starr")
        self.assertFalse(fb)
        scope, _ = oflc.match_scope(
            {"worksite_city": "MCALLEN", "worksite_state": "TX"})
        self.assertEqual(scope, "rgv")

    def test_other_texas_city_is_tx_scope(self):
        scope, _ = oflc.match_scope(
            {"worksite_city": "LUBBOCK", "worksite_state": "TX"})
        self.assertEqual(scope, "tx")

    def test_non_texas_filtered(self):
        scope, _ = oflc.match_scope(
            {"worksite_city": "ORLANDO", "worksite_state": "FL"})
        self.assertIsNone(scope)

    def test_city_fallback_when_state_blank(self):
        scope, fb = oflc.match_scope(
            {"worksite_city": "ROMA", "worksite_state": ""})
        self.assertEqual(scope, "starr")
        self.assertTrue(fb)

    def test_city_fallback_rejected_for_unknown_city(self):
        scope, _ = oflc.match_scope(
            {"worksite_city": "LUBBOCK", "worksite_state": ""})
        self.assertIsNone(scope)


class TestXlsxParsing(unittest.TestCase):
    def _parse(self, header, *rows, program="H-2A"):
        data = make_xlsx([header, *rows])
        obs, scanned, headers = oflc.parse_xlsx_bytes(
            data, program, "https://example.invalid/f.xlsx",
            "2026-11-26T00:00:00Z")
        return obs, scanned, headers

    def test_starr_row_verified(self):
        obs, scanned, _ = self._parse(H2A_HEADER, ROW_STARR)
        self.assertEqual(scanned, 1)
        self.assertEqual(len(obs), 1)
        o = obs[0]
        self.assertEqual(o["label"], "VERIFIED")
        self.assertEqual(o["scope"], "starr")
        self.assertEqual(o["county_fips"], "48427")
        self.assertEqual(o["case_number"], "H-300-26001-000001")
        self.assertEqual(o["employer_name"], "Rio Grande Citrus LLC")
        self.assertEqual(o["workers_certified"], 12)
        self.assertEqual(o["workers_requested"], 12)
        self.assertEqual(o["wage_from"], 15.79)
        self.assertEqual(o["wage_unit"], "Hour")
        self.assertEqual(o["decision_date"], "2026-07-15")
        self.assertEqual(o["leg"], "dol-official")

    def test_rgv_city_row_is_rgv_scope(self):
        obs, _, _ = self._parse(H2A_HEADER, ROW_MCAllen)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["scope"], "rgv")
        self.assertIsNone(obs[0]["county_fips"])

    def test_non_texas_rows_filtered(self):
        obs, scanned, _ = self._parse(H2A_HEADER, ROW_FLORIDA)
        self.assertEqual(scanned, 1)
        self.assertEqual(obs, [])

    def test_missing_status_is_reported_not_zero(self):
        obs, _, _ = self._parse(H2A_HEADER, ROW_MISSING_STATUS)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["label"], "REPORTED")
        self.assertIsNone(obs[0]["case_status"])
        self.assertIsNone(obs[0]["workers_certified"])
        self.assertEqual(obs[0]["workers_requested"], 3)

    def test_addendum_b_county_fields(self):
        obs, scanned, _ = self._parse(
            ADDENDUM_B_HEADER, ROW_ADDENDUM_STARR, ROW_ADDENDUM_HIDALGO,
            program="H-2A-ADDENDUM-B")
        self.assertEqual(scanned, 2)
        self.assertEqual(len(obs), 2)
        by_scope = {o["scope"]: o for o in obs}
        self.assertEqual(by_scope["starr"]["worksite_county"], "STARR")
        self.assertEqual(by_scope["starr"]["workers_requested"], 12)
        self.assertEqual(by_scope["rgv"]["worksite_county"], "HIDALGO")
        # Addendum B has no case status: REPORTED, never VERIFIED.
        self.assertEqual(by_scope["starr"]["label"], "REPORTED")
        self.assertIsNone(by_scope["starr"]["case_status"])

    def test_excel_serial_date(self):
        self.assertEqual(oflc._excel_serial_to_date(45841), "2025-07-03")
        self.assertIsNone(oflc._excel_serial_to_date("not-a-date"))
        self.assertIsNone(oflc._excel_serial_to_date(5))

    def test_empty_workbook(self):
        obs, scanned, headers = oflc.parse_xlsx_bytes(
            make_xlsx([]), "H-2A", "https://example.invalid/e.xlsx",
            "2026-11-26T00:00:00Z")
        self.assertEqual((obs, scanned, headers), ([], 0, []))


class TestUrlCandidates(unittest.TestCase):
    def test_subfolder_first_then_flat(self):
        urls = oflc.file_url_candidates(
            "H-2A_Disclosure_Data_FY2026_Q4.xlsx", 2026, "Q4")
        self.assertEqual(urls, [
            "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/FY26Q4/"
            "H-2A_Disclosure_Data_FY2026_Q4.xlsx",
            "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
            "H-2A_Disclosure_Data_FY2026_Q4.xlsx",
        ])

    def test_user_agent_is_latin1_safe(self):
        # Regression: an em dash in the User-Agent broke every live
        # request (urllib encodes headers as latin-1) while the fake
        # opener in tests never touched the header.
        req = urllib.request.Request(
            "https://example.invalid/x",
            headers={"User-Agent": oflc.USER_AGENT})
        req.get_header("User-agent").encode("latin-1")
        self.assertTrue(oflc.USER_AGENT.isascii())


class TestMirrorLeg(unittest.TestCase):
    def _mirror_opener(self, payload):
        body = json.dumps(payload).encode()

        def opener(req, timeout=60):
            return FakeResp(body)

        return opener

    def test_texas_rows_reported_florida_filtered(self):
        obs, report = oflc.fetch_mirror_observations(
            "H-2A", "2026-11-26T00:00:00Z",
            opener=self._mirror_opener(MIRROR_PAYLOAD))
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["rows_scanned"], 3)
        self.assertEqual(report["rows_matched"], 2)
        self.assertEqual(len(obs), 2)
        for o in obs:
            self.assertEqual(o["label"], "REPORTED")
            self.assertEqual(o["leg"], "morvs-mirror")
            self.assertEqual(o["scope"], "tx")
            self.assertIsNone(o["worksite_city"])
            self.assertIsNone(o["worksite_county"])
        self.assertEqual(obs[0]["employer_name"], "Scott Etheredge")
        self.assertEqual(obs[0]["workers_requested"], 2)
        self.assertIsNone(obs[0]["workers_certified"])

    def test_mirror_error_recorded_not_raised(self):
        def boom(req, timeout=60):
            raise ConnectionError("no network")

        obs, report = oflc.fetch_mirror_observations(
            "H-2A", "2026-11-26T00:00:00Z", opener=boom)
        self.assertEqual(obs, [])
        self.assertTrue(report["status"].startswith("ERROR: ConnectionError"))

    def test_top_employer_certified_stays_null_without_data(self):
        # Rows with no certified counts at all: the summary's per-employer
        # certified total must be null, not a zero-filled 0.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "H-2A_Disclosure_Data_FY2026_Q4.xlsx"
            path.write_bytes(make_xlsx(
                [H2A_HEADER, ROW_MISSING_STATUS]))
            result = oflc.fetch_observations(
                programs=("H-2A",), include_addendum_b=False,
                use_mirror=False, local_dir=tmp)
        top = result["summary"]["texas"]["top_employers"]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["name"], "Starr Onion Farms")
        self.assertIsNone(top[0]["workers_certified"])
        self.assertIsNone(
            result["summary"]["workers"]["workers_certified_total"])


class TestFetchObservations(unittest.TestCase):
    def _blocked_dol_opener(self):
        def opener(req, timeout=300):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "morvs.ai" in url:
                return FakeResp(json.dumps(MIRROR_PAYLOAD).encode())
            raise HTTPError(url, 403, "Forbidden", {}, None)

        return opener

    def test_dol_blocked_mirror_survives(self):
        result = oflc.fetch_observations(
            programs=("H-2A",), include_addendum_b=False,
            opener=self._blocked_dol_opener())
        self.assertEqual(result["sensor"], "oflc-85")
        s = result["summary"]
        self.assertEqual(s["official_legs_blocked"], 1)
        self.assertEqual(s["mirror_legs_ok"], 1)
        self.assertEqual(s["observations_total"], 2)
        self.assertEqual(s["texas_total"], 2)
        self.assertEqual(s["starr_county"], 0)
        self.assertEqual(s["by_leg"], {"dol-official": 0, "morvs-mirror": 2})
        self.assertTrue(result["files"][0]["status"].startswith("ERROR:"))
        self.assertIn("403", result["files"][0]["status"])
        self.assertEqual(
            len(result["files"][0]["attempted_urls"]), 2)

    def test_mirror_dedup_against_official(self):
        data = make_xlsx([H2A_HEADER, ROW_STARR])

        def opener(req, timeout=300):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "morvs.ai" in url:
                return FakeResp(json.dumps(MIRROR_PAYLOAD).encode())
            return FakeResp(data)

        result = oflc.fetch_observations(
            programs=("H-2A",), include_addendum_b=False,
            opener=opener)
        # Official Starr row + 1 mirror TX row; the mirror copy of the
        # Starr case number is deduplicated, not re-emitted.
        self.assertEqual(result["summary"]["observations_total"], 2)
        self.assertEqual(result["mirror_duplicates_skipped"], 1)
        self.assertEqual(result["summary"]["starr_county"], 1)

    def test_local_dir_parses_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "H-2A_Disclosure_Data_FY2026_Q4.xlsx"
            path.write_bytes(make_xlsx(
                [H2A_HEADER, ROW_STARR, ROW_ROMA, ROW_FLORIDA]))
            result = oflc.fetch_observations(
                programs=("H-2A",), include_addendum_b=False,
                use_mirror=False, local_dir=tmp)
        s = result["summary"]
        self.assertEqual(s["observations_total"], 2)
        self.assertEqual(s["starr_county"], 2)
        self.assertEqual(s["workers_starr"]["workers_certified_total"], 16)
        self.assertEqual(result["files"][0]["status"], "OK")
        self.assertTrue(
            result["files"][0]["url"].startswith("file://"))


if __name__ == "__main__":
    unittest.main()
