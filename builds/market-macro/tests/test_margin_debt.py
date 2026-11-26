"""Tests for margin_debt.py (sensor #103, Wave 5 deficit sweep).
Stdlib unittest only, no network (a synthetic XLSX is built in
memory; the live fetch is faked).

Run:  python3 -m unittest discover -s tests -v
from builds/market-macro/
"""

import io
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import margin_debt  # noqa: E402

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/sharedStrings.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""

SHARED_STRINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="6" uniqueCount="6">
<si><t>Year-Month</t></si>
<si><t>Debit Balances</t></si>
<si><t>Free Credit Cash</t></si>
<si><t>Free Credit Margin</t></si>
<si><t>2026-10</t></si>
<si><t>2026-09</t></si>
</sst>
"""

SHEET = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c></row>
<row r="2"><c r="A2" t="s"><v>4</v></c><c r="B2"><v>1448360</v></c><c r="C2"><v>210290</v></c><c r="D2"><v>212890</v></c></row>
<row r="3"><c r="A3" t="s"><v>5</v></c><c r="B3"><v>1480054</v></c><c r="C3"><v>215328</v></c><c r="D3"><v>218581</v></c></row>
<row r="4"><c r="A4"><v>1997-01</v></c><c r="B4"><v>103337</v></c><c r="C4"><v>68856</v></c></row>
<row r="5"><c r="A5"><v>2026-08</v></c><c r="B5"><v>not-a-number</v></c><c r="C5"><v>207641</v></c><c r="D5"><v>217499</v></c></row>
</sheetData>
</worksheet>
"""


def build_xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("xl/sharedStrings.xml", SHARED_STRINGS)
        zf.writestr("xl/worksheets/sheet1.xml", SHEET)
    return buf.getvalue()


class TestParse(unittest.TestCase):
    def test_rows(self):
        rows, status = margin_debt.parse_margin_xlsx(build_xlsx())
        self.assertEqual(status, "OK")
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["date"], "2026-10")
        self.assertEqual(rows[0]["debit_balances_m"], 1448360.0)
        self.assertEqual(rows[0]["free_credit_cash_m"], 210290.0)
        self.assertEqual(rows[0]["free_credit_margin_m"], 212890.0)
        self.assertEqual(rows[0]["label"], "VERIFIED")
        # Old row with no 4th column: margin is null, never zero-filled
        self.assertEqual(rows[2]["date"], "1997-01")
        self.assertEqual(rows[2]["free_credit_margin_m"], None)
        self.assertEqual(rows[2]["label"], "VERIFIED")
        # Unparseable debit: REPORTED, not dropped
        self.assertEqual(rows[3]["label"], "REPORTED")
        self.assertIsNone(rows[3]["debit_balances_m"])

    def test_bad_zip(self):
        rows, status = margin_debt.parse_margin_xlsx(b"not a zip")
        self.assertEqual(rows, [])
        self.assertTrue(status.startswith("ERROR_"))


class TestCollect(unittest.TestCase):
    @patch.object(margin_debt, "fetch_workbook",
                  return_value=(build_xlsx(), "OK"))
    def test_collect_recent_months(self, _mock):
        result = margin_debt.collect(months=2)
        self.assertEqual(result["sensor"], "103")
        self.assertEqual(result["summary"]["observations_total"], 2)
        self.assertEqual(result["summary"]["history_rows"], 4)
        # Workbook lists newest first; collect sorts ascending, so the
        # last 2 are the newest months (2026-09, 2026-10), both VERIFIED;
        # the REPORTED 2026-08 row sits just outside the window.
        self.assertEqual(result["summary"]["latest"]["date"], "2026-10")
        self.assertEqual(result["summary"]["verified"], 2)

    @patch.object(margin_debt, "fetch_workbook",
                  return_value=(None, "HTTP_403"))
    def test_fetch_failure(self, _mock):
        result = margin_debt.collect()
        self.assertEqual(result["summary"]["observations_total"], 0)
        self.assertEqual(result["fetch_status"], "HTTP_403")


if __name__ == "__main__":
    unittest.main()
