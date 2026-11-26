"""Tests for qcew_warn.py (sensor #51). Stdlib unittest only, no network.

Run:  python3 -m unittest discover -s tests -v
from builds/regional-capital/
"""

import io
import json
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import qcew_warn  # noqa: E402

QCEW_HEADER = (
    '"area_fips","own_code","industry_code","agglvl_code","size_code",'
    '"year","qtr","disclosure_code","qtrly_estabs","month1_emplvl",'
    '"month2_emplvl","month3_emplvl","total_qtrly_wages",'
    '"taxable_qtrly_wages","qtrly_contributions","avg_wkly_wage"\n'
)


def qcew_row(area="48427", own="0", ind="10", agglvl="70", year="2026",
             qtr="1", disc="", estabs="675", m1="15400", m2="15500",
             m3="15613", wages="161540063", avgwk="796"):
    return (f'"{area}","{own}","{ind}","{agglvl}","0","{year}","{qtr}",'
            f'"{disc}","{estabs}","{m1}","{m2}","{m3}","{wages}","0",'
            f'"0","{avgwk}"\n')


def make_warn_xlsx(rows):
    """Build a minimal WARN workbook in memory.

    rows: list of lists (first row is the header). String cells go
    through the shared-strings table; plain ints stay numeric.
    """
    strings: list[str] = []
    str_idx: dict[str, int] = {}

    def s_cell(value):
        if value not in str_idx:
            str_idx[value] = len(strings)
            strings.append(value)
        return str_idx[value]

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_rows = []
    for ri, row in enumerate(rows, start=1):
        cells = []
        for ci, val in enumerate(row):
            col = chr(ord("A") + ci)
            if val is None:
                continue
            if isinstance(val, str):
                cells.append(
                    f'<c r="{col}{ri}" t="s"><v>{s_cell(val)}</v></c>')
            else:
                cells.append(f'<c r="{col}{ri}"><v>{val}</v></c>')
        sheet_rows.append(f"<row r=\"{ri}\">" + "".join(cells) + "</row>")
    ss_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
              '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              f'count="{len(strings)}" uniqueCount="{len(strings)}">'
              + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    sheet_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 "<sheetData>" + "".join(sheet_rows) + "</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", ss_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


WARN_HEADER = ["NOTICE_DATE", "JOB_SITE_NAME", "COUNTY_NAME", "WDA_NAME",
               "TOTAL_LAYOFF_NUMBER", "LayOff_Date", "WFDD_RECEIVED_DATE",
               "CITY_NAME"]

WARN_ROW_STARR = [46107, "Rio Grande Foods LLC", "Starr",
                  "Lower Rio Grande Valley WDA", 42, 46112, 46107, "Roma"]
WARN_ROW_CAMERON = [46085, "First Brands Group, LLC", "Cameron",
                    "Cameron County WDA", 345, 46142, 46085, "Brownsville"]
WARN_ROW_DALLAS = [46349, "Dallas Widgets Inc", "Dallas",
                   "North Central Texas WDA", 100, 46417, 46350, "Dallas"]
WARN_ROW_MISSING_WORKERS = [46107, "Starr Parts Co", "Starr",
                            "Lower Rio Grande Valley WDA", None, 46112,
                            46107, "Rio Grande City"]


class TestExcelDates(unittest.TestCase):
    def test_serial_converts_to_iso(self):
        # 45658 = 2025-01-01; 46349 = 2026-11-23 (Excel epoch 1899-12-30).
        self.assertEqual(qcew_warn.excel_serial_to_iso(45658), "2025-01-01")
        self.assertEqual(qcew_warn.excel_serial_to_iso(46349), "2026-11-23")
        self.assertEqual(qcew_warn.excel_serial_to_iso("46107"),
                         "2026-03-26")

    def test_blank_and_bad_serials_are_none(self):
        self.assertIsNone(qcew_warn.excel_serial_to_iso(None))
        self.assertIsNone(qcew_warn.excel_serial_to_iso(""))
        self.assertIsNone(qcew_warn.excel_serial_to_iso("not-a-date"))
        self.assertIsNone(qcew_warn.excel_serial_to_iso(0))
        self.assertIsNone(qcew_warn.excel_serial_to_iso(-5))


