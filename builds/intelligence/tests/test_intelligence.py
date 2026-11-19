"""tests/test_intelligence.py — 04_INTELLIGENCE build test suite.

Offline only: the socket is blocked for the whole module, so no outbound
call can hide in the tests. Run from the intelligence workspace:
  ../feed-dash/.venv/bin/python -m pytest tests/ -q
"""
import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

WS = Path(__file__).resolve().parent.parent
VENV_PY = Path("/home/hatch/workspace/pineapple/builds/feed-dash/.venv/bin/python")
sys.path.insert(0, str(WS / "writers"))
sys.path.insert(0, str(WS / "_lib"))

# ---------------------------------------------------------------------------
# No network in tests.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _blocked(*a, **k):
        raise RuntimeError("network blocked in offline tests")
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def load_module(module_id, relpath):
    path = WS / relpath
    spec = importlib.util.spec_from_file_location("t_%s" % module_id, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["t_%s" % module_id] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. All eleven modules' selftests / health checks exit 0.
# ---------------------------------------------------------------------------
SELFTEST_MODULES = [
    ("cad_appraisal", "cad_appraisal/cad_appraisal.py"),
    ("code_violations", "code_violations/code_violations.py"),
    ("county_records", "county_records/county_records.py"),
    ("delinquent_tax", "delinquent_tax/delinquent_tax.py"),
    ("local_econ", "local_econ/local_econ.py"),
    ("osint", "osint/osint_public.py"),
    ("preforeclosure", "preforeclosure/preforeclosure.py"),
    ("utility_shutoffs", "utility_shutoffs/utility_shutoffs.py"),
]

# Modules with no --selftest: running them (IntelModule.run) is the check.
RUN_MODULES = [
    ("economic_checker", "economic_checker/economic_checker.py"),
    ("political_tracker", "political_tracker/political_tracker.py"),
    ("recon_engine", "recon_engine/recon_engine.py"),
]


@pytest.mark.parametrize("module_id,relpath", SELFTEST_MODULES)
def test_selftest_exit_0(module_id, relpath):
    r = subprocess.run([str(VENV_PY), (WS / relpath).name, "--selftest"],
                       cwd=WS / relpath.split("/")[0],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("module_id,relpath", RUN_MODULES)
def test_run_exit_0_and_first_run_input(module_id, relpath):
    moddir = WS / relpath.split("/")[0]
    r = subprocess.run([str(VENV_PY), (WS / relpath).name],
                       cwd=moddir, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (moddir / "input").exists()
    assert (moddir / "output" / "opportunities.json").exists()


# ---------------------------------------------------------------------------
# 2. cad_appraisal: scoring boundaries + equity math vs hand-computed fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cad():
    return load_module("cad_appraisal", "cad_appraisal/cad_appraisal.py")


def _parcel(**kw):
    base = {"account": "T-1", "cad": "Hidalgo", "county": "Hidalgo",
            "owner": "SAMPLE — Test", "situs": "1 Test St",
            "market_value": 100000, "land_value": 20000,
            "improvement_value": 80000, "living_area_sqft": 1000,
            "comp_median_value_per_sqft": 100, "last_deed_year": 2020,
            "acreage": 0.2, "year_built": 2000}
    base.update(kw)
    return base


def test_cad_equity_math_hand_computed(cad):
    # comp = 2000 sqft x $100 = $200,000; market $170,000
    # under_assessed = (200000-170000)/200000*100 = 15.0
    # land_share = 40000/170000*100 = 23.5
    p = _parcel(living_area_sqft=2000, comp_median_value_per_sqft=100,
                market_value=170000, land_value=40000, improvement_value=130000)
    eq = cad.equity_vs_comps(p)
    assert eq["comp_value"] == 200000
    assert eq["under_assessed_pct"] == 15.0
    assert eq["land_share_pct"] == 23.5
    assert eq["est_value"] == 170000


def test_cad_equity_land_only_no_comp_basis(cad):
    p = _parcel(living_area_sqft=0, comp_median_value_per_sqft=0,
                market_value=120000, land_value=120000, improvement_value=0)
    eq = cad.equity_vs_comps(p)
    assert eq["comp_value"] is None
    assert eq["under_assessed_pct"] is None
    assert eq["est_value"] == 120000


@pytest.mark.parametrize("market,should_fire", [(184000, True), (184200, False)])
def test_cad_under_assessed_boundary(cad, market, should_fire):
    # comp = 2000 x $100 = $200,000. 184000 -> exactly 8.0% (fires, >= 8.0);
    # 184200 -> 7.9% (does not fire).
    p = _parcel(living_area_sqft=2000, comp_median_value_per_sqft=100,
                market_value=market, land_value=40000, improvement_value=144000,
                last_deed_year=2020)
    rec = cad.describe(p)
    assert ("under_assessed" in cad._classify(p, rec)) == should_fire


@pytest.mark.parametrize("market,should_fire", [(200000, True), (199999, False)])
def test_cad_high_equity_boundary(cad, market, should_fire):
    p = _parcel(market_value=market, land_value=50000,
                improvement_value=market - 50000, living_area_sqft=0,
                comp_median_value_per_sqft=0, last_deed_year=2020)
    rec = cad.describe(p)
    assert ("high_equity" in cad._classify(p, rec)) == should_fire


def test_cad_long_owned_boundary(cad):
    this_year = datetime.now().year
    p25 = _parcel(last_deed_year=this_year - 25, market_value=50000,
                  living_area_sqft=0, comp_median_value_per_sqft=0)
    p24 = _parcel(last_deed_year=this_year - 24, market_value=50000,
                  living_area_sqft=0, comp_median_value_per_sqft=0)
    assert "long_owned" in cad._classify(p25, cad.describe(p25))
    assert "long_owned" not in cad._classify(p24, cad.describe(p24))


def test_cad_estate_flag_and_sample_data_coverage(cad):
    parcels = cad.load_parcels()
    assert len(parcels) == 12
    flags = set()
    for p in parcels:
        flags.update(cad._classify(p, cad.describe(p)))
        assert "SAMPLE" in str(p.get("owner", ""))
    assert {"under_assessed", "high_equity", "long_owned",
            "estate_or_trust"} <= flags
    assert len(cad.items()) == 10  # 2 parcels carry no flag


# ---------------------------------------------------------------------------
# 3. OSINT ethics gate.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def osint():
    return load_module("osint", "osint/osint_public.py")


def test_osint_clean_entities_load_and_pass_gate(osint):
    ents = osint._load_entities()
    assert len(ents) == 6
    for e in ents:
        osint.assert_record_clean(e)  # must not raise
        assert "(SAMPLE)" in e["entity"]


def test_osint_rejected_example_is_rejected(osint):
    blob = json.loads(osint.SAMPLE_FILE.read_text(encoding="utf-8"))
    dirty = blob["rejected_examples"]
    assert len(dirty) == 1
    with pytest.raises(osint.EthicsViolation):
        osint.assert_record_clean(dirty[0])


@pytest.mark.parametrize("bad", [
    {"entity": "T", "ssn": "000-00-0000"},
    {"entity": "T", "dob": "1980-01-01"},
    {"entity": "T", "date_of_birth": "1980-01-01"},
    {"entity": "T", "drivers_license": "X123"},
    {"entity": "T", "home_address": "1 Main St"},
    {"entity": "T", "credit_card": "4111"},
    {"entity": "T", "ein": "12-3456789"},
    {"entity": "T", "tax_id": "12-3456789"},
    {"entity": "T", "personal_email": "a@b.com"},
    {"entity": "T", "cell": "555-0100"},
    {"entity": "T", "note": "from facebook profile"},
    {"entity": "T", "note": "pulled from spokeo"},
    {"entity": "T", "note": "scraped from the web"},
])
def test_osint_gate_rejects_each_banned_thing(osint, bad):
    with pytest.raises(osint.EthicsViolation):
        osint.assert_record_clean(bad)


def test_osint_gate_allows_clean_record(osint):
    osint.assert_record_clean({
        "entity": "Clean Sample LLC",
        "filings": [{"name": "Certificate of Formation"}],
        "registered_agent_public": "Agent LLC",
        "addresses_public": [{"value": "1 Main St, McAllen, TX"}],
    })


def test_osint_no_pii_keys_anywhere_in_loaded_data(osint):
    blob = json.loads(osint.SAMPLE_FILE.read_text(encoding="utf-8"))
    for rec in blob["entities"]:
        for key, _ in osint._walk_keys(rec):
            tokens = osint._key_tokens(key)
            for frag in osint._BANNED_KEY_FRAGMENTS:
                if "_" in frag:
                    assert frag not in key.lower().replace("-", "_"), key
                else:
                    assert frag not in tokens, key


def test_osint_query_filter(osint):
    assert len(osint.items(query="Valley Sun")) == 1
    assert len(osint.items(query="No Such Entity")) == 0


# ---------------------------------------------------------------------------
# 4. county_records event-type coverage + ranking.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def county():
    return load_module("county_records", "county_records/county_records.py")


def test_county_event_type_and_county_coverage(county):
    events = county.load_events()
    assert len(events) == 15
    types = {e["type"] for e in events}
    assert types == {"tax_delinquent", "constable_sale", "foreclosure_posting",
                     "county_auction", "commissioners_agenda"}
    counties = {e["county"] for e in events}
    assert {"Hidalgo", "Cameron", "Starr", "Willacy"} <= counties
    assert all("SAMPLE" in e["title"] for e in events)


def test_county_items_ranked_and_agenda_has_no_est_value(county):
    its = county.items()
    scores = [i["score"] for i in its]
    assert scores == sorted(scores, reverse=True)
    agenda = [i for i in its if i["event_type"] == "commissioners_agenda"]
    assert agenda and all(i["est_value"] is None for i in agenda)
    assets = [i for i in its if i["event_type"] != "commissioners_agenda"]
    assert all(isinstance(i["est_value"], (int, float)) and i["est_value"] >= 0
               for i in assets)


def test_county_murky_owner_escalates_risk(county):
    ev = {"type": "tax_delinquent", "county": "Hidalgo",
          "owner_status": "heirs / probate", "assessed_value": 100000,
          "amount_owed": 10000}
    assert county._risk(ev) == "HIGH"
    clean = dict(ev, owner_status="owner-occupied")
    assert county._risk(clean) == "MED"


# ---------------------------------------------------------------------------
# 5. local_econ three-lens scoring.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def econ():
    return load_module("local_econ", "local_econ/local_econ.py")


def test_local_econ_three_lens_weights(econ):
    sig = {"kind": "building_permit", "posted_date": "2026-11-16",
           "deadline": None, "dollar_amount": 100000, "county": "Hidalgo"}
    sc = econ._score_signal(sig)
    base = 62 + 3  # base 62 + <$1M dollar band +3; posted <=7d +6 -> 71
    assert sc["score"] == 71.0
    assert sc["lens"]["contractor_lead"] == round(71.0 * 0.95, 1)
    assert sc["lens"]["realestate_lift"] == round(71.0 * 0.65, 1)
    assert sc["lens"]["marketplace_demand"] == round(71.0 * 0.35, 1)
    assert sc["best_lens"] == "contractor_lead"


def test_local_econ_kind_and_city_coverage(econ):
    sigs = econ.load_signals()
    assert len(sigs) == 12
    kinds = {s["kind"] for s in sigs}
    assert {"building_permit", "business_opening", "public_bid",
            "road_project", "council_econdev", "grant"} <= kinds
    cities = {s["city"] for s in sigs}
    assert {"McAllen", "Edinburg", "Brownsville", "Harlingen"} <= cities
    assert all(s.get("source") == "sample" and s.get("real_source", "").startswith("https://")
               for s in sigs)
    its = econ.items()
    assert len(its) == 12
    assert all(set(it["opportunity_lens"]) ==
               {"contractor_lead", "realestate_lift", "marketplace_demand"}
               for it in its)


def test_local_econ_passed_deadline_penalized(econ):
    sig = {"kind": "public_bid", "posted_date": "2026-11-01",
           "deadline": "2026-11-02", "dollar_amount": 500000, "county": "Hidalgo"}
    sc = econ._score_signal(sig)
    assert sc["risk"] == "HIGH"  # deadline passed bumps risk
    assert sc["score"] < 78  # base 78 minus 25 stale penalty (+dollar/freshness)


# ---------------------------------------------------------------------------
# 6. recon_engine dedup.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def recon():
    return load_module("recon_engine", "recon_engine/recon_engine.py")


def test_recon_dedupe_keeps_freshest(recon):
    leads = [
        {"source": "tax_sale", "title": "Tax sale: 3BR ranch",
         "category": "real_estate", "price": 18000, "est_value": 145000,
         "posted_days_ago": 5, "location": "County", "url": ""},
        {"source": "tax_sale", "title": "  Tax Sale:  3BR ranch ",
         "category": "real_estate", "price": 18000, "est_value": 145000,
         "posted_days_ago": 1, "location": "County", "url": ""},
        {"source": "estate_sale", "title": "Estate tools",
         "category": "equipment", "price": 900, "est_value": 2600,
         "posted_days_ago": 0, "location": "Town", "url": ""},
    ]
    out = recon._dedupe_leads(leads)
    assert len(out) == 2
    kept = [l for l in out if "3BR" in l["title"]][0]
    assert kept["posted_days_ago"] == 1  # freshest copy kept


def test_recon_dedupe_tie_break_highest_est_value(recon):
    leads = [
        {"source": "surplus", "title": "Lot A", "category": "misc",
         "price": 100, "est_value": 200, "posted_days_ago": 2,
         "location": "", "url": ""},
        {"source": "surplus", "title": "Lot A", "category": "misc",
         "price": 100, "est_value": 500, "posted_days_ago": 2,
         "location": "", "url": ""},
    ]
    out = recon._dedupe_leads(leads)
    assert len(out) == 1 and out[0]["est_value"] == 500


def test_recon_scan_dedupes_via_input_file(recon, tmp_path):
    leads = [
        {"source": "tax_sale", "title": "Dup lead", "category": "real_estate",
         "price": 1000, "est_value": 5000, "posted_days_ago": 3,
         "location": "County", "url": ""},
        {"source": "tax_sale", "title": "Dup lead", "category": "real_estate",
         "price": 1000, "est_value": 5000, "posted_days_ago": 0,
         "location": "County", "url": ""},
        {"source": "surplus", "title": "Other lead", "category": "misc",
         "price": 100, "est_value": 300, "posted_days_ago": 1,
         "location": "City", "url": ""},
    ]
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "leads.json").write_text(json.dumps(leads))
    engine = recon.ReconEngine(base_dir=tmp_path)
    opps = engine.scan()
    assert len(opps) == 2
    assert {o.title for o in opps} == {"Dup lead", "Other lead"}


# ---------------------------------------------------------------------------
# 7. _boot regression: the three _lib modules import with no .pineapple_root
#    anywhere in the parent tree (workspace-relative _lib fallback).
# ---------------------------------------------------------------------------
BOOT_MODULES = [
    ("economic_checker", "economic_checker/economic_checker.py"),
    ("political_tracker", "political_tracker/political_tracker.py"),
    ("recon_engine", "recon_engine/recon_engine.py"),
]

BOOT_PROBE = """
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("IMPORT_OK", mod.__name__)
"""


@pytest.mark.parametrize("module_id,relpath", BOOT_MODULES)
def test_boot_import_without_pineapple_root(module_id, relpath, tmp_path):
    root = tmp_path / "noroot"
    moddir = root / module_id
    moddir.mkdir(parents=True)
    shutil.copy(WS / relpath, moddir / Path(relpath).name)
    shutil.copytree(WS / "_lib", root / "_lib")
    # No .pineapple_root anywhere under tmp_path (or /tmp); prove it.
    assert not list(tmp_path.rglob(".pineapple_root"))
    probe = tmp_path / "probe.py"
    probe.write_text(BOOT_PROBE)
    r = subprocess.run([str(VENV_PY), str(probe), str(moddir / Path(relpath).name)],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path))
    assert r.returncode == 0 and "IMPORT_OK" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("module_id,relpath", BOOT_MODULES)
def test_boot_fails_without_lib_or_marker(module_id, relpath, tmp_path):
    """Negative control: the ORIGINAL module (no fallback) must fail to
    import when neither a marker nor a _lib is in the parent tree — this
    proves the regression test above actually exercises the fix."""
    orig = Path("/home/hatch/workspace/pineapple/recovered/pineapple-os/"
                "04_INTELLIGENCE") / relpath
    moddir = tmp_path / "orig" / module_id
    moddir.mkdir(parents=True)
    shutil.copy(orig, moddir / Path(relpath).name)
    probe = tmp_path / "probe.py"
    probe.write_text(BOOT_PROBE)
    r = subprocess.run([str(VENV_PY), str(probe), str(moddir / Path(relpath).name)],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path))
    assert r.returncode != 0
    assert "ModuleNotFoundError" in r.stderr and "pineapple_intel" in r.stderr


