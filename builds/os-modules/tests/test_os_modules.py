"""tests/test_os_modules.py — BUILD-20261117-006 (Task 4).

Covers all 7 GPT QA gates + the brief's acceptance tests:
  1. sensor ingest validation + alert-rule boundaries
  2. simulator math vs hand-computed fixtures (plain-float recomputation)
  3. simulator selftest exit-code regression (missing data -> 1, restored -> 0)
  4. learning recalibrate on synthetic closed outcomes (append-only log)
  5. dashboard render with empty engines + no cross-user leak + feed link-out
  6. network first-run kit (SAMPLE users only, audit log, permission matrix)
  7. feed writer mapping (ANALYSIS ONLY verbatim, sensor lat/lon + rule)
  8. recovered originals untouched (git status clean)

No network in tests: the socket constructor is blocked module-wide. The
live feed round-trip is NOT here — it is verify_feed_roundtrip.py (scratch
feed instance on 127.0.0.1:8102). Run with the feed-dash venv python:
  /home/hatch/workspace/pineapple/builds/feed-dash/.venv/bin/python -m pytest tests/ -q
"""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
VENV_PY = "/home/hatch/workspace/pineapple/builds/feed-dash/.venv/bin/python"
# System python3 carries sympy 1.12; the pytest venv does not. All simulator
# work (in-process import would fail in the venv) goes through sim_driver.py
# or direct subprocess calls under SYS_PY.
SYS_PY = "/usr/bin/python3"

# --- no network in tests ---------------------------------------------------
_real_socket = socket.socket


def _blocked_socket(*a, **k):
    raise RuntimeError("network disabled in tests")


socket.socket = _blocked_socket


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sensors():
    sys.path.insert(0, str(WORKSPACE / "09_SENSORS"))
    return load_module("sensor_ingest_ws", WORKSPACE / "09_SENSORS" / "sensor_ingest.py")


@pytest.fixture(scope="module")
def sim_results():
    """Simulator deltas/items via sim_driver.py under the system python
    (sympy lives there, not in the pytest venv)."""
    def run(mode):
        proc = subprocess.run([SYS_PY, str(WORKSPACE / "tests" / "sim_driver.py"), mode],
                              capture_output=True, text=True, cwd=str(WORKSPACE))
        assert proc.returncode == 0, "sim_driver %s failed: %s" % (mode, proc.stderr[-1000:])
        return json.loads(proc.stdout)
    return {"deltas": run("deltas"), "items": run("items")}


def _samples():
    return json.loads((WORKSPACE / "06_DECISION" / "simulator" / "data"
                       / "sample_scenarios.json").read_text(encoding="utf-8"))["scenarios"]


@pytest.fixture(scope="module")
def learning_mod():
    sys.path.insert(0, str(WORKSPACE / "06_DECISION"))
    return load_module("learning_ws", WORKSPACE / "06_DECISION" / "learning.py")


@pytest.fixture(scope="module")
def dashboard_mod():
    sys.path.insert(0, str(WORKSPACE / "07_NETWORK"))
    return load_module("dashboard_ws", WORKSPACE / "07_NETWORK" / "dashboard.py")


