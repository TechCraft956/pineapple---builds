#!/usr/bin/env python3
"""Tests for the Patent Radar build (BUILD-20261117-001).

Covers the brief's acceptance checks plus GPT's review patches
(RESULT-BUILD-20261117-001-GPT): negative tests, provenance,
REVIEW_REQUIRED, status-computation boundaries, snapshot regression,
dry-run / atomic writes, and NO outbound call in any offline test
(everything here runs on fixtures; fetch_legacy/fetch_odp are never called).

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import patent_radar_live as live  # noqa: E402
import patent_radar as radar  # noqa: E402

TODAY = date(2026, 11, 17)
SAMPLE = ROOT / "data" / "sample_patents.json"
FIXTURE = HERE / "fixtures" / "patentsview_response.json"
REQUIRED_KEYS = live.REQUIRED_KEYS


def _run_module(env_extra=None, args=None):
    env = dict(os.environ)
    env.pop("PATENT_RADAR_DATA", None)
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, str(ROOT / "patent_radar.py")] + (args or ["--selftest"])
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))


class TestSampleFixture(unittest.TestCase):
    def test_loader_contract(self):
        blob = json.loads(SAMPLE.read_text())
        self.assertEqual(set(blob.keys()), {"_meta", "patents"})
        self.assertEqual(blob["_meta"]["data_status"], "sample")
        self.assertIn("SAMPLE", blob["_meta"]["note"])
        pats = blob["patents"]
        self.assertEqual(len(pats), 10)
        for p in pats:
            missing = REQUIRED_KEYS - set(p.keys())
            self.assertFalse(missing, "record %s missing %s" % (p.get("patent_number"), missing))
        self.assertEqual({p["status"] for p in pats}, {"expired", "expiring", "filing"})
        diffs = {p["manufacture_profile"].split(":")[0] for p in pats}
        self.assertEqual(diffs, {"trivial", "low", "medium", "high"})
        self.assertGreaterEqual(sum(1 for p in pats if p["printable_3d"]), 3)

    def test_selftest_exits_zero(self):
        r = _run_module()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SELFTEST OK", r.stdout)

    def test_snapshot_regression(self):
        """Sample output is stable: 10 ideas, known top-3 order/scores."""
        r = _run_module(args=["--json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        items = json.loads(r.stdout)
        self.assertEqual(len(items), 10)
        self.assertEqual(items[0]["patent_number"], "US-TEST-000001")
        self.assertEqual(items[0]["opportunity_score"], 100.0)
        self.assertEqual(items[1]["opportunity_score"], 100.0)
        self.assertEqual(items[2]["opportunity_score"], 100.0)
        self.assertTrue(all(i["data_status"] == "sample" for i in items))
        self.assertTrue(all(i["review_required"] for i in items))
        # decision-engine contract keys intact
        req = {"title", "category", "source", "action", "est_value",
               "risk", "location", "url", "confidence"}
        for it in items:
            self.assertTrue(req <= set(it.keys()))


class TestStatusComputation(unittest.TestCase):
    def test_expired_boundary(self):
        # filed 2006-11-16 -> expires 2026-11-16, one day before TODAY
        s, exp, unc = live.compute_status(date(2006, 11, 16), "utility", "US", TODAY)
        self.assertEqual((s, exp), ("expired", date(2026, 11, 16)))
        self.assertIsNone(unc)

    def test_expiring_within_24_months(self):
        # expires 2027-06-01, ~6.5 months out
        s, exp, unc = live.compute_status(date(2007, 6, 1), "utility", "US", TODAY)
        self.assertEqual((s, exp), ("expiring", date(2027, 6, 1)))

    def test_expiring_exact_24_month_boundary(self):
        # expires exactly 24 months after TODAY -> still "expiring"
        s, exp, unc = live.compute_status(date(2008, 11, 17), "utility", "US", TODAY)
        self.assertEqual(s, "expiring")

    def test_in_force_beyond_24_months(self):
        # expires 2028-12-01, ~24.5 months out -> in-force (excluded downstream)
        s, exp, unc = live.compute_status(date(2008, 12, 1), "utility", "US", TODAY)
        self.assertEqual(s, "in-force")

    def test_feb29_leap_handling(self):
        s, exp, unc = live.compute_status(date(2008, 2, 29), "utility", "US", TODAY)
        self.assertEqual(exp, date(2028, 2, 29))
        self.assertEqual(s, "expiring")

    def test_non_us_is_review_required_not_expired(self):
        s, exp, unc = live.compute_status(date(2000, 1, 1), "utility", "EP", TODAY)
        self.assertEqual(s, "filing")
        self.assertIsNone(exp)
        self.assertIn("non-US", unc)

    def test_design_patent_is_review_required(self):
        s, exp, unc = live.compute_status(date(2000, 1, 1), "design", "US", TODAY)
        self.assertEqual(s, "filing")
        self.assertIsNone(exp)

    def test_missing_filing_date_is_review_required(self):
        s, exp, unc = live.compute_status(None, "utility", "US", TODAY)
        self.assertEqual(s, "filing")
        self.assertIsNone(exp)
        self.assertIn("filing date", unc)


class TestNormalization(unittest.TestCase):
    def _raw(self, **kw):
        base = {"patent_number": "US-TEST-200001", "patent_title": "Widget",
                "patent_type": "utility", "jurisdiction": "US",
                "filing_date": "2005-01-15", "patent_date": "2007-03-03",
                "cpc_section_id": "A01"}
        base.update(kw)
        return base

    def test_expired_record_maps_to_contract(self):
        rec, err = live.normalize_record(self._raw(), TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["expiration_date"], "2025-01-15")
        self.assertTrue(REQUIRED_KEYS <= set(rec.keys()))
        self.assertTrue(rec["review_required"])
        self.assertEqual(rec["status_method"], live.STATUS_METHOD)

    def test_missing_patent_number_rejected(self):
        rec, err = live.normalize_record(self._raw(patent_number=""), TODAY)
        self.assertIsNone(rec)
        self.assertIn("missing patent_number", err)

    def test_missing_title_rejected(self):
        rec, err = live.normalize_record(self._raw(patent_title=""), TODAY)
        self.assertIsNone(rec)
        self.assertIn("missing patent_title", err)

    def test_invalid_filing_date_review_required(self):
        rec, err = live.normalize_record(self._raw(filing_date="not-a-date"), TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "filing")
        self.assertIn("filing date", rec["status_uncertainty"])

    def test_unknown_status_never_invented(self):
        # The adapter COMPUTES status; it never trusts a status field.
        rec, err = live.normalize_record(
            self._raw(status="bogus-status"), TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")  # computed, not carried

    def test_duplicate_ids_deduped(self):
        blob, counts = live.build_live_file(
            [self._raw(), self._raw()], {"cpc": ["A01"]}, TODAY, "t", "u")
        self.assertEqual(counts["included"], 1)
        self.assertEqual(counts["rejected"], 1)
        self.assertIn("duplicate", blob["_meta"]["rejected"][0]["reason"])

    def test_empty_dataset_refused_downstream(self):
        blob, counts = live.build_live_file([], {"cpc": ["A01"]}, TODAY, "t", "u")
        self.assertEqual(counts["included"], 0)
        self.assertEqual(blob["patents"], [])

    def test_provenance_present(self):
        blob, counts = live.build_live_file(
            [self._raw()], {"cpc": ["A01"]}, TODAY, "test-source", "http://x")
        meta = blob["_meta"]
        for k in ("source", "source_url", "retrieved_at_utc", "jurisdiction",
                  "status_method", "uncertainty", "adapter_version", "counts"):
            self.assertIn(k, meta)
        self.assertEqual(meta["data_status"], "live")
        self.assertEqual(blob["patents"][0]["provenance"]["source_url"], "http://x")


class TestAdapterCLI(unittest.TestCase):
    def test_fixture_end_to_end_offline(self):
        """No outbound call: fixture -> live file -> module ranks it live."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "live_patents.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "patent_radar_live.py"),
                 "--fixture", str(FIXTURE), "--today", "2026-11-17",
                 "--out", str(out)],
                capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            blob = json.loads(out.read_text())
            self.assertEqual(blob["_meta"]["data_status"], "live")
            self.assertEqual(len(blob["patents"]), 6)
            self.assertEqual(blob["_meta"]["counts"]["rejected"], 3)
            # module ranks the live file, every idea data_status "live"
            m = _run_module(
                env_extra={"PATENT_RADAR_DATA": str(out)}, args=["--selftest"])
            self.assertEqual(m.returncode, 0, m.stdout + m.stderr)
            self.assertIn("LIVE", m.stdout)
            j = _run_module(
                env_extra={"PATENT_RADAR_DATA": str(out)}, args=["--json"])
            items = json.loads(j.stdout)
            self.assertTrue(all(i["data_status"] == "live" for i in items))
            self.assertTrue(all(i["review_required"] for i in items))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "live_patents.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "patent_radar_live.py"),
                 "--fixture", str(FIXTURE), "--today", "2026-11-17",
                 "--dry-run", "--out", str(out)],
                capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(out.exists())

    def test_corrupt_fixture_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text("{not json")
            out = Path(td) / "live.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "patent_radar_live.py"),
                 "--fixture", str(bad), "--out", str(out)],
                capture_output=True, text=True, cwd=str(ROOT))
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(out.exists())
            self.assertIn("not valid JSON", r.stderr)

    def test_empty_fixture_refuses_empty_write(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty.json"
            empty.write_text(json.dumps({"patents": []}))
            out = Path(td) / "live.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "patent_radar_live.py"),
                 "--fixture", str(empty), "--out", str(out)],
                capture_output=True, text=True, cwd=str(ROOT))
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(out.exists())

    def test_atomic_write_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "live.json"
            live.atomic_write(out, {"patents": []})
            self.assertTrue(out.exists())
            self.assertEqual([p.name for p in Path(td).iterdir()], ["live.json"])

    def test_legacy_fetch_without_key_fails_with_migration_note(self):
        env = dict(os.environ)
        env.pop("PATENTSVIEW_API_KEY", None)
        r = subprocess.run(
            [sys.executable, str(ROOT / "patent_radar_live.py")],
            capture_output=True, text=True, cwd=str(ROOT), env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("RETIRED", r.stderr)
        self.assertIn("ODP", r.stderr)

    def test_offline_flag_refuses_network(self):
        # fetch_legacy honors PATENT_RADAR_OFFLINE=1 (no network attempted)
        os.environ["PATENT_RADAR_OFFLINE"] = "1"
        try:
            with self.assertRaises(RuntimeError) as cm:
                live.fetch_legacy(["A01B"], "2004-01-01", "2010-12-31", 5)
            self.assertIn("OFFLINE", str(cm.exception))
        finally:
            del os.environ["PATENT_RADAR_OFFLINE"]


ODP_FIXTURE = HERE / "fixtures" / "odp_search_response.json"


def _odp_wrapper(**md_over):
    md = {"patentNumber": "7654321", "inventionTitle": "GARDEN WIDGET",
          "filingDate": "2001-05-01", "grantDate": "2003-06-03",
          "applicationTypeLabelName": "Utility", "applicationTypeCode": "UTL",
          "applicationStatusDescriptionText": "Patented Case",
          "cpcClassificationBag": ["A01G   9/02"]}
    md.update(md_over)
    return {"applicationNumberText": "09876543", "applicationMetaData": md,
            "eventDataBag": []}


class TestOdpNormalization(unittest.TestCase):
    """ODP adapter (v1.1.0): recorded fixture + synthetic wrappers, no network."""

    def test_recorded_fixture_covers_three_kinds(self):
        raws = live.load_odp_fixture(ODP_FIXTURE)
        self.assertEqual(len(raws), 3)
        blob, counts = live.build_live_file(
            raws, {"source": "odp-fixture"}, TODAY, "odp-fixture", "http://x",
            normalizer=live.normalize_odp_record, key_fn=live._odp_key,
            meta_extra={"status_method": live.ODP_STATUS_METHOD})
        self.assertEqual(counts["included"], 3)
        by_num = {p["patent_number"]: p for p in blob["patents"]}
        lapsed = by_num["US11406065"]
        self.assertEqual(lapsed["status"], "expired")
        self.assertIsNotNone(lapsed["lapse_evidence"])
        # effective expiration is the lapse event date, not filing+20y (2040)
        self.assertTrue(lapsed["expiration_date"].startswith("2026-09"))
        self.assertEqual(lapsed["status_method"], live.ODP_STATUS_METHOD)
        self.assertIn("filing+20y provisional", lapsed["status_method"])
        self.assertEqual(by_num["US7665409"]["status"], "expiring")
        self.assertEqual(by_num["US6718891"]["status"], "expired")
        for p in blob["patents"]:
            self.assertTrue(REQUIRED_KEYS <= set(p.keys()))
            self.assertTrue(p["review_required"])

    def test_expired_by_term(self):
        rec, err = live.normalize_odp_record(_odp_wrapper(), TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["expiration_date"], "2021-05-01")
        self.assertEqual(rec["patent_number"], "US7654321")
        self.assertEqual(rec["domain"], "garden / horticulture")

    def test_lapse_status_overrides_future_term(self):
        w = _odp_wrapper(
            filingDate="2020-05-12",
            applicationStatusDescriptionText=(
                "Patent Expired Due to NonPayment of Maintenance Fees "
                "Under 37 CFR 1.362"))
        rec, err = live.normalize_odp_record(w, TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")
        self.assertIsNotNone(rec["lapse_evidence"])

    def test_lapse_event_dates_effective_expiration(self):
        w = _odp_wrapper(filingDate="2020-05-12")
        w["eventDataBag"] = [{"eventCode": "EXP.", "eventDate": "2025-08-25",
                              "eventDescriptionText": "Expire Patent"}]
        rec, err = live.normalize_odp_record(w, TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["expiration_date"], "2025-08-25")

    def test_in_force_rejected(self):
        rec, err = live.normalize_odp_record(
            _odp_wrapper(filingDate="2020-01-01"), TODAY)
        self.assertIsNone(rec)
        self.assertIn("in-force", err)

    def test_design_type_lands_in_filing_bucket(self):
        rec, err = live.normalize_odp_record(
            _odp_wrapper(applicationTypeLabelName="Design"), TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "filing")
        self.assertIn("not a US utility patent", rec["status_uncertainty"])

    def test_missing_patent_number_rejected(self):
        rec, err = live.normalize_odp_record(
            _odp_wrapper(patentNumber=""), TODAY)
        self.assertIsNone(rec)
        self.assertIn("missing patentNumber", err)

    def test_off_domain_title_screened(self):
        rec, err = live.normalize_odp_record(
            _odp_wrapper(inventionTitle="SURGICAL IRRIGATION DEVICE"), TODAY)
        self.assertIsNone(rec)
        self.assertIn("off-domain title screen", err)

    def test_odp_fixture_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "live_patents.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "patent_radar_live.py"),
                 "--odp-fixture", str(ODP_FIXTURE), "--today", "2026-11-17",
                 "--out", str(out)],
                capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            blob = json.loads(out.read_text())
            self.assertEqual(blob["_meta"]["data_status"], "live")
            self.assertEqual(len(blob["patents"]), 3)
            self.assertEqual(blob["_meta"]["status_method"],
                             live.ODP_STATUS_METHOD)
            j = _run_module(
                env_extra={"PATENT_RADAR_DATA": str(out)}, args=["--json"])
            items = json.loads(j.stdout)
            self.assertEqual(len(items), 3)
            self.assertTrue(all(i["data_status"] == "live" for i in items))

    def test_marketable_title_domains(self):
        # Marketable-smalls keywords label domains even when the CPC class
        # (e.g. F23Q lighters) has no CPC-domain mapping.
        w = _odp_wrapper(inventionTitle="CIGARETTE LIGHTER WITH ASHTRAY",
                         cpcClassificationBag=["F23Q   2/16"])
        rec, err = live.normalize_odp_record(w, TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["domain"], "smoking accessories")
        w2 = _odp_wrapper(inventionTitle="COMBINATION CORKSCREW AND OPENER",
                          cpcClassificationBag=["B67B   7/00"])
        rec2, err2 = live.normalize_odp_record(w2, TODAY)
        self.assertIsNone(err2)
        self.assertEqual(rec2["domain"], "bar / kitchen smalls")

    def test_query_plan_lapsed_first_for_marketable_keywords(self):
        plan = live.odp_query_plan(TODAY, ["lighter", "ashtray", "flask"], 3)
        labels = [s["label"] for s in plan]
        self.assertTrue(labels[0].startswith("lapsed:"))
        self.assertTrue(all(s["body"]["filters"][0]["value"] == ["UTL"]
                            for s in plan))

    def test_fetch_odp_zero_hit_query_is_not_fatal(self):
        # ODP returns HTTP 404 for a zero-hit search; the pull must treat
        # it as an empty result for that query and keep going.
        calls = {"n": 0}

        def fake_search(body):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError('ODP search HTTP 404: {"code":"404",'
                                   '"message":"Not Found"}')
            return {"count": 0, "patentFileWrapperDataBag": []}

        orig = live._odp_post_search
        live._odp_post_search = fake_search
        try:
            raw, log = live.fetch_odp(["lighter"], 1, TODAY, pause=0)
        finally:
            live._odp_post_search = orig
        self.assertEqual(raw, [])
        self.assertEqual(log[0].get("note"), "no matching records (HTTP 404)")
        self.assertEqual(len(log), 3)  # lapsed + expiring + expired-term

    def test_fetch_odp_offline_refused(self):
        os.environ["PATENT_RADAR_OFFLINE"] = "1"
        try:
            with self.assertRaises(RuntimeError) as cm:
                live.fetch_odp(["garden"], 1, TODAY)
            self.assertIn("OFFLINE", str(cm.exception))
        finally:
            del os.environ["PATENT_RADAR_OFFLINE"]


VINTAGE_FIXTURE = HERE / "fixtures" / "odp_vintage_response.json"


def _vintage_wrapper(**md_over):
    """Old-case shape as observed live 2026-11-17: no filingDate (the index
    carries none before 2001), no CPC bag, old-case status text."""
    md = {"patentNumber": "4080530",
          "inventionTitle": "EQUAPOISED LAMP AND NEW COUNTERBALANCED ARM ASSEMBLIES",
          "filingDate": None, "grantDate": "1978-03-21",
          "applicationTypeLabelName": "Utility", "applicationTypeCode": "UTL",
          "applicationStatusDescriptionText":
              "Patented File - (Old Case Added for File Tracking Purposes)",
          "cpcClassificationBag": []}
    md.update(md_over)
    return {"applicationNumberText": "05987654", "applicationMetaData": md,
            "eventDataBag": []}


class TestOdpVintage(unittest.TestCase):
    """Vintage profile (v1.2.0): golden-era grants are expired by term;
    expiration is a labeled term estimate, never a lapse claim."""

    def test_vintage_utility_grant_basis(self):
        rec, err = live.normalize_odp_vintage_record(_vintage_wrapper(), TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["patent_type"], "utility")
        # pre-1995 term ran 17 years from grant: 1978-03-21 + 17y
        self.assertEqual(rec["expiration_date"], "1995-03-21")
        self.assertTrue(rec["term_basis"].startswith("grant+17y"))
        self.assertEqual(rec["status_method"], live.VINTAGE_STATUS_METHOD)
        self.assertIn("term (vintage, pre-1990 filing)", rec["status_method"])
        self.assertIsNone(rec["filing_date"])
        self.assertTrue(rec["review_required"])

    def test_vintage_design_grant_basis(self):
        w = _vintage_wrapper(
            patentNumber="D251509", grantDate="1979-04-03",
            applicationTypeCode="DES", applicationTypeLabelName="Design",
            inventionTitle="DESIGN FOR TRIM STRIP ADAPTED TO BE SECURED "
                           "TO AN AUTOMOBILE BUMPER OR BODY")
        rec, err = live.normalize_odp_vintage_record(w, TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["patent_number"], "USD251509")
        self.assertEqual(rec["patent_type"], "design")
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["expiration_date"], "1993-04-03")  # grant + 14y
        self.assertTrue(rec["term_basis"].startswith("grant+14y"))

    def test_vintage_filing_basis_when_filing_on_record(self):
        w = _vintage_wrapper(patentNumber="7654322",
                             inventionTitle="PORTABLE ELECTRIC FAN",
                             filingDate="1980-03-04", grantDate="1982-01-05",
                             applicationStatusDescriptionText="Patented Case")
        rec, err = live.normalize_odp_vintage_record(w, TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "expired")
        self.assertEqual(rec["expiration_date"], "2000-03-04")  # filing + 20y
        self.assertTrue(rec["term_basis"].startswith("filing+20y"))

    def test_vintage_no_dates_is_review_bucket_not_expired(self):
        w = _vintage_wrapper(filingDate=None, grantDate=None)
        rec, err = live.normalize_odp_vintage_record(w, TODAY)
        self.assertIsNone(err)
        self.assertEqual(rec["status"], "filing")
        self.assertIsNone(rec["expiration_date"])
        self.assertTrue(rec["review_required"])

    def test_vintage_component_title_screened(self):
        w = _vintage_wrapper(inventionTitle="TELEVISION RECEIVER CIRCUIT")
        rec, err = live.normalize_odp_vintage_record(w, TODAY)
        self.assertIsNone(rec)
        self.assertIn("off-domain title screen", err)

    def test_vintage_category_screen(self):
        self.assertEqual(live.vintage_category("ELECTRIC CLOCK RADIO"),
                         "clocks & instruments")
        self.assertEqual(live.vintage_category("DESIGN FOR A TABLE LAMP"),
                         "lamps & lighting")
        self.assertIsNone(live.vintage_category("CATHODE-RAY TUBE"))
        self.assertIsNone(live.vintage_category("METHOD OF PRODUCING ZEOLITE"))
        self.assertIsNone(live.vintage_category("PAINT STRIPPING METHOD"))

    def test_vintage_category_word_boundaries(self):
        # Substring collisions observed in the first live sweep: "lamp"
        # inside CLAMP, "table" inside STABLE / TABLETS.
        self.assertIsNone(live.vintage_category("MOLDED GARMENT CLAMP"))
        self.assertIsNone(live.vintage_category(
            "HIGHLY-STABLE GRAFT COPOLYMER DISPERSIONS"))
        self.assertIsNone(live.vintage_category(
            "PHARMACEUTICAL TABLETS AND CAPSULES"))
        self.assertEqual(live.vintage_category(
            "EQUAPOISED LAMP AND COUNTERBALANCED ARM ASSEMBLIES"),
            "lamps & lighting")

    def test_fetch_odp_vintage_paginates_full_sweep(self):
        def fake_search(body):
            f = body["filters"][0]["value"]
            if f == ["DES"]:
                return {"count": 1, "patentFileWrapperDataBag":
                        [_vintage_wrapper(patentNumber="D251509",
                                          applicationTypeCode="DES")]}
            off = body["pagination"]["offset"]
            bag = [_vintage_wrapper(patentNumber=str(5000000 + off + i))
                   for i in range(min(50, 75 - off))]
            return {"count": 75, "patentFileWrapperDataBag": bag}

        orig = live._odp_post_search
        live._odp_post_search = fake_search
        try:
            raw, log = live.fetch_odp_vintage(pause=0, page=50)
        finally:
            live._odp_post_search = orig
        self.assertEqual(len(raw), 76)  # 1 design + 75 utility, deduped
        self.assertEqual(log[-1]["label"], "vintage:coverage")
        self.assertEqual(log[-1]["unique_collected"], 76)

    def test_vintage_fixture_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "live_patents_vintage.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "patent_radar_live.py"),
                 "--odp-fixture", str(VINTAGE_FIXTURE), "--profile", "vintage",
                 "--today", "2026-11-17", "--out", str(out)],
                capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            blob = json.loads(out.read_text())
            self.assertEqual(blob["_meta"]["status_method"],
                             live.VINTAGE_STATUS_METHOD)
            self.assertEqual(len(blob["patents"]), 3)
            by_num = {p["patent_number"]: p for p in blob["patents"]}
            self.assertEqual(by_num["US4080530"]["expiration_date"], "1995-03-21")
            self.assertEqual(by_num["USD251509"]["patent_type"], "design")
            self.assertEqual(by_num["US7654322"]["expiration_date"], "2000-03-04")
            for p in blob["patents"]:
                self.assertEqual(p["status"], "expired")
                self.assertTrue(REQUIRED_KEYS <= set(p.keys()))
                self.assertTrue(p["review_required"])
            j = _run_module(
                env_extra={"PATENT_RADAR_DATA": str(out)}, args=["--json"])
            items = json.loads(j.stdout)
            self.assertEqual(len(items), 3)
            self.assertTrue(all(i["data_status"] == "live" for i in items))


if __name__ == "__main__":
    unittest.main()