class TestCandidateQuarters(unittest.TestCase):
    def test_lags_two_quarters_from_november(self):
        # 2026-11-26 is Q4: two quarters back is 2026Q2, probe is 2026Q3
        # (both 404 live — latest published is 2026Q1; the collector
        # walks down until a quarter returns data).
        cands = qcew_warn.candidate_quarters(date(2026, 11, 26))
        self.assertEqual(cands[0], (2026, 3))
        self.assertEqual(cands[1], (2026, 2))
        self.assertEqual(cands[2], (2026, 1))

    def test_year_rollover(self):
        cands = qcew_warn.candidate_quarters(date(2027, 2, 10))
        self.assertEqual(cands[0], (2026, 4))
        self.assertEqual(cands[1], (2026, 3))


class TestQcewObservations(unittest.TestCase):
    def _rows(self, text):
        import csv
        return list(csv.DictReader(io.StringIO(text)))

    def test_county_total_verified(self):
        text = QCEW_HEADER + qcew_row()
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "48427", 2026, 1,
            "https://example.invalid/48427.csv", "2026-11-26T00:00:00Z")
        total = [o for o in obs if o["kind"] == "area_total"]
        self.assertEqual(len(total), 1)
        o = total[0]
        self.assertEqual(o["label"], "VERIFIED")
        self.assertEqual(o["scope"], "starr")
        self.assertEqual(o["county_fips"], "48427")
        self.assertEqual(o["employment_month3"], 15613)
        self.assertEqual(o["avg_weekly_wage"], 796)
        self.assertEqual(o["establishments"], 675)
        self.assertEqual(o["total_quarterly_wages"], 161540063)
        self.assertEqual(o["period"], "2026Q1")

    def test_private_and_government_totals(self):
        text = (QCEW_HEADER + qcew_row() + qcew_row(own="5", agglvl="71")
                + qcew_row(own="1", agglvl="71", m3="911", avgwk="2795")
                + qcew_row(own="3", agglvl="71", m3="5054", avgwk="782"))
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "48427", 2026, 1,
            "https://example.invalid/x.csv", "2026-11-26T00:00:00Z")
        kinds = {o["kind"]: o for o in obs}
        self.assertEqual(kinds["private_total"]["employment_month3"], 15613)
        self.assertEqual(kinds["federal_total"]["avg_weekly_wage"], 2795)
        self.assertEqual(kinds["local_total"]["employment_month3"], 5054)
        self.assertNotIn("state_total", kinds)  # no own=2 row in fixture

    def test_missing_figures_are_reported_not_zero(self):
        text = QCEW_HEADER + qcew_row(m3="", avgwk="")
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "48427", 2026, 1,
            "https://example.invalid/x.csv", "2026-11-26T00:00:00Z")
        total = [o for o in obs if o["kind"] == "area_total"][0]
        self.assertEqual(total["label"], "REPORTED")
        self.assertIsNone(total["employment_month3"])
        self.assertIsNone(total["avg_weekly_wage"])

    def test_suppressed_total_is_reported(self):
        text = QCEW_HEADER + qcew_row(disc="N")
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "48427", 2026, 1,
            "https://example.invalid/x.csv", "2026-11-26T00:00:00Z")
        total = [o for o in obs if o["kind"] == "area_total"][0]
        self.assertEqual(total["label"], "REPORTED")
        self.assertTrue(total["disclosure_suppressed"])

    def test_suppressed_total_measures_are_null_not_placeholder_zero(self):
        # BLS publishes MSA ownership totals as placeholder 0s with
        # disclosure '-'. Withheld figures must come out null, never 0.
        text = (QCEW_HEADER + qcew_row()
                + qcew_row(own="5", agglvl="41", m3="0", avgwk="0",
                           estabs="0", wages="0", disc="-"))
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "C3258", 2025, 4,
            "https://example.invalid/msa.csv", "2026-11-26T00:00:00Z")
        priv = [o for o in obs if o["kind"] == "private_total"][0]
        self.assertEqual(priv["label"], "REPORTED")
        self.assertTrue(priv["disclosure_suppressed"])
        self.assertIsNone(priv["employment_month3"])
        self.assertIsNone(priv["avg_weekly_wage"])
        self.assertIsNone(priv["establishments"])
        self.assertIsNone(priv["total_quarterly_wages"])
        blob = json.dumps([priv])
        self.assertNotIn(": 0", blob)

    def test_top_sectors_ranked_and_suppressed_skipped(self):
        text = (QCEW_HEADER + qcew_row()
                + qcew_row(own="5", ind="72", agglvl="74", m3="1170",
                           avgwk="349", estabs="66")
                + qcew_row(own="5", ind="23", agglvl="74", m3="189",
                           avgwk="1604", estabs="35")
                + qcew_row(own="5", ind="62", agglvl="74", m3="5000",
                           avgwk="900", estabs="99", disc="N")
                + qcew_row(own="5", ind="44", agglvl="74", m3="800",
                           avgwk="600", estabs="120"))
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "48427", 2026, 1,
            "https://example.invalid/x.csv", "2026-11-26T00:00:00Z")
        secs = [o for o in obs if o["kind"] == "sector"]
        # Suppressed NAICS 62 (5,000 emp) must NOT appear; order is 72, 44, 23.
        self.assertEqual([s["industry_code"] for s in secs],
                         ["72", "44", "23"])
        self.assertEqual(secs[0]["industry_title"],
                         "Accommodation and food services")
        self.assertEqual(secs[0]["employment_month3"], 1170)
        self.assertEqual(secs[0]["label"], "VERIFIED")
        blob = json.dumps(obs)
        self.assertNotIn('"62"', blob)

    def test_msa_scope_has_no_county_fips(self):
        text = QCEW_HEADER + qcew_row(area="C3258")
        obs = qcew_warn.build_qcew_observations(
            self._rows(text), "C3258", 2026, 1,
            "https://example.invalid/msa.csv", "2026-11-26T00:00:00Z")
        total = [o for o in obs if o["kind"] == "area_total"][0]
        self.assertEqual(total["scope"], "msa")
        self.assertIsNone(total["county_fips"])
        self.assertEqual(total["area_name"],
                         "McAllen-Edinburg-Mission, TX")