# --- 1. sensor ingest validation -------------------------------------------
class TestSensorIngest:
    def test_valid_reading_accepted(self, sensors):
        store = []
        res = sensors.ingest({"device_id": "esp32_garage_01", "ts": "2026-06-26T06:00:00Z",
                              "metric": "state", "value": "closed"}, store=store)
        assert res["ok"] is True and res["count"] == 1 and len(store) == 1

    def test_unknown_device_rejected_store_unchanged(self, sensors):
        store = [{"device_id": "esp32_garage_01", "ts": "2026-06-26T06:00:00Z",
                  "metric": "state", "value": "closed"}]
        res = sensors.ingest({"device_id": "esp32_unknown_99", "ts": "2026-06-26T06:00:00Z",
                              "metric": "state", "value": "open"}, store=store)
        assert res["ok"] is False and "unknown device_id" in res["error"]
        assert len(store) == 1

    def test_bad_timestamp_rejected_store_unchanged(self, sensors):
        store = []
        res = sensors.ingest({"device_id": "esp32_garage_01", "ts": "not-a-date",
                              "metric": "state", "value": "open"}, store=store)
        assert res["ok"] is False and "ISO-8601" in res["error"]
        assert store == []

    def test_missing_keys_rejected(self, sensors):
        store = []
        res = sensors.ingest({"device_id": "esp32_garage_01", "metric": "state"}, store=store)
        assert res["ok"] is False and "missing keys" in res["error"]
        assert store == []

    def test_invalid_value_type_rejected_store_unchanged(self, sensors):
        # NOTE (finding, not a gap in the test): the recovered module validates
        # the Reading schema and value TYPE only — it has no numeric range
        # check, so an out-of-range NUMBER (e.g. temp_f 999) is accepted by
        # the recovered code's design. Values outside the accepted type
        # domain (None / list / dict) ARE rejected; that is what is tested.
        store = []
        for bad in (None, [1, 2], {"v": 1}):
            res = sensors.ingest({"device_id": "esp32_garage_01",
                                  "ts": "2026-06-26T06:00:00Z",
                                  "metric": "state", "value": bad}, store=store)
            assert res["ok"] is False, "value %r was not rejected" % (bad,)
            assert store == []

    def test_restored_data_selftest_contract(self, sensors):
        devices = sensors.load_devices()
        readings = sensors.load_readings()
        assert len(devices) == 8 and len(readings) == 12
        assert {d["sensor_type"] for d in devices.values()} == set(sensors.SENSOR_TYPES)
        items = sensors.items()
        assert len(items) == 4  # garage open, garage left open, water, bike battery
        titles = " | ".join(i["title"] for i in items)
        assert "Garage opened" in titles and "Water detected" in titles and "11.8" in titles
        for it in items:  # every alert carries RGV lat/lon + the rule's device
            assert 25.0 < it["lat"] < 27.0 and -99.5 < it["lon"] < -97.0
            assert it["device_id"] in devices


# --- 2. alert-rule boundaries ----------------------------------------------
class TestAlertBoundaries:
    @pytest.mark.parametrize("value,expected", [(11.99, True), (12.0, False), (12.01, False)])
    def test_battery_lt_boundary(self, sensors, value, expected):
        rule = {"metric": "volts", "op": "lt", "threshold": 12.0}
        assert sensors._rule_fires(rule, {"value": value}) is expected

    @pytest.mark.parametrize("value,expected", [(85.0, False), (85.01, True), (84.99, False)])
    def test_temp_gt_boundary(self, sensors, value, expected):
        rule = {"metric": "temp_f", "op": "gt", "threshold": 85}
        assert sensors._rule_fires(rule, {"value": value}) is expected

    @pytest.mark.parametrize("value,expected", [("open", True), ("OPEN", True), ("closed", False)])
    def test_state_change_to(self, sensors, value, expected):
        rule = {"metric": "state", "op": "change_to", "threshold": "open"}
        assert sensors._rule_fires(rule, {"value": value}) is expected

    def test_quiet_devices_stay_quiet(self, sensors):
        devices = sensors.load_devices()
        readings = sensors.load_readings()
        alerts = sensors.active_alerts(devices, readings)
        fired = {a["device_id"] for a in alerts}
        assert fired == {"esp32_garage_01", "esp32_water_washer", "esp32_bike_battery"}
        assert "esp32_motion_driveway" not in fired  # state=clear
        assert "esp32_freezer" not in fired           # 2.1F, threshold 10F
        assert "esp32_gate" not in fired and "esp32_mailbox" not in fired


# --- 3. simulator math vs hand-computed fixtures ---------------------------
# Expected deltas computed INDEPENDENTLY (plain float math, no sympy) from
# the sample scenario params; see BUILD_REPORT.md for the derivation.
EXPECTED_DELTAS = {
    "flip_vs_save": {"1mo": 146.31, "1yr": 1756.50, "5yr": 8801.56},
    "fha_now_vs_later": {"1mo": -4540.94, "1yr": 6692.15, "5yr": 12482.89},
    "debt_vs_deploy": {"1mo": -198.15, "1yr": -2563.50, "5yr": -18627.76},
}


def _monthly_rate(annual):
    return (1 + annual) ** (1 / 12) - 1