def test_boot_scan_runs_without_marker(tmp_path):
    """End-to-end: recon_engine scans in a marker-free tree via the fallback."""
    root = tmp_path / "noroot2"
    moddir = root / "recon_engine"
    moddir.mkdir(parents=True)
    shutil.copy(WS / "recon_engine" / "recon_engine.py", moddir / "recon_engine.py")
    shutil.copytree(WS / "_lib", root / "_lib")
    probe = tmp_path / "probe_scan.py"
    probe.write_text("""
import importlib.util, sys, json
spec = importlib.util.spec_from_file_location("recon_engine", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules["recon_engine"] = mod
spec.loader.exec_module(mod)
opps = mod.ReconEngine().scan()
print("SCAN_OK", len(opps))
""")
    r = subprocess.run([str(VENV_PY), str(probe), str(moddir / "recon_engine.py")],
                       capture_output=True, text=True, timeout=60,
                       cwd=str(tmp_path))
    assert r.returncode == 0 and "SCAN_OK 5" in r.stdout, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# 8. Feed writer mapping (no network): schema-valid, warnings + provenance.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def writer():
    import intelligence_writer
    return intelligence_writer


def test_writer_maps_all_modules_schema_valid(writer):
    import jsonschema
    schema = json.loads((WS / "feed-service-copy" / "opportunity.schema.json")
                        .read_text(encoding="utf-8")) \
        if (WS / "feed-service-copy" / "opportunity.schema.json").exists() \
        else json.loads(Path("/home/hatch/workspace/pineapple/builds/"
                             "feed-dash/feed-service/opportunity.schema.json")
                        .read_text(encoding="utf-8"))
    collected = writer.collect_items()
    assert set(collected) == {m for m, _, _ in writer.MODULES}
    records = writer.map_all(collected)
    assert len(records) == 111
    for rec in records:
        jsonschema.validate(rec, schema)
        assert rec["provenance"]["data_status"] == "sample"
        assert rec["provenance"]["warning"]
        assert rec["risk_notes"] == rec["provenance"]["warning"]
        assert rec["approval_status"] == "PENDING"
        assert rec["id"].startswith("intel:")
    by_module = {}
    for rec in records:
        by_module[rec["provenance"]["module"]] = \
            by_module.get(rec["provenance"]["module"], 0) + 1
    assert by_module == {
        "cad_appraisal": 10, "code_violations": 15, "county_records": 15,
        "delinquent_tax": 14, "local_econ": 12, "osint": 6,
        "preforeclosure": 12, "utility_shutoffs": 12,
        "economic_checker": 6, "political_tracker": 4, "recon_engine": 5,
    }


