"""Tests for bfs.py (sensor #55) — offline fixtures, no network calls."""

import io
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET

import bfs


def make_county_xlsx(rows):
    """Build a minimal .xlsx (sharedStrings + one sheet) in memory.

    rows: list of lists of cell values (first row is the header).
    """
    strings = []
    index = {}

    def s_idx(value):
        if value not in index:
            index[value] = len(strings)
            strings.append(value)
        return index[value]

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ss_parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                f'<sst xmlns="{ns}" count="{len(rows) * 3}">']
    sheet_rows = []
    for r_i, row in enumerate(rows, start=1):
        cells = []
        for c_i, value in enumerate(row):
            col = chr(ord("A") + c_i) if c_i < 26 else f"A{chr(ord('A') + c_i - 26)}"
            if value is None:
                continue
            if isinstance(value, str):
                idx = s_idx(value)
                cells.append(f'<c r="{col}{r_i}" t="s"><v>{idx}</v></c>')
                ss_parts.append(f"<si><t>{value}</t></si>")
            else:
                cells.append(f'<c r="{col}{r_i}"><v>{value}</v></c>')
        sheet_rows.append(f"<row r=\"{r_i}\">" + "".join(cells) + "</row>")
    ss_parts.append("</sst>")
    # Rebuild sharedStrings with the true count after collecting strings.
    ss_parts[1] = (f'<sst xmlns="{ns}" count="{len(strings)}" '
                   f'uniqueCount="{len(strings)}">')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<worksheet xmlns="{ns}"><sheetData>'
             + "".join(sheet_rows) + "</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/sharedStrings.xml", "".join(ss_parts))
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


HEADER = ["State", "County", "County Code", "state_fips", "county_fips",
          "BA2005", "BA2019", "BA2024", "BA2025"]


class TestParseCountyXlsx(unittest.TestCase):
    def test_starr_row_parsed(self):
        data = make_county_xlsx([
            HEADER,
            ["TX", "Starr County", "48427", "48", "427",
             178, 253, 392, 466],
            ["TX", "Hidalgo County", "48215", "48", "215",
             1000, 2000, 3000, 4000],
        ])
        rows = bfs.parse_county_xlsx(data)
        self.assertEqual(len(rows), 2)
        starr = [r for r in rows if r["County Code"] == "48427"][0]
        self.assertEqual(starr["County"], "Starr County")
        self.assertEqual(starr["BA2025"], "466")
        self.assertEqual(starr["BA2005"], "178")

    def test_blank_county_code_row_skipped(self):
        data = make_county_xlsx([
            HEADER,
            ["TX", "Starr County", "48427", "48", "427",
             178, 253, 392, 466],
            ["TX", "Nowhere County", None, "48", None,
             1, 2, 3, 4],
        ])
        rows = bfs.parse_county_xlsx(data)
        self.assertEqual(len(rows), 1)

    def test_title_rows_before_header_ignored(self):
        data = make_county_xlsx([
            ["County Level Business Applications", None, None],
            [None, None, None],
            HEADER,
            ["TX", "Starr County", "48427", "48", "427",
             178, 253, 392, 466],
        ])
        rows = bfs.parse_county_xlsx(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["County Code"], "48427")


class TestBuildCountyObservations(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"State": "TX", "County": "Starr County", "County Code": "48427",
             "BA2005": "178", "BA2019": "253", "BA2025": "466"},
            {"State": "TX", "County": "Hidalgo County",
             "County Code": "48215",
             "BA2005": "1000", "BA2019": "2000", "BA2025": "4000"},
        ]

    def test_starr_only_by_default(self):
        obs = bfs.build_county_observations(
            self.rows, "http://example.invalid/x.xlsx", "2026-11-26T00:00:00Z")
        self.assertEqual(len(obs), 3)
        self.assertTrue(all(o["county_fips"] == "48427" for o in obs))
        by_year = {o["year"]: o["business_applications"] for o in obs}
        self.assertEqual(by_year, {2005: 178, 2019: 253, 2025: 466})
        self.assertTrue(all(o["label"] == "VERIFIED" for o in obs))
        self.assertEqual(obs[0]["source_url"],
                         "http://example.invalid/x.xlsx")

    def test_rgv_secondary_with_flag(self):
        obs = bfs.build_county_observations(
            self.rows, "http://example.invalid/x.xlsx", "2026-11-26T00:00:00Z",
            include_rgv=True)
        self.assertEqual(len(obs), 6)
        scopes = {(o["county_fips"], o["scope"]) for o in obs}
        self.assertIn(("48215", "rgv"), scopes)

    def test_unparseable_value_is_reported_not_zero(self):
        rows = [{"State": "TX", "County": "Starr County",
                 "County Code": "48427", "BA2025": "n/a"}]
        obs = bfs.build_county_observations(
            rows, "http://example.invalid/x.xlsx", "2026-11-26T00:00:00Z")
        self.assertEqual(len(obs), 1)
        self.assertIsNone(obs[0]["business_applications"])
        self.assertEqual(obs[0]["label"], "REPORTED")


class TestStateWeekly(unittest.TestCase):
    CSV = ("Year,Week,State,BA_NSA,HBA_NSA,WBA_NSA,CBA_NSA\n"
           "2026,40,TX,1200,700,500,300\n"
           "2026,41,TX,1300,750,520,310\n"
           "2026,42,TX,1250,720,510,305\n"
           "2026,42,OK,400,200,150,100\n")

    def test_recent_weeks_only_and_tx_only(self):
        obs = bfs.build_state_weekly_observations(
            self.CSV, "http://example.invalid/s.csv", "2026-11-26T00:00:00Z",
            weeks=2)
        self.assertEqual(len(obs), 2)
        self.assertEqual([o["week"] for o in obs], [41, 42])
        self.assertTrue(all(o["state"] == "TX" for o in obs))
        self.assertEqual(obs[-1]["business_applications"], 1250)
        self.assertEqual(obs[-1]["high_propensity_applications"], 720)
        self.assertEqual(obs[-1]["scope"], "texas_state_context")
        self.assertIsNone(obs[-1]["county_fips"])

    def test_zero_weeks_skips_leg(self):
        obs = bfs.build_state_weekly_observations(
            self.CSV, "http://example.invalid/s.csv", "2026-11-26T00:00:00Z",
            weeks=0)
        self.assertEqual(obs, [])


class TestFetchDocumentShape(unittest.TestCase):
    def test_blocked_api_leg_recorded(self):
        doc = bfs.fetch_observations(
            state_weeks=0,
            opener=lambda url, timeout=None: (_ for _ in ()).throw(
                RuntimeError("no network in tests")))
        api_legs = [l for l in doc["legs"]
                    if l["leg"] == "bfs_api_monthly_county"]
        self.assertEqual(len(api_legs), 1)
        self.assertEqual(api_legs[0]["status"], "BLOCKED-needs-owner")
        self.assertIn("api.census.gov/data/key_signup.html",
                      api_legs[0]["owner_step"])
        self.assertEqual(doc["sensor"], "census-bfs-55")
        self.assertIn("differentially private", doc["disclosure_note"])

    def test_json_serializable(self):
        doc = bfs.fetch_observations(
            state_weeks=0,
            opener=lambda url, timeout=None: (_ for _ in ()).throw(
                RuntimeError("no network in tests")))
        json.dumps(doc)


if __name__ == "__main__":
    unittest.main()
