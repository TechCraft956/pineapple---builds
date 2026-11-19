"""Decision Engine test suite — stdlib only, no network.

Run from the build workspace root:
    python3 -m unittest discover -s tests -v

Covers the brief's Task 2 + Task 4 acceptance checks:
  quant dims/boundaries, doctrine penalties, context dedup, scanner
  write-safety (explicit allowlist: writes ONLY inside 00_INDEX /
  00_PROCESSED), outcomes append-only, the stale-context rule, the
  learned-weights flag, and the boundary guard (no contact with the
  production trading system or the other briefing system — see the guard
  test for the exact tokens it enforces).
"""
import ast
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WS / "_lib"))
sys.path.insert(0, str(WS))

import pineapple_quant as pq  # noqa: E402
import doctrine as doc  # noqa: E402
import decision_engine as de  # noqa: E402
import source_scanner as ss  # noqa: E402


# ---------------------------------------------------------------- quant
class TestQuant(unittest.TestCase):
    def test_dims_and_boundaries(self):
        # all dims maxed in the favourable direction -> 100
        s = pq.score(pq.QuantInput(roi=100, time=0, risk=0, difficulty=0, capital=0))
        self.assertEqual(s.overall, 100.0)
        # all dims worst -> 0
        s = pq.score(pq.QuantInput(roi=0, time=100, risk=100, difficulty=100, capital=100))
        self.assertEqual(s.overall, 0.0)
        # out-of-range inputs are clamped, never escape 0..100
        s = pq.score(pq.QuantInput(roi=250, time=-40, risk=500, difficulty=-5, capital=101))
        self.assertEqual(s.dims["roi"], 100.0)
        self.assertEqual(s.dims["time"], 0.0)
        self.assertEqual(s.dims["risk"], 100.0)
        self.assertTrue(0.0 <= s.overall <= 100.0)

    def test_lower_is_better_inversion(self):
        # identical roi, but high time/risk must score LOWER than low time/risk
        hi = pq.score(pq.QuantInput(roi=80, time=90, risk=90, difficulty=90, capital=90))
        lo = pq.score(pq.QuantInput(roi=80, time=10, risk=10, difficulty=10, capital=10))
        self.assertLess(hi.overall, lo.overall)

    def test_default_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(pq.DEFAULT_WEIGHTS.values()), 1.0, places=6)
        self.assertEqual(set(pq.DEFAULT_WEIGHTS), set(pq.DIMENSIONS))

    def test_from_opportunity_explicit_quant(self):
        opp = {"score": 10, "risk": "LOW", "fields": {"quant": {"roi": 90, "time": 10,
              "risk": 10, "difficulty": 10, "capital": 10}}}
        qi = pq.from_opportunity(opp)
        self.assertEqual(qi.roi, 90.0)
        self.assertEqual(qi.time, 10.0)

    def test_from_opportunity_risk_map(self):
        self.assertEqual(pq.from_opportunity({"score": 50, "risk": "HIGH"}).risk, 80)
        self.assertEqual(pq.from_opportunity({"score": 50, "risk": "UNKNOWN"}).risk, 55)
        # numeric roi_estimate buckets capital; non-numeric stays default 50
        self.assertEqual(pq.from_opportunity({"score": 50, "roi_estimate": 500}).capital, 20)
        self.assertEqual(pq.from_opportunity({"score": 50, "roi_estimate": None}).capital, 50)