def _plain_flip(p):
    m = _monthly_rate(p["savings_apy"])
    gross = p["est_resale"] - p["buy_price"] - p["recon_cost"]
    net = gross - p["est_resale"] * p["fees_pct"]
    ev = p["sell_prob"] * net + (1 - p["sell_prob"]) * (-p["recon_cost"])
    out = {}
    for lab, mo in {"1mo": 1, "1yr": 12, "5yr": 60}.items():
        fl = ev * p["flips_per_year"] * (mo / 12)
        tied = p["buy_price"] + p["recon_cost"]
        out[lab] = round(fl - tied * ((1 + m) ** mo - 1)
                         + (p["cash_on_hand"] - tied) * ((1 + m) ** mo - 1), 2)
    return out


def _amort_bal(pr, r, n, term=360):
    if r == 0:
        return pr * (1 - n / term)
    pay = pr * r * (1 + r) ** term / ((1 + r) ** term - 1)
    return pr * (1 + r) ** n - pay * ((1 + r) ** n - 1) / r


def _plain_fha(p):
    price, down = p["home_price"], p["home_price"] * p["fha_down_pct"]
    loan, closing = price - down, price * p["closing_pct"]
    m_now, m_appr = _monthly_rate(p["rate_now"]), _monthly_rate(p["appreciation_yr"])

    def buy_now(mo):
        hv = price * (1 + m_appr) ** mo
        carry = ((price * p["property_tax_rate"] / 12) + (p["insurance_yr"] / 12)
                 + (loan * p["mip_annual_pct"] / 12)) * mo
        return hv - _amort_bal(loan, m_now, mo) - (down + closing) - carry + p["rent_now"] * mo

    def wait(mo):
        if mo <= p["wait_months"]:
            return 0.0
        pl = price * (1 + m_appr) ** p["wait_months"]
        ll = pl - pl * p["fha_down_pct"]
        om = mo - p["wait_months"]
        carry = ((pl * p["property_tax_rate"] / 12) + (p["insurance_yr"] / 12)
                 + (ll * p["mip_annual_pct"] / 12)) * om
        return (pl * (1 + m_appr) ** om - _amort_bal(ll, _monthly_rate(p["rate_later"]), om)
                - (pl * p["fha_down_pct"] + pl * p["closing_pct"]) - carry
                + p["rent_now"] * om)
    return {lab: round(buy_now(mo) - wait(mo), 2)
            for lab, mo in {"1mo": 1, "1yr": 12, "5yr": 60}.items()}


def _plain_debt(p):
    m_apr, m_dep = _monthly_rate(p["debt_apr"]), _monthly_rate(p["deploy_return_yr"])
    out = {}
    for lab, mo in {"1mo": 1, "1yr": 12, "5yr": 60}.items():
        paid = min(p["capital"], p["debt_balance"])
        pd = paid * ((1 + m_apr) ** mo - 1)
        ev = (p["deploy_success_prob"] * (p["capital"] * ((1 + m_dep) ** mo - 1))
              + (1 - p["deploy_success_prob"]) * (-p["capital"] * 0.5 * mo / 12))
        out[lab] = round(ev - p["debt_balance"] * ((1 + m_apr) ** mo - 1) - pd, 2)
    return out


_PLAIN = {"flip_vs_save": _plain_flip, "fha_now_vs_later": _plain_fha,
          "debt_vs_deploy": _plain_debt}


class TestSimulatorMath:
    def test_deltas_match_hand_computed_fixtures(self, sim_results):
        results = sim_results["deltas"]
        assert len(results) == 3
        for res in results:
            got = res["projected_net_worth_delta"]
            for horizon, expected in EXPECTED_DELTAS[res["scenario"]].items():
                assert got[horizon] == pytest.approx(expected, abs=0.05), \
                    "%s %s: got %s, hand-computed %s" % (res["scenario"], horizon, got[horizon], expected)
            # every result carries the disclaimer + audit trail
            assert "ANALYSIS ONLY" in res["disclaimer"]
            assert res["risk"] in ("LOW", "MED", "HIGH")
            assert res["bottleneck"] and res["best_next_action"]

    def test_deltas_match_plain_float_recomputation(self, sim_results):
        for res in sim_results["deltas"]:
            plain = _PLAIN[res["scenario"]](res["params"])
            for horizon in ("1mo", "1yr", "5yr"):
                assert res["projected_net_worth_delta"][horizon] == pytest.approx(
                    plain[horizon], abs=0.05)

    def test_items_ranked_and_disclaimed(self, sim_results):
        items = sim_results["items"]
        assert len(items) == 3
        assert all("ANALYSIS ONLY" in it["disclaimer"] for it in items)
        assert [abs(i["est_value"]) for i in items] == sorted(
            [abs(i["est_value"]) for i in items], reverse=True)


