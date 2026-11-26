"""Tests for cbp.py (sensor #55, CBP leg) — offline fixtures, no network."""

import io
import json
import unittest
import zipfile

import cbp


HEADER = ("fipstate,fipscty,naics,emp_nf,emp,qp1_nf,qp1,ap_nf,ap,est,"
          "n<5,n5_9,n10_19,n20_49,n50_99,n100_249,n250_499,n500_999,"
          "n1000,n1000_1,n1000_2,n1000_3,n1000_4")

TOTAL_ROW = ('"48","427","------","G",8704,"G",58523,"G",234845,594,'
             '300,129,101,40,10,9,3,"N","N","N","N","N"')
SECTOR_ROW = ('"48","427","44----","G",1200,"G",8000,"G",32000,120,'
              '60,30,20,5,3,2,0,"N","N","N","N","N"')
INDUSTRY_ROW = ('"48","427","445110","H",150,"H",900,"H",3600,8,'
                '4,2,2,0,0,0,0,"N","N","N","N","N"')
HIDALGO_ROW = ('"48","215","------","G",99000,"G",700000,"G",2900000,5000,'
               '2000,1200,1000,400,200,100,50,"N","N","N","N","N"')
OTHER_STATE_ROW = ('"06","001","------","G",5000,"G",30000,"G",120000,300,'
                   '150,80,50,10,5,3,2,"N","N","N","N","N"')
EMPTY_EMP_ROW = ('"48","427","81----","","","","","","",25,'
                 '10,8,5,2,0,0,0,"N","N","N","N","N"')


def make_cbp_zip(csv_text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cbp23co.txt", csv_text)
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestNaicsLevel(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(cbp.naics_level("------"), "total")
        self.assertEqual(cbp.naics_level("44----"), "sector")
        self.assertEqual(cbp.naics_level("445---"), "subsector")
        self.assertEqual(cbp.naics_level("445110"), "industry")
        self.assertIsNone(cbp.naics_level(None))

    def test_zip_url(self):
        self.assertEqual(
            cbp.cbp_zip_url(2023),
            "https://www2.census.gov/programs-surveys/cbp/datasets/"
            "2023/cbp23co.zip")


class TestBuildObservation(unittest.TestCase):
    def test_total_row(self):
        import csv as csv_mod
        row = next(csv_mod.DictReader(io.StringIO(HEADER + "\n" + TOTAL_ROW)))
        obs = cbp.build_observation(row, "http://example.invalid/z.zip",
                                    "2026-11-26T00:00:00Z", "starr")
        self.assertEqual(obs["county_fips"], "48427")
        self.assertEqual(obs["naics_level"], "total")
        self.assertEqual(obs["employees"], 8704)
        self.assertEqual(obs["employees_noise_flag"], "G")
        self.assertEqual(obs["annual_payroll_usd_1000"], 234845)
        self.assertEqual(obs["establishments"], 594)
        self.assertEqual(obs["establishments_by_size"]["n<5"], 300)
        self.assertEqual(obs["label"], "VERIFIED")

    def test_empty_emp_is_reported_not_zero(self):
        import csv as csv_mod
        row = next(csv_mod.DictReader(
            io.StringIO(HEADER + "\n" + EMPTY_EMP_ROW)))
        obs = cbp.build_observation(row, "http://example.invalid/z.zip",
                                    "2026-11-26T00:00:00Z", "starr")
        self.assertIsNone(obs["employees"])
        self.assertEqual(obs["label"], "REPORTED")
        self.assertEqual(obs["establishments"], 25)


class TestFetch(unittest.TestCase):
    CSV = "\n".join([HEADER, TOTAL_ROW, SECTOR_ROW, INDUSTRY_ROW,
                     HIDALGO_ROW, OTHER_STATE_ROW, EMPTY_EMP_ROW])

    def test_starr_only_by_default(self):
        doc = cbp.fetch_observations(
            opener=lambda req, timeout=None: FakeResponse(
                make_cbp_zip(self.CSV)))
        self.assertEqual(doc["fetch_status"], "OK")
        self.assertEqual(doc["summary"]["rows_scanned"], 6)
        self.assertEqual(doc["summary"]["observations_total"], 4)
        self.assertEqual(doc["summary"]["starr_rows"], 4)
        self.assertEqual(doc["summary"]["by_label"]["VERIFIED"], 3)
        self.assertEqual(doc["summary"]["by_label"]["REPORTED"], 1)
        total = doc["summary"]["starr_total"]
        self.assertEqual(total["employees"], 8704)
        self.assertEqual(total["establishments"], 594)
        top = doc["summary"]["starr_top_sectors_by_employment"]
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["naics"], "44----")
        self.assertEqual(top[0]["employees"], 1200)
        self.assertEqual(top[1]["naics"], "81----")
        self.assertIsNone(top[1]["employees"])

    def test_rgv_secondary_with_flag(self):
        doc = cbp.fetch_observations(
            include_rgv=True,
            opener=lambda req, timeout=None: FakeResponse(
                make_cbp_zip(self.CSV)))
        self.assertEqual(doc["summary"]["observations_total"], 5)
        scopes = {(o["county_fips"], o["scope"])
                  for o in doc["observations"]}
        self.assertIn(("48215", "rgv"), scopes)

    def test_fetch_error_recorded(self):
        doc = cbp.fetch_observations(
            opener=lambda req, timeout=None: (_ for _ in ()).throw(
                RuntimeError("no network in tests")))
        self.assertTrue(doc["fetch_status"].startswith("ERROR"))
        self.assertEqual(doc["observations"], [])
        self.assertEqual(doc["sensor"], "census-cbp-55")
        json.dumps(doc)


if __name__ == "__main__":
    unittest.main()