# ---------------------------------------------------------------- doctrine
class TestDoctrine(unittest.TestCase):
    DOCTRINE = {"rules": [
        {"domain": "assets", "type": "min", "field": "roi_pct", "threshold": 30,
         "message": "ROI below floor"},
        {"domain": "all", "type": "max", "field": "risk", "threshold": 70,
         "message": "Risk above ceiling"},
        {"domain": "all", "type": "forbid_flag", "field": "blind_signal",
         "message": "Blind signal forbidden"},
        {"domain": "all", "type": "soft", "field": "conflicts_family",
         "message": "Family conflict"},
    ]}

    def test_clean_item_no_penalty(self):
        v = doc.check({"roi_pct": 80, "risk": 20, "capital": 30}, "assets", self.DOCTRINE)
        self.assertTrue(v.aligned)
        self.assertEqual(v.penalty, 0.0)

    def test_min_max_penalties_stack(self):
        v = doc.check({"roi_pct": 18, "risk": 90}, "assets", self.DOCTRINE)
        self.assertFalse(v.aligned)
        self.assertEqual(v.penalty, 24.0)  # 12 (min) + 12 (max)
        self.assertEqual(len(v.flags), 2)

    def test_forbid_flag_is_25(self):
        v = doc.check({"roi_pct": 80, "blind_signal": True}, "assets", self.DOCTRINE)
        self.assertEqual(v.penalty, 25.0)

    def test_soft_flag_is_18_and_domain_scoping(self):
        v = doc.check({"roi_pct": 80, "conflicts_family": True}, "assets", self.DOCTRINE)
        self.assertEqual(v.penalty, 18.0)
        # the assets-domain min rule does NOT fire for the trading domain
        v2 = doc.check({"roi_pct": 5}, "trading", self.DOCTRINE)
        self.assertEqual(v2.penalty, 0.0)
        self.assertEqual(v2.checked, 0)