# --- 4. simulator selftest exit-code regression -----------------------------
class TestSimulatorExitCode:
    def _run_selftest(self, with_data, tmp_path):
        sim_dir = tmp_path / "simulator"
        sim_dir.mkdir()
        shutil.copy(WORKSPACE / "06_DECISION" / "simulator" / "simulator.py", sim_dir)
        shutil.copy(WORKSPACE / "06_DECISION" / "simulator" / "README.md", sim_dir)
        if with_data:
            shutil.copytree(WORKSPACE / "06_DECISION" / "simulator" / "data",
                            sim_dir / "data")
        proc = subprocess.run([SYS_PY, str(sim_dir / "simulator.py"), "--selftest"],
                              capture_output=True, text=True)
        return proc.returncode, proc.stdout

    def test_missing_sample_data_exits_1(self, tmp_path):
        rc, out = self._run_selftest(False, tmp_path)
        assert rc == 1, "selftest with missing sample data exited %d, expected 1" % rc
        assert "[FAIL] missing sample data" in out

    def test_restored_sample_data_exits_0(self, tmp_path):
        rc, out = self._run_selftest(True, tmp_path)
        assert rc == 0, "selftest with restored data exited %d" % rc
        assert "SELFTEST PASSED" in out

    def test_workspace_selftests_exit_0(self):
        for script, py in ((WORKSPACE / "09_SENSORS" / "sensor_ingest.py", sys.executable),
                           (WORKSPACE / "06_DECISION" / "simulator" / "simulator.py", SYS_PY)):
            proc = subprocess.run([py, str(script), "--selftest"],
                                  capture_output=True, text=True)
            assert proc.returncode == 0, "%s --selftest exited %d: %s" % (
                script.name, proc.returncode, proc.stdout[-500:])


# --- 5. learning recalibrate on synthetic closed outcomes --------------------
class TestLearningRecalibrate:
    def _fixture_rows(self):
        # roi dimension tracks realized ROI; every other dim is neutral (50).
        # Weights must move TOWARD roi (documented direction).
        rows = []
        for i, (roi_dim, actual) in enumerate([(90, 0.50), (85, 0.40),
                                               (10, -0.30), (15, -0.20)]):
            rows.append({
                "id": "SYNTH-%d" % i, "title": "synthetic closed outcome %d" % i,
                "category": "TEST", "status": "sold" if actual > 0 else "skipped",
                "predicted_quant": 50.0, "actual_roi": actual,
                "dims": {"roi": roi_dim, "time": 50, "risk": 50,
                         "difficulty": 50, "capital": 50},
                "notes": "SYNTHETIC fixture — not a real outcome",
            })
        return rows

    def test_recalibrate_moves_weights_toward_roi(self, learning_mod, tmp_path):
        import pineapple_quant as pq
        log = tmp_path / "outcomes_log.jsonl"
        report = tmp_path / "learning_report.md"
        weights_file = tmp_path / "quant_weights.json"
        log.write_text("\n".join(json.dumps(r) for r in self._fixture_rows()) + "\n",
                       encoding="utf-8")
        before_bytes = log.read_bytes()
        old_weights = dict(pq.DEFAULT_WEIGHTS)
        orig_log, orig_report = learning_mod.LOG, learning_mod.REPORT
        orig_weights_path = pq.weights_path
        try:
            learning_mod.LOG, learning_mod.REPORT = log, report
            pq.weights_path = lambda: weights_file  # noqa: E731
            learning_mod.cmd_recalibrate()
        finally:
            learning_mod.LOG, learning_mod.REPORT = orig_log, orig_report
            pq.weights_path = orig_weights_path
        # append-only: recalibrate must not touch the outcomes log
        assert log.read_bytes() == before_bytes, "recalibrate rewrote the outcomes log"
        new_weights = json.loads(weights_file.read_text(encoding="utf-8"))["weights"]
        assert abs(sum(new_weights.values()) - 1.0) < 1e-6
        assert new_weights["roi"] > old_weights["roi"], \
            "roi weight did not move up: %s -> %s" % (old_weights["roi"], new_weights["roi"])
        assert report.exists() and "Closed outcomes used: 4" in report.read_text(encoding="utf-8")

    def test_recalibrate_needs_three_closed(self, learning_mod, tmp_path):
        import pineapple_quant as pq
        log = tmp_path / "outcomes_log.jsonl"
        log.write_text(json.dumps(self._fixture_rows()[0]) + "\n", encoding="utf-8")
        orig_log = learning_mod.LOG
        try:
            learning_mod.LOG = log
            learning_mod.cmd_recalibrate()  # must not crash, must not write weights
        finally:
            learning_mod.LOG = orig_log
        assert not (tmp_path / "quant_weights.json").exists()

    def test_workspace_has_zero_real_outcomes(self):
        proc = subprocess.run([sys.executable, str(WORKSPACE / "06_DECISION" / "learning.py"),
                               "stats"], capture_output=True, text=True)
        assert proc.returncode == 0
        assert "Outcomes log: 0 total" in proc.stdout
        assert not (WORKSPACE / "06_DECISION" / "outcomes_log.jsonl").exists(), \
            "no real outcome may be invented — actual_roi stays null until one is logged"