class TestWarnParsing(unittest.TestCase):
    def test_parse_workbook_rows(self):
        data = make_warn_xlsx([WARN_HEADER, WARN_ROW_STARR,
                               WARN_ROW_CAMERON])
        rows, header = qcew_warn.parse_warn_xlsx(data)
        self.assertEqual(header, WARN_HEADER)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["JOB_SITE_NAME"], "Rio Grande Foods LLC")
        self.assertEqual(rows[0]["COUNTY_NAME"], "Starr")
        self.assertEqual(rows[1]["TOTAL_LAYOFF_NUMBER"], "345")

    def test_ragged_row_padded_not_failed(self):
        short = [46107, "Starr Parts Co", "Starr"]
        data = make_warn_xlsx([WARN_HEADER, short])
        rows, _ = qcew_warn.parse_warn_xlsx(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["JOB_SITE_NAME"], "Starr Parts Co")
        self.assertIsNone(rows[0].get("TOTAL_LAYOFF_NUMBER"))

    def test_blank_rows_skipped(self):
        data = make_warn_xlsx([WARN_HEADER, WARN_ROW_STARR,
                               [None] * 8, WARN_ROW_CAMERON])
        rows, _ = qcew_warn.parse_warn_xlsx(data)
        self.assertEqual(len(rows), 2)

    def test_empty_formatted_ghost_rows_skipped(self):
        # TWC's 2025 workbook carries hundreds of empty styled rows
        # (<c s="9"/> with no <v>). They are formatting ghosts, not
        # notices, and must not inflate the notice count.
        ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        strings = WARN_HEADER + ["Rio Grande Foods LLC", "Starr",
                                 "Lower Rio Grande Valley WDA", "Roma"]
        ss_xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  f'<sst xmlns="{ns}" count="{len(strings)}" '
                  f'uniqueCount="{len(strings)}">'
                  + "".join(f"<si><t>{s}</t></si>" for s in strings)
                  + "</sst>")
        hdr_cells = "".join(
            f'<c r="{chr(65 + i)}1" t="s"><v>{i}</v></c>'
            for i in range(8))
        data_cells = (
            '<c r="A2"><v>46107</v></c>'
            '<c r="B2" t="s"><v>8</v></c>'
            '<c r="C2" t="s"><v>9</v></c>'
            '<c r="D2" t="s"><v>10</v></c>'
            '<c r="E2"><v>42</v></c>'
            '<c r="F2"><v>46112</v></c>'
            '<c r="G2"><v>46107</v></c>'
            '<c r="H2" t="s"><v>11</v></c>')
        ghost = "".join(
            f'<row r="{r}">' + "".join(
                f'<c r="{chr(65 + i)}{r}" s="9"/>' for i in range(8)
            ) + "</row>" for r in (3, 4, 5))
        sheet_xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     f'<worksheet xmlns="{ns}"><sheetData>'
                     f"<row r=\"1\">{hdr_cells}</row>"
                     f"<row r=\"2\">{data_cells}</row>"
                     f"{ghost}</sheetData></worksheet>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/sharedStrings.xml", ss_xml)
            zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        rows, _ = qcew_warn.parse_warn_xlsx(buf.getvalue())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["JOB_SITE_NAME"], "Rio Grande Foods LLC")