# ---------------------------------------------------------------- harness
def _temp_workspace():
    """Copy the build code (not runtime outputs) into a temp dir and import
    decision_engine from there, so stateful tests never touch the real brief
    or outcomes log. Returns (tmpdir, engine_module, scanner_module)."""
    tmp = Path(tempfile.mkdtemp(prefix="de-test-"))
    for name in ("decision_engine.py", "context_intake.py", "source_scanner.py",
                 "pineapple_os.py"):
        shutil.copy(WS / name, tmp / name)
    shutil.copytree(WS / "_lib", tmp / "_lib")
    shutil.copytree(WS / "04_INTELLIGENCE", tmp / "04_INTELLIGENCE")
    shutil.copytree(WS / "06_DECISION", tmp / "06_DECISION")
    # runtime outputs must not leak into the temp copy: fresh log/brief only
    for stale in ((tmp / "06_DECISION" / "outcomes_log.jsonl"),
                  (tmp / "06_DECISION" / "learning_report.md"),
                  (tmp / "decision_brief.json")):
        if stale.exists():
            stale.unlink()
    (tmp / ".pineapple_root").touch()
    for d in ("00_INDEX", "00_INBOX", "00_PROCESSED"):
        (tmp / d).mkdir()
    sys.path.insert(0, str(tmp / "_lib"))
    sys.path.insert(0, str(tmp))

    # The engine resolves pineapple_os / _lib helpers through sys.modules and
    # sys.path; a previous temp copy's cached modules would point ROOT at a
    # deleted temp dir. Evict them so each temp workspace imports fresh.
    for _name in ("pineapple_os", "pineapple_quant", "doctrine",
                  "pineapple_context", "pineapple_intel",
                  "decision_engine_tmpcopy", "source_scanner_tmpcopy"):
        sys.modules.pop(_name, None)

    def _load(modname, path):
        spec = importlib.util.spec_from_file_location(modname + "_tmpcopy", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    engine = _load("decision_engine", tmp / "decision_engine.py")
    scanner = _load("source_scanner", tmp / "source_scanner.py")
    return tmp, engine, scanner


class TempWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.de, self.ss = _temp_workspace()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write_index(self, records, name="context_index.json"):
        (self.tmp / "00_INDEX" / name).write_text(json.dumps(records), encoding="utf-8")


# ---------------------------------------------------------------- context
class TestContextDedupAndStale(TempWorkspaceTest):
    def test_same_title_twice_is_once(self):
        rec = {"filename": "a.txt", "date_modified": "2026-11-17T00:00:00Z",
               "entities": {"opportunities": ["grant", "grant"], "risks": [], "deadlines": []}}
        rec2 = {"filename": "b.txt", "date_modified": "2026-11-17T00:00:00Z",
                "entities": {"opportunities": ["grant"], "risks": [], "deadlines": []}}
        self._write_index({"00_INBOX/a.txt": rec, "00_INBOX/b.txt": rec2})
        items = self.de.items_from_context()
        titles = [i["title"] for i in items]
        self.assertEqual(titles.count("Context: grant"), 1)

    def test_stale_context_decays_and_flags(self):
        now = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        old = (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec_old = {"filename": "old.txt", "date_modified": old,
                   "entities": {"opportunities": [], "risks": ["overdue"], "deadlines": []}}
        rec_new = {"filename": "new.txt", "date_modified": fresh,
                   "entities": {"opportunities": [], "risks": ["late fee"], "deadlines": []}}
        self._write_index({"00_INBOX/old.txt": rec_old, "00_INBOX/new.txt": rec_new})
        items = self.de.items_from_context(now=now)
        by_src = {i["source"]: i for i in items}
        self.assertEqual(by_src["old.txt"]["quant"], 45.0)  # 55 - 10 decay
        self.assertTrue(by_src["old.txt"]["stale"])
        self.assertEqual(by_src["old.txt"]["age_days"], 45)
        self.assertTrue(any("STALE" in f for f in by_src["old.txt"]["doctrine"]["flags"]))
        self.assertEqual(by_src["new.txt"]["quant"], 55.0)
        self.assertNotIn("stale", by_src["new.txt"])

    def test_stale_boundary_30_days_fresh_31_stale(self):
        now = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
        for days, expect_stale in ((30, False), (31, True)):
            dt = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec = {"filename": "x.txt", "date_modified": dt,
                   "entities": {"opportunities": [], "risks": ["overdue"], "deadlines": []}}
            self._write_index({"00_INBOX/x.txt": rec})
            item = self.de.items_from_context(now=now)[0]
            self.assertEqual(item.get("stale", False), expect_stale,
                             "age %d days" % days)

    def test_missing_date_is_not_stale(self):
        rec = {"filename": "nodate.txt",
               "entities": {"opportunities": [], "risks": ["overdue"], "deadlines": []}}
        self._write_index({"00_INBOX/nodate.txt": rec})
        item = self.de.items_from_context()[0]
        self.assertEqual(item["quant"], 55.0)
        self.assertNotIn("stale", item)


# ---------------------------------------------------------------- scanner
class TestScannerWriteSafety(TempWorkspaceTest):
    def test_write_outside_allowlist_raises(self):
        for bad in (self.tmp / "00_INBOX" / "evil.json",
                    self.tmp / "decision_brief.json",
                    Path("/tmp/outside-decision-engine.json")):
            with self.assertRaises(PermissionError, msg=str(bad)):
                self.ss._assert_safe_write(bad)

    def test_write_inside_allowlist_ok(self):
        for good in (self.tmp / "00_INDEX" / "x.json",
                     self.tmp / "00_PROCESSED" / "summaries" / "y.json"):
            self.ss._assert_safe_write(good)  # must not raise
            self.ss._save(good, {"ok": True})
            self.assertTrue(good.exists())

    def test_scan_leaves_sources_byte_identical(self):
        srcdir = self.tmp / "sample_sources" / "Downloads"
        srcdir.mkdir(parents=True)
        victim = srcdir / "note.txt"
        victim.write_text("SAMPLE scan source — a deal for sale at $85, grant opportunity.\n",
                          encoding="utf-8")
        before = hashlib.sha256(victim.read_bytes()).hexdigest()
        cfg = {"defaults": {"max_file_size_mb": 25, "max_files_per_scan": 400,
                            "excluded_folders": [], "allowed_file_types": [".txt"]},
               "sources": [{"name": "Downloads (sample)", "path": str(srcdir),
                            "enabled": True, "recursive": True}]}
        (self.tmp / "00_INDEX" / "source_config.json").write_text(json.dumps(cfg),
                                                                  encoding="utf-8")
        totals = self.ss.scan()
        self.assertEqual(totals["scanned"], 1)
        self.assertEqual(totals["new"], 1)
        self.assertEqual(hashlib.sha256(victim.read_bytes()).hexdigest(), before)
        # second scan: unchanged file is skipped, still identical
        totals2 = self.ss.scan()
        self.assertEqual(totals2["skipped_unchanged"], 1)
        self.assertEqual(hashlib.sha256(victim.read_bytes()).hexdigest(), before)


# ---------------------------------------------------------------- outcomes
class TestOutcomesAppendOnly(TempWorkspaceTest):
    def test_second_run_appends_without_rewriting_prior_lines(self):
        brief1 = self.de.build_brief(top_n=5)
        log = self.tmp / "06_DECISION" / "outcomes_log.jsonl"
        lines1 = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines1), 5)
        self.assertTrue(all(json.loads(ln)["actual_roi"] is None for ln in lines1))
        brief2 = self.de.build_brief(top_n=5)
        lines2 = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines2), 10)
        self.assertEqual(lines2[:5], lines1)  # prior lines byte-identical
        self.assertEqual(brief1["total_considered"], brief2["total_considered"])
        # every logged row keeps the contract fields
        for ln in lines2:
            row = json.loads(ln)
            for k in ("id", "date", "title", "category", "predicted_quant",
                      "dims", "action", "status", "actual_roi", "notes"):
                self.assertIn(k, row)
            self.assertEqual(row["status"], "recommended")


