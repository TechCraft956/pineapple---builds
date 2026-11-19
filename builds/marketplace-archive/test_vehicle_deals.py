#!/usr/bin/env python3
"""Tests for the extracted Vehicle Financing Deal Optimizer.

Source: marketplace-scraper/backend/vehicle_deals.py, copied verbatim into
this workspace (diff-verified identical). Its only dependency is pydantic.

Payment fixtures F1-F5 were computed INDEPENDENTLY of the module with
Python's decimal module (exact decimal amortization, 28-digit precision)
in /tmp/fixtures.py, then rounded to cents. The module computes totals from
the UNROUNDED monthly payment and rounds only at output, so the fixtures
below follow that same rule (e.g. F1: 204.927696... x 60 = 12295.66 interest
1695.66, not 204.93 x 60).

Recommendation fixtures were hand-checked term by term (every penalty and
bonus) in /tmp/verify_scores.py before being frozen here.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from vehicle_deals import (
    VehicleDealEvaluationRequest,
    evaluate_vehicle_deals,
)

HERE = Path(__file__).resolve().parent
CLI = HERE / "vehicle_deals_cli.py"


def base_deal(**overrides):
    deal = {
        "listing_title": "2018 Toyota Tacoma SR5",
        "asking_price": 12000,
        "year": 2018,
        "make": "Toyota",
        "model": "Tacoma",
        "mileage": 45000,
        "apr": 6.0,
        "loan_term_months": 60,
        "down_payment": 2000,
        "estimated_taxes_and_fees": 600,
        "distance_miles": 20,
        "estimated_fair_market_value": 13000,
    }
    deal.update(overrides)
    return deal


# ---------------------------------------------------------------- payment math
class TestPaymentMath(unittest.TestCase):
    """Hand-computed amortization fixtures (APR, term, down, total cost)."""

    # (label, deal overrides, financed, payment, interest, total_acq, spread)
    FIXTURES = [
        ("F1 6% 60mo", {}, 10600.00, 204.93, 1695.66, 14895.66, -1895.66),
        ("F2 0% APR", {"asking_price": 9000, "down_payment": 0,
                        "estimated_taxes_and_fees": 0, "apr": 0.0,
                        "loan_term_months": 36,
                        "estimated_fair_market_value": 9500},
         9000.00, 250.00, 0.00, 9000.00, 500.00),
        ("F3 9.9% 72mo", {"asking_price": 20000, "down_payment": 5000,
                          "estimated_taxes_and_fees": 1000, "apr": 9.9,
                          "loan_term_months": 72,
                          "estimated_fair_market_value": 22000},
         16000.00, 295.61, 5283.72, 27283.72, -5283.72),
        ("F4 full down payment", {"asking_price": 8000, "down_payment": 8400,
                                  "estimated_taxes_and_fees": 400, "apr": 5.0,
                                  "loan_term_months": 48,
                                  "estimated_fair_market_value": 9000},
         0.00, 0.00, 0.00, 8800.00, 200.00),
        ("F5 7.25% 48mo", {"asking_price": 15500, "down_payment": 3000,
                           "estimated_taxes_and_fees": 775, "apr": 7.25,
                           "loan_term_months": 48,
                           "estimated_fair_market_value": 16000},
         13275.00, 319.43, 2057.56, 19107.56, -3107.56),
    ]

    def test_payment_fixtures(self):
        for label, overrides, fin, pay, interest, acq, spread in self.FIXTURES:
            with self.subTest(label):
                got = evaluate_vehicle_deals(
                    VehicleDealEvaluationRequest(deals=[base_deal(**overrides)])
                ).deals[0]
                self.assertEqual(got.financed_amount, fin, label)
                self.assertEqual(got.estimated_monthly_payment, pay, label)
                self.assertEqual(got.total_interest_paid, interest, label)
                self.assertEqual(got.total_acquisition_cost, acq, label)
                self.assertEqual(got.market_spread, spread, label)

    def test_zero_apr_is_exact_division(self):
        got = evaluate_vehicle_deals(
            VehicleDealEvaluationRequest(deals=[base_deal(
                asking_price=9000, down_payment=0, estimated_taxes_and_fees=0,
                apr=0.0, loan_term_months=36)])
        ).deals[0]
        self.assertEqual(got.estimated_monthly_payment, 250.00)
        self.assertEqual(got.total_interest_paid, 0.00)

    def test_down_payment_reduces_financed_amount(self):
        low = evaluate_vehicle_deals(VehicleDealEvaluationRequest(
            deals=[base_deal(down_payment=2000)])).deals[0]
        high = evaluate_vehicle_deals(VehicleDealEvaluationRequest(
            deals=[base_deal(down_payment=8000)])).deals[0]
        self.assertEqual(low.financed_amount, 10600.00)
        self.assertEqual(high.financed_amount, 4600.00)
        self.assertLess(high.estimated_monthly_payment,
                        low.estimated_monthly_payment)
        self.assertLess(high.total_interest_paid, low.total_interest_paid)


# ------------------------------------------------------- recommendations
PURSUE = base_deal(
    asking_price=8000, down_payment=1000, estimated_taxes_and_fees=400,
    apr=4.0, loan_term_months=48, estimated_fair_market_value=12000,
    condition_score=9, seller_type="private", title_status="clean",
    inventory_age_days=60)
NEGOTIATE = base_deal(
    listing_title="2019 Ford F-150 XLT", asking_price=11000, year=2019,
    make="Ford", model="F-150", mileage=65000, apr=5.5,
    loan_term_months=48, down_payment=1500, estimated_taxes_and_fees=500,
    distance_miles=30, estimated_fair_market_value=12500,
    condition_score=7, seller_type="private", title_status="clean",
    inventory_age_days=10)
PASS = base_deal(
    listing_title="2012 Chevy Silverado LT", asking_price=18000, year=2012,
    make="Chevrolet", model="Silverado", mileage=150000, apr=12.0,
    loan_term_months=84, down_payment=500, estimated_taxes_and_fees=1500,
    distance_miles=200, estimated_fair_market_value=12000,
    condition_score=4, seller_type="auction", title_status="rebuilt",
    inventory_age_days=5)


class TestRecommendations(unittest.TestCase):
    def test_pursue_fixture(self):
        got = evaluate_vehicle_deals(
            VehicleDealEvaluationRequest(deals=[PURSUE])).deals[0]
        self.assertEqual(got.deal_score, 95)
        self.assertEqual(got.recommendation, "pursue")
        self.assertEqual(got.estimated_monthly_payment, 167.09)
        self.assertEqual(got.total_interest_paid, 620.08)
        self.assertEqual(got.total_acquisition_cost, 9420.08)
        self.assertEqual(got.market_spread, 2579.92)

    def test_negotiate_fixture(self):
        got = evaluate_vehicle_deals(
            VehicleDealEvaluationRequest(deals=[NEGOTIATE])).deals[0]
        self.assertEqual(got.deal_score, 54)
        self.assertEqual(got.recommendation, "negotiate")
        self.assertEqual(got.estimated_monthly_payment, 232.56)
        self.assertEqual(got.total_interest_paid, 1163.11)
        self.assertEqual(got.total_acquisition_cost, 13163.11)
        self.assertEqual(got.market_spread, -663.11)

    def test_pass_fixture(self):
        got = evaluate_vehicle_deals(
            VehicleDealEvaluationRequest(deals=[PASS])).deals[0]
        self.assertEqual(got.deal_score, 0)
        self.assertEqual(got.recommendation, "pass")
        self.assertEqual(got.estimated_monthly_payment, 335.40)
        self.assertEqual(got.total_interest_paid, 9173.76)
        self.assertEqual(got.total_acquisition_cost, 30173.76)
        self.assertEqual(got.market_spread, -18173.76)

    def test_ranking_order_and_best_deal(self):
        # Deliberately shuffled input: worst first.
        got = evaluate_vehicle_deals(VehicleDealEvaluationRequest(
            deals=[PASS, NEGOTIATE, PURSUE]))
        self.assertEqual([d.listing_title for d in got.deals], [
            "2018 Toyota Tacoma SR5", "2019 Ford F-150 XLT",
            "2012 Chevy Silverado LT"])
        self.assertEqual([d.rank for d in got.deals], [1, 2, 3])
        self.assertEqual([d.recommendation for d in got.deals],
                         ["pursue", "negotiate", "pass"])
        self.assertEqual(got.best_deal.listing_title, "2018 Toyota Tacoma SR5")
        self.assertEqual(got.best_deal.rank, 1)

    def test_scores_descending_with_rank(self):
        got = evaluate_vehicle_deals(VehicleDealEvaluationRequest(
            deals=[PASS, NEGOTIATE, PURSUE]))
        scores = [d.deal_score for d in got.deals]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_pure_function_same_input_same_output(self):
        req = VehicleDealEvaluationRequest(deals=[PURSUE, NEGOTIATE])
        first = evaluate_vehicle_deals(req).model_dump_json()
        second = evaluate_vehicle_deals(req).model_dump_json()
        self.assertEqual(first, second)


# ---------------------------------------------------------- invalid inputs
class TestInvalidInputs(unittest.TestCase):
    BAD_DEALS = {
        "asking_price zero": {"asking_price": 0},
        "asking_price negative": {"asking_price": -100},
        "apr above 35": {"apr": 35.01},
        "apr negative": {"apr": -1},
        "term below 12": {"loan_term_months": 11},
        "term above 96": {"loan_term_months": 97},
        "down payment exceeds price+fees": {"down_payment": 20000},
        "year too old": {"year": 1979},
        "year too new": {"year": 2101},
        "mileage negative": {"mileage": -1},
        "mileage above cap": {"mileage": 500001},
        "fair value zero": {"estimated_fair_market_value": 0},
        "title too short": {"listing_title": "ab"},
        "bad seller_type": {"seller_type": "broker"},
        "bad title_status": {"title_status": "salvage"},
        "condition above 10": {"condition_score": 11},
        "distance negative": {"distance_miles": -5},
    }

    def test_bad_deals_rejected(self):
        for label, overrides in self.BAD_DEALS.items():
            with self.subTest(label):
                with self.assertRaises(ValidationError, msg=label):
                    VehicleDealEvaluationRequest(deals=[base_deal(**overrides)])

    def test_empty_deals_rejected(self):
        with self.assertRaises(ValidationError):
            VehicleDealEvaluationRequest(deals=[])

    def test_eleven_deals_rejected(self):
        with self.assertRaises(ValidationError):
            VehicleDealEvaluationRequest(deals=[base_deal()] * 11)

    def test_ten_deals_accepted(self):
        got = evaluate_vehicle_deals(VehicleDealEvaluationRequest(
            deals=[base_deal(listing_title=f"Deal {i}") for i in range(10)]))
        self.assertEqual(len(got.deals), 10)

    def test_missing_required_field_rejected(self):
        deal = base_deal()
        del deal["apr"]
        with self.assertRaises(ValidationError):
            VehicleDealEvaluationRequest(deals=[deal])

    def test_down_payment_equal_to_price_plus_fees_is_valid(self):
        got = evaluate_vehicle_deals(VehicleDealEvaluationRequest(
            deals=[base_deal(down_payment=12600)])).deals[0]
        self.assertEqual(got.financed_amount, 0.00)
        self.assertEqual(got.estimated_monthly_payment, 0.00)


# ------------------------------------------------------- import isolation
FORBIDDEN_MODULES = {
    "playwright", "facebook", "fastapi", "requests", "bs4",
    "beautifulsoup4", "aiohttp", "aiosqlite", "pymongo", "selenium",
    "uvicorn", "emergentintegrations", "scraper", "dashboard",
    "notifier", "server",
}


class TestImportIsolation(unittest.TestCase):
    def test_source_imports_only_typing_and_pydantic(self):
        tree = ast.parse((HERE / "vehicle_deals.py").read_text())
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        self.assertEqual(roots, {"__future__", "pydantic", "typing"})

    def test_no_forbidden_module_loaded_at_runtime(self):
        code = (
            "import sys; import vehicle_deals; "
            "print('\\n'.join(sorted(sys.modules)))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=HERE,
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        loaded = {m.split(".")[0] for m in proc.stdout.split()}
        self.assertTrue(FORBIDDEN_MODULES.isdisjoint(loaded),
                        f"forbidden modules loaded: {FORBIDDEN_MODULES & loaded}")

    def test_extracted_module_matches_recovered_original(self):
        import hashlib
        orig = Path.home() / ("workspace/pineapple/recovered/marketplace-scraper"
                              "/backend/vehicle_deals.py")
        mine = HERE / "vehicle_deals.py"
        self.assertTrue(orig.exists(), "recovered original missing")
        self.assertEqual(hashlib.md5(orig.read_bytes()).hexdigest(),
                         hashlib.md5(mine.read_bytes()).hexdigest(),
                         "extracted module differs from the recovered original")


# ---------------------------------------------------------------------- CLI
class TestCLI(unittest.TestCase):
    def _run_cli(self, payload, stdin=False):
        with tempfile.TemporaryDirectory() as tmp:
            if stdin:
                proc = subprocess.run(
                    [sys.executable, str(CLI), "--json", "-"],
                    input=json.dumps(payload), cwd=HERE,
                    capture_output=True, text=True, timeout=60)
            else:
                req = Path(tmp) / "request.json"
                req.write_text(json.dumps(payload))
                proc = subprocess.run(
                    [sys.executable, str(CLI), "--json", str(req)],
                    cwd=HERE, capture_output=True, text=True, timeout=60)
            return proc

    def test_cli_file_input_ranks(self):
        proc = self._run_cli({"deals": [PASS, NEGOTIATE, PURSUE]})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual([d["rank"] for d in out["deals"]], [1, 2, 3])
        self.assertEqual(out["best_deal"]["recommendation"], "pursue")
        self.assertEqual(out["deals"][0]["deal_score"], 95)

    def test_cli_stdin_input(self):
        proc = self._run_cli({"deals": [PURSUE]}, stdin=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["deals"][0]["recommendation"], "pursue")

    def test_cli_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "request.json"
            outp = Path(tmp) / "result.json"
            req.write_text(json.dumps({"deals": [PURSUE]}))
            proc = subprocess.run(
                [sys.executable, str(CLI), "--json", str(req),
                 "--output", str(outp)], cwd=HERE,
                capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "")
            out = json.loads(outp.read_text())
            self.assertEqual(out["deals"][0]["deal_score"], 95)

    def test_cli_invalid_json_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "bad.json"
            req.write_text("{not json")
            proc = subprocess.run(
                [sys.executable, str(CLI), "--json", str(req)],
                cwd=HERE, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, "")
            self.assertIn("error", proc.stderr.lower())

    def test_cli_invalid_deal_fails_cleanly(self):
        proc = self._run_cli({"deals": [base_deal(apr=99)]})
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("error", proc.stderr.lower())

    def test_cli_runs_from_another_directory(self):
        # Proves standalone: no reliance on cwd or the recovered clone.
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "request.json"
            req.write_text(json.dumps({"deals": [PURSUE]}))
            proc = subprocess.run(
                [sys.executable, str(CLI), "--json", str(req)],
                cwd=tmp, capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(HERE)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["deals"][0]["rank"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