def test_writer_warnings_intact_per_module(writer):
    collected = writer.collect_items()
    records = writer.map_all(collected)
    by_mod = {}
    for rec in records:
        by_mod.setdefault(rec["provenance"]["module"], []).append(rec)
    assert "not appraisals" in by_mod["cad_appraisal"][0]["risk_notes"]
    assert "not a legal standing determination" in by_mod["osint"][0]["risk_notes"]
    assert "no targeting of vulnerable individuals" in \
        by_mod["utility_shutoffs"][0]["risk_notes"]
    assert "Homeowner-respectful" in by_mod["preforeclosure"][0]["risk_notes"]
    assert all("SAMPLE" in r["risk_notes"] for r in records)


def test_writer_latlon_present_where_module_carries_it(writer):
    collected = writer.collect_items()
    records = writer.map_all(collected)
    by_mod = {}
    for rec in records:
        by_mod.setdefault(rec["provenance"]["module"], []).append(rec)
    assert all(r["provenance"]["lat"] is not None
               for r in by_mod["code_violations"])
    assert all(r["provenance"]["lat"] is not None
               for r in by_mod["cad_appraisal"])
    assert all(r["provenance"]["lat"] is not None
               for r in by_mod["county_records"])
    assert all(r["provenance"]["lat"] is not None
               for r in by_mod["local_econ"])


def test_writer_ids_unique_and_stable(writer):
    collected = writer.collect_items()
    records = writer.map_all(collected)
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))
    records2 = writer.map_all(writer.collect_items())
    assert [r["id"] for r in records2] == ids