# --- 6. dashboard render ------------------------------------------------------
class TestDashboard:
    def test_renders_with_empty_engines(self, dashboard_mod):
        api = dashboard_mod.api
        orig = (api.network_users, api.brief, api.scan_stats, api.plugins,
                api.learning_stats, api.evolution)
        try:
            api.network_users = lambda: []
            api.brief = lambda: {"top_actions": [], "total_considered": 0}
            api.scan_stats = lambda: {"indexed": 0}
            api.plugins = lambda: []
            api.learning_stats = lambda: {"total": 0}
            api.evolution = lambda: {"review": {}, "questions": [], "backlog": [],
                                     "registry": [], "roadmap": {}}
            html = dashboard_mod.render_html("selftest")
        finally:
            (api.network_users, api.brief, api.scan_stats, api.plugins,
             api.learning_stats, api.evolution) = orig
        assert "PINEAPPLE NETWORK OS" in html and "No users" in html
        assert "api/feed/opportunities" in html  # link-out to the shared feed

    def test_real_engines_no_cross_user_leak(self, dashboard_mod):
        # Plant a marker in sample_owner's private workspace; it must never
        # appear in the rendered page, while both usernames legitimately do.
        marker = "LEAK-MARKER-OWNER-7f3a9c2e"
        doc = WORKSPACE / "07_NETWORK" / "workspaces" / "sample_owner" / "documents" / "private.txt"
        doc.write_text("owner-private note: %s\n" % marker, encoding="utf-8")
        try:
            html = dashboard_mod.render_html()
        finally:
            doc.unlink()
        assert marker not in html, "owner workspace content leaked into dashboard HTML"
        assert "workspaces/sample_owner" not in html
        assert "sample_owner" in html and "sample_family" in html
        assert "api/feed/opportunities" in html

    def test_selftest_renders_preview(self):
        proc = subprocess.run(
            [sys.executable, str(WORKSPACE / "07_NETWORK" / "dashboard.py"),
             "--port", "8899", "--selftest"], capture_output=True, text=True)
        assert proc.returncode == 0
        preview = WORKSPACE / "07_NETWORK" / "dashboard_preview.html"
        assert preview.exists() and preview.stat().st_size > 3000
        assert "PINEAPPLE NETWORK OS" in preview.read_text(encoding="utf-8")


