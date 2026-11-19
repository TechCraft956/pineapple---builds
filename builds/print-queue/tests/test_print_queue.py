"""Offline tests for the 3D Print Business Queue builder. Stdlib only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_queue as bq  # noqa: E402

FIXED_TS = "2026-11-17T00:00:00Z"


def synthetic_raw(**overrides):
    raw = {
        "id": "PQ-TEST-001",
        "title": "Synthetic test item",
        "source_ref": "TEST",
        "legal_status": "test",
        "market_grade": "H",
        "market_evidence": "Synthetic evidence line, long enough to pass validation.",
        "ease_grade": "M",
        "make_route": "PRINT",
        "next_action": "MODEL",
        "assigned_filament_id": "fil-pla-white",
        "size_class": "small",
        "use_context": "indoor",
        "material_suitability": "good",
        "colour_match": True,
        "fit_context": "Synthetic fit context.",
        "est_filament_g": None,
    }
    raw.update(overrides)
    return raw


class ScoringTests(unittest.TestCase):
    def test_scoring_math_known_triples(self):
        self.assertEqual(bq.compute_score("H", "H", "H"), 27)
        self.assertEqual(bq.compute_score("H", "M", "H"), 18)
        self.assertEqual(bq.compute_score("H", "H", "L"), 9)
        self.assertEqual(bq.compute_score("M", "M", "M"), 8)
        self.assertEqual(bq.compute_score("L", "L", "L"), 1)
        self.assertEqual(bq.compute_score("H", "L", "M"), 6)

    def test_grade_points(self):
        self.assertEqual(bq.GRADE_POINTS, {"H": 3, "M": 2, "L": 1})


class FilamentFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.inventory = bq.load_inventory(ROOT / "inputs" / "filament_inventory.json")

    def fit(self, **overrides):
        raw = synthetic_raw(**overrides)
        return bq.compute_filament_fit(raw, self.inventory[raw["assigned_filament_id"]])

    def test_gold_silk_large_is_L(self):
        grade, _, _, flags = self.fit(assigned_filament_id="fil-gold-silk", size_class="large")
        self.assertEqual(grade, "L")
        self.assertIn("scarce_stock_large_item", flags)

    def test_gold_silk_small_caps_at_M(self):
        grade, _, _, flags = self.fit(assigned_filament_id="fil-gold-silk", size_class="small")
        self.assertEqual(grade, "M")
        self.assertIn("scarce_stock", flags)

    def test_pla_for_outdoor_is_L_and_flagged(self):
        grade, _, reasons, flags = self.fit(
            assigned_filament_id="fil-pla-black", use_context="outdoor")
        self.assertEqual(grade, "L")
        self.assertIn("pla_for_outdoor_poor_fit", flags)
        self.assertTrue(any("poor fit" in r for r in reasons))

    def test_petg_for_outdoor_not_flagged(self):
        grade, _, _, flags = self.fit(
            assigned_filament_id="fil-petg-clear", use_context="outdoor")
        self.assertEqual(grade, "H")
        self.assertNotIn("pla_for_outdoor_poor_fit", flags)

    def test_good_colour_match_is_H(self):
        grade, _, _, _ = self.fit()
        self.assertEqual(grade, "H")

    def test_colour_mismatch_caps_at_M(self):
        grade, _, _, flags = self.fit(colour_match=False)
        self.assertEqual(grade, "M")
        self.assertIn("colour_mismatch", flags)

    def test_poor_suitability_is_L(self):
        grade, _, _, flags = self.fit(material_suitability="poor")
        self.assertEqual(grade, "L")
        self.assertIn("material_suitability_poor", flags)


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.inventory = bq.load_inventory(ROOT / "inputs" / "filament_inventory.json")

    def test_unknown_factor_value_rejected(self):
        with self.assertRaises(bq.InputError):
            bq._base_record(synthetic_raw(market_grade="X"), "manual", self.inventory, "t")

    def test_missing_evidence_rejected(self):
        raw = synthetic_raw()
        del raw["market_evidence"]
        with self.assertRaises(bq.InputError):
            bq._base_record(raw, "manual", self.inventory, "t")

    def test_empty_evidence_rejected(self):
        with self.assertRaises(bq.InputError):
            bq._base_record(synthetic_raw(market_evidence=""), "manual", self.inventory, "t")

    def test_est_filament_zero_rejected(self):
        with self.assertRaises(bq.InputError):
            bq._base_record(synthetic_raw(est_filament_g=0), "manual", self.inventory, "t")

    def test_est_filament_null_accepted(self):
        rec = bq._base_record(synthetic_raw(est_filament_g=None), "manual", self.inventory, "t")
        self.assertIsNone(rec["est_filament_g"])

    def test_unknown_next_action_rejected(self):
        with self.assertRaises(bq.InputError):
            bq._base_record(synthetic_raw(next_action="SHIP"), "manual", self.inventory, "t")

    def test_unknown_filament_rejected(self):
        with self.assertRaises(bq.InputError):
            bq._base_record(
                synthetic_raw(assigned_filament_id="fil-nope"), "manual", self.inventory, "t")


class HardGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.inventory = bq.load_inventory(ROOT / "inputs" / "filament_inventory.json")
        cls.queue = bq.build(ROOT, generated_at=FIXED_TS)

    def _write_patent_input(self, tmp, candidates):
        path = Path(tmp) / "patents.json"
        path.write_text(json.dumps({
            "candidates": candidates,
            "queued_at_utc": FIXED_TS, "retrieved_at_utc": FIXED_TS,
        }), encoding="utf-8")
        return path

    def test_blocklisted_patents_rejected_by_loader(self):
        for ref in sorted(bq.BLOCKLISTED_PATENTS):
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write_patent_input(tmp, [synthetic_raw(source_ref=ref)])
                with self.assertRaises(bq.InputError, msg=ref):
                    bq.load_patent_winners(path, self.inventory)

    def test_blocklisted_patents_absent_from_outputs(self):
        blob = json.dumps(self.queue)
        md = bq.render_markdown(self.queue)
        for ref in bq.BLOCKLISTED_PATENTS:
            self.assertNotIn(ref, blob)
            self.assertNotIn(ref, md)
        refs = {r["source_ref"] for r in self.queue["records"]}
        self.assertTrue(refs.isdisjoint(bq.BLOCKLISTED_PATENTS))

    def test_waiting_records_in_own_section_never_ranked(self):
        for rec in self.queue["records"]:
            if rec["next_action"] == "WAITING-ON-AIRAM":
                self.assertEqual(rec["section"], "waiting_on_airam")
                self.assertIsNone(rec["rank"])
            else:
                self.assertEqual(rec["section"], "actionable")
                self.assertIsInstance(rec["rank"], int)

    def test_siren_is_waiting_never_print(self):
        siren = [r for r in self.queue["records"] if r["source_track"] == "siren"]
        self.assertEqual(len(siren), 1)
        self.assertEqual(siren[0]["next_action"], "WAITING-ON-AIRAM")
        self.assertNotEqual(siren[0]["next_action"], "PRINT")
        self.assertIn("RPM = 0", siren[0]["blocker"])
        self.assertIn("caliper checklist", siren[0]["blocker"])
        self.assertEqual(siren[0].get("after_waiting_next_action"), "MODEL")

    def test_feed_sellable_with_unknown_licence_rejected(self):
        bad = synthetic_raw(sellable=True, licence=None, source_ref="https://example.invalid/x")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.json"
            path.write_text(json.dumps({"candidates": [bad], "queued_at_utc": FIXED_TS}),
                            encoding="utf-8")
            with self.assertRaises(bq.InputError):
                bq.load_feed_candidates(path, self.inventory)

    def test_feed_not_sellable_candidate_rejected(self):
        bad = synthetic_raw(sellable=False, licence="CC BY 4.0",
                            source_ref="https://example.invalid/x")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feed.json"
            path.write_text(json.dumps({"candidates": [bad], "queued_at_utc": FIXED_TS}),
                            encoding="utf-8")
            with self.assertRaises(bq.InputError):
                bq.load_feed_candidates(path, self.inventory)


class QueueContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = bq.build(ROOT, generated_at=FIXED_TS)

    def test_record_counts(self):
        self.assertEqual(self.queue["counts"]["total"], 12)
        self.assertEqual(self.queue["counts"]["by_track"]["patent"], 11)
        self.assertEqual(self.queue["counts"]["by_track"]["feed"], 0)
        self.assertEqual(self.queue["counts"]["by_track"]["siren"], 1)
        self.assertEqual(self.queue["counts"]["actionable"], 11)
        self.assertEqual(self.queue["counts"]["waiting_on_airam"], 1)

    def test_foosball_ranks_first_with_27(self):
        top = [r for r in self.queue["records"] if r.get("rank") == 1]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["source_ref"], "US4076244")
        self.assertEqual(top[0]["score"], 27)
        self.assertEqual(
            (top[0]["factors"]["market"]["grade"], top[0]["factors"]["ease"]["grade"],
             top[0]["factors"]["fit"]["grade"]),
            ("H", "H", "H"),
        )

    def test_actionable_sorted_by_score_then_market(self):
        actionable = [r for r in self.queue["records"] if r["section"] == "actionable"]
        keys = [(-r["score"], -r["factors"]["market"]["points"]) for r in actionable]
        self.assertEqual(keys, sorted(keys))
        ranks = [r["rank"] for r in actionable]
        self.assertEqual(ranks, list(range(1, len(actionable) + 1)))

    def test_every_record_has_factors_filament_and_null_or_positive_grams(self):
        for rec in self.queue["records"]:
            for factor in ("market", "ease", "fit"):
                self.assertIn(rec["factors"][factor]["grade"], bq.GRADE_POINTS)
                self.assertEqual(
                    rec["factors"][factor]["points"],
                    bq.GRADE_POINTS[rec["factors"][factor]["grade"]],
                )
            self.assertTrue(rec["filament_fit"]["assigned_filament"])
            self.assertTrue(rec["filament_fit"]["why"])
            self.assertTrue(rec["est_filament_g"] is None or rec["est_filament_g"] > 0)
            self.assertEqual(
                rec["score"],
                rec["factors"]["market"]["points"]
                * rec["factors"]["ease"]["points"]
                * rec["factors"]["fit"]["points"],
            )

    def test_non_print_routes_keep_labels(self):
        routes = {r["source_ref"]: r["make_route"] for r in self.queue["records"]}
        self.assertEqual(routes["US6415689"], "METAL FAB")
        self.assertEqual(routes["USD165508"], "RE-HOUSE")
        self.assertEqual(routes["USD174098"], "RE-HOUSE")


class DeterminismTests(unittest.TestCase):
    def test_two_builds_same_bytes_with_fixed_timestamp(self):
        q1 = bq.build(ROOT, generated_at=FIXED_TS)
        q2 = bq.build(ROOT, generated_at=FIXED_TS)
        s1 = json.dumps(q1, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        s2 = json.dumps(q2, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        self.assertEqual(s1, s2)
        self.assertEqual(bq.render_markdown(q1), bq.render_markdown(q2))

    def test_generated_at_is_the_only_difference(self):
        q1 = bq.build(ROOT, generated_at="2026-11-17T00:00:00Z")
        q2 = bq.build(ROOT, generated_at="2026-11-18T00:00:00Z")
        q2["generated_at_utc"] = q1["generated_at_utc"]
        self.assertEqual(q1, q2)


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = bq.build(ROOT, generated_at=FIXED_TS)
        cls.md = bq.render_markdown(cls.queue)

    def test_every_queue_id_exactly_once(self):
        for rec in self.queue["records"]:
            self.assertEqual(self.md.count(rec["id"]), 1, rec["id"])

    def test_header_contents(self):
        self.assertIn(FIXED_TS, self.md)
        self.assertIn("Filament snapshot date: 2026-11-17", self.md)
        self.assertIn("prioritization heuristic", self.md)
        self.assertIn("NOT a profit prediction", self.md)

    def test_waiting_section_states_siren_blocker(self):
        self.assertIn("## Waiting on Airam", self.md)
        self.assertIn("RPM = 0", self.md)
        self.assertIn("D-flat depth is UNKNOWN", self.md)
        self.assertIn("gear ratio is UNVERIFIED", self.md)

    def test_ranked_table_has_all_actionable(self):
        for rec in self.queue["records"]:
            if rec["section"] == "actionable":
                self.assertIn(f"| {rec['rank']} | {rec['id']} |", self.md)


if __name__ == "__main__":
    unittest.main()