# ---------------------------------------------------------------- weights
class TestLearnedWeightsFlag(TempWorkspaceTest):
    def test_weights_file_changes_scoring_and_flag_disables_it(self):
        # extreme weights: roi only. A high-roi / high-friction item then scores ~roi.
        (self.tmp / "00_INDEX" / "quant_weights.json").write_text(
            json.dumps({"weights": {"roi": 1.0, "time": 0.0, "risk": 0.0,
                                    "difficulty": 0.0, "capital": 0.0}}), encoding="utf-8")
        # load a FRESH copy of pineapple_quant from the temp workspace so its
        # weights file resolves to the temp 00_INDEX, not the real one
        spec = importlib.util.spec_from_file_location(
            "pineapple_quant_tmpcopy", self.tmp / "_lib" / "pineapple_quant.py")
        pq_tmp = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = pq_tmp  # dataclasses needs the module registered
        spec.loader.exec_module(pq_tmp)
        qi = pq_tmp.QuantInput(roi=90, time=90, risk=90, difficulty=90, capital=90)
        scored_learned = pq_tmp.score(qi)  # reads the temp weights file
        scored_default = pq_tmp.score(qi, weights=dict(pq_tmp.DEFAULT_WEIGHTS))
        self.assertAlmostEqual(scored_learned.overall, 90.0, places=0)
        self.assertLess(scored_default.overall, 60.0)
        # and the flag threads through build_brief without crashing
        b_on = self.de.build_brief(top_n=3, use_learned_weights=True)
        b_off = self.de.build_brief(top_n=3, use_learned_weights=False)
        self.assertEqual(b_on["total_considered"], b_off["total_considered"])


# ---------------------------------------------------------------- boundary
FORBIDDEN_PHRASES = ("life briefing", "pineapple next")
FORBIDDEN_IMPORT_RE = re.compile(r"^(pineapple_)?next$|^life_briefing$|_next$|^next_")


class TestBoundaryGuard(unittest.TestCase):
    """No import of, and no reference to, the production trading system or
    the other briefing system anywhere in this build — except the scope
    comment at the top of decision_engine.py and this guard test itself."""

    def test_no_forbidden_references_in_build_files(self):
        allowed = {WS / "decision_engine.py", Path(__file__).resolve()}
        offenders = []
        for p in WS.rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".md", ".json", ".txt", ".sh"):
                continue
            if p in allowed or "__pycache__" in p.parts:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for phrase in FORBIDDEN_PHRASES:
                if phrase in text:
                    offenders.append("%s contains %r" % (p.relative_to(WS), phrase))
        self.assertEqual(offenders, [])

    def test_no_forbidden_imports(self):
        bad = []
        for p in WS.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    leaf = n.split(".")[-1]
                    if FORBIDDEN_IMPORT_RE.match(leaf):
                        bad.append("%s imports %s" % (p.relative_to(WS), n))
        self.assertEqual(bad, [])

    def test_no_forbidden_modules_loaded_at_runtime(self):
        import decision_engine  # noqa: F401  (already imported at module top)
        loaded = [m for m in sys.modules
                  if FORBIDDEN_IMPORT_RE.match(m.split(".")[-1])]
        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