# --- 7. network first-run kit ---------------------------------------------------
class TestFirstRunKit:
    def test_kit_in_temp_copy(self, tmp_path):
        net_copy = tmp_path / "07_NETWORK"
        shutil.copytree(WORKSPACE / "07_NETWORK", net_copy,
                        ignore=shutil.ignore_patterns("users.json", "audit_log.jsonl",
                                                      "workspaces", "dashboard_preview.html",
                                                      "first_run_kit_log.md", "__pycache__"))
        kit = WORKSPACE / "scripts" / "first_run_kit.py"
        proc = subprocess.run([sys.executable, str(kit), "--network-dir", str(net_copy)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        users = json.loads((net_copy / "users.json").read_text(encoding="utf-8"))["users"]
        assert set(users) == {"sample_owner", "sample_family"}
        for u in users.values():
            assert u["password_algo"] == "pbkdf2_sha256"
            assert "password_hash" in u and "password_salt" in u
            assert all(c in "0123456789abcdef" for c in u["password_hash"])
        audit = (net_copy / "audit_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(audit) == 2 and all(json.loads(ln)["action"] == "create_user" for ln in audit)
        assert "create_watchlists -> ALLOW (OWNER god_mode)" in proc.stdout
        assert "create_watchlists -> DENY (role=FAMILY_USER)" in proc.stdout
        assert "raw_fs -> DENY (role=FAMILY_USER)" in proc.stdout
        # idempotent re-run: no new users, no new audit entries
        proc2 = subprocess.run([sys.executable, str(kit), "--network-dir", str(net_copy)],
                               capture_output=True, text=True)
        assert proc2.returncode == 0 and "created=none" in proc2.stdout
        audit2 = (net_copy / "audit_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(audit2) == 2

    def test_workspace_users_are_sample_only(self):
        users = json.loads((WORKSPACE / "07_NETWORK" / "users.json")
                           .read_text(encoding="utf-8"))["users"]
        assert set(users) == {"sample_owner", "sample_family"}
        assert users["sample_owner"]["is_owner"] is True
        assert users["sample_family"]["role"] == "FAMILY_USER"


# --- 8. feed writer mapping ----------------------------------------------------
class TestFeedWriters:
    def test_sensor_writer_mapping(self):
        sys.path.insert(0, str(WORKSPACE / "writers"))
        import sensor_writer
        import sensor_ingest
        recs = sensor_writer.map_items(sensor_ingest.items())
        assert len(recs) == 4
        for rec in recs:
            assert rec["provenance"]["lat"] and rec["provenance"]["lon"]
            assert rec["provenance"]["rule"], "missing firing rule"
            assert "SAMPLE telemetry" in rec["provenance"]["warning"]
            assert rec["type"] == "other" and rec["approval_status"] == "PENDING"

    def test_simulator_writer_carries_warning_verbatim(self, sim_results):
        # simulator_writer imports simulator (sympy) — drive it under the
        # system python with no token so it prints the mapped records.
        proc = subprocess.run(
            [SYS_PY, str(WORKSPACE / "writers" / "simulator_writer.py")],
            capture_output=True, text=True,
            env={k: v for k, v in dict(os.environ).items() if k != "FEED_API_TOKEN"})
        assert proc.returncode == 2, "expected exit 2 (token unset), got %d: %s" % (
            proc.returncode, proc.stderr[-500:])
        recs = json.loads(proc.stdout)
        assert len(recs) == 3
        disclaimer = sim_results["deltas"][0]["disclaimer"]
        for rec in recs:
            assert rec["risk_notes"] == disclaimer
            assert rec["provenance"]["warning"] == disclaimer
            assert disclaimer in rec["evidence"]
            assert rec["est_value"] == rec["provenance"]["projected_net_worth_delta"]["1yr"]


# --- 9. recovered originals untouched -------------------------------------------
class TestOriginalsUntouched:
    def test_recovered_modules_untouched(self):
        # Scoped to the four trees this build copied from. (The clone as a
        # whole currently also shows an untracked 04_INTELLIGENCE/osint/out/
        # created 2026-11-17 23:39 by parallel pipeline work — not this build,
        # and outside the modules this brief touches.)
        proc = subprocess.run(
            ["git", "-C", "/home/hatch/workspace/pineapple/recovered/pineapple-os",
             "status", "--porcelain", "--", "09_SENSORS", "07_NETWORK",
             "06_DECISION", "_lib"], capture_output=True, text=True)
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", \
            "recovered modules have modifications:\n%s" % proc.stdout