class TestWarnObservations(unittest.TestCase):
    def _obs(self, row_dict):
        return qcew_warn.build_warn_observation(
            row_dict, "https://example.invalid/warn.xlsx",
            "2026-11-26T00:00:00Z")

    def _dict(self, row):
        return {h: v for h, v in zip(WARN_HEADER, row)}

    def test_starr_notice_verified(self):
        o = self._obs(self._dict(WARN_ROW_STARR))
        self.assertIsNotNone(o)
        self.assertEqual(o["label"], "VERIFIED")
        self.assertEqual(o["scope"], "starr")
        self.assertEqual(o["county_fips"], "48427")
        self.assertEqual(o["employer"], "Rio Grande Foods LLC")
        self.assertEqual(o["city"], "Roma")
        self.assertEqual(o["workers_affected"], 42)
        self.assertEqual(o["notice_date"], "2026-03-26")
        self.assertEqual(o["layoff_date"], "2026-03-31")

    def test_cameron_notice_is_rgv_scope(self):
        o = self._obs(self._dict(WARN_ROW_CAMERON))
        self.assertIsNotNone(o)
        self.assertEqual(o["scope"], "rgv")
        self.assertIsNone(o["county_fips"])
        self.assertEqual(o["workers_affected"], 345)

    def test_out_of_scope_county_dropped(self):
        self.assertIsNone(self._obs(self._dict(WARN_ROW_DALLAS)))

    def test_missing_workers_is_reported_not_zero(self):
        o = self._obs(self._dict(WARN_ROW_MISSING_WORKERS))
        self.assertIsNotNone(o)
        self.assertEqual(o["label"], "REPORTED")
        self.assertIsNone(o["workers_affected"])
        self.assertEqual(o["employer"], "Starr Parts Co")


class TestFetchObservationsOffline(unittest.TestCase):
    def test_full_run_with_fake_opener(self):
        qcew_text = (QCEW_HEADER + qcew_row()
                     + qcew_row(own="5", agglvl="71"))
        warn_bytes = make_warn_xlsx([WARN_HEADER, WARN_ROW_STARR,
                                     WARN_ROW_CAMERON, WARN_ROW_DALLAS])

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self._payload

        def opener(url, timeout=120):
            if "warn-act-listings" in url:
                return FakeResp(warn_bytes)
            if "warn-notice" in url:
                return FakeResp(b"<html>warn-act-listings-2026-twc.xlsx</html>")
            if "area/48427.csv" in url or "area/C3258.csv" in url:
                # Only 2026Q1 returns data; newer quarters 404.
                if "/2026/1/" in url:
                    return FakeResp(qcew_text.encode())
                raise urllib_error_404()
            raise AssertionError(f"unexpected url {url}")

        import urllib.error

        def urllib_error_404():
            return urllib.error.HTTPError(
                "https://example.invalid/x.csv", 404, "Not Found", {}, None)

        result = qcew_warn.fetch_observations(
            quarters=1, warn_years=[2026], opener=opener)
        self.assertEqual(result["summary"]["qcew_latest_period"], "2026Q1")
        self.assertEqual(result["summary"]["starr_latest"]
                         ["employment_month3"], 15613)
        self.assertEqual(result["summary"]["warn_rgv_notices"], 2)
        self.assertEqual(result["summary"]["warn_starr_notices"], 1)
        self.assertEqual(result["summary"]["warn_statewide_notices"], 3)
        self.assertEqual(result["summary"]["warn_by_county"]["STARR"], 1)
        self.assertEqual(result["summary"]["warn_by_county"]["CAMERON"], 1)
        self.assertEqual(result["legs"]["warn"]["page_status"], "OK")
        self.assertEqual(result["legs"]["qcew"]["status"], "OK")

    def test_qcew_404_probe_recorded_not_raised(self):
        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self._payload

        import urllib.error

        def opener(url, timeout=120):
            if "warn-act-listings" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            if "warn-notice" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        result = qcew_warn.fetch_observations(
            quarters=1, warn_years=[2026], opener=opener)
        self.assertEqual(result["legs"]["qcew"]["status"], "BLOCKED-no-data")
        self.assertEqual(result["legs"]["warn"]["status"], "BLOCKED-no-data")
        self.assertEqual(result["summary"]["observations_total"], 0)


if __name__ == "__main__":
    unittest.main()
