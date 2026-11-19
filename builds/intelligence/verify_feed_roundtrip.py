"""verify_feed_roundtrip.py — live feed round-trip for 04_INTELLIGENCE.

Starts a LOCAL COPY of the feed service (feed-service-copy/, never the
original, never deployed) on 127.0.0.1:8102 with a scratch data dir, posts
all eleven modules' items through writers/intelligence_writer.py, then
GETs them back and verifies every record round-trips with sample provenance
+ its module warning intact. Run from the intelligence workspace:
  ../feed-dash/.venv/bin/python verify_feed_roundtrip.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FEED_SRC = Path("/home/hatch/workspace/pineapple/builds/feed-dash/feed-service")
FEED = HERE / "feed-service-copy"
VENV_PY = Path("/home/hatch/workspace/pineapple/builds/feed-dash/.venv/bin/python")
TOKEN = "intel-test-token"
BASE = "http://127.0.0.1:8102"
DATA = FEED / "data-live-intel"


def get(path):
    with urllib.request.urlopen(
            urllib.request.Request(BASE + path), timeout=10) as r:
        return r.status, json.loads(r.read())


def post_noauth(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    if FEED.exists():
        shutil.rmtree(FEED)
    shutil.copytree(FEED_SRC, FEED, ignore=shutil.ignore_patterns(
        "__pycache__", "data-live", "data-live-*"))
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    shutil.copy(FEED / "data" / "feed.json", DATA / "feed.json")
    env = dict(os.environ, FEED_DATA_DIR=str(DATA), FEED_API_TOKEN=TOKEN,
               FEED_PORT="8102")
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "app:app",
         "--host", "127.0.0.1", "--port", "8102"],
        cwd=FEED, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(30):
            try:
                s, _ = get("/health")
                if s == 200:
                    break
            except Exception:
                time.sleep(0.5)
        else:
            print("FAIL: feed service did not come up")
            return 1
        print("1. feed service up: GET /health -> 200")

        wenv = dict(os.environ, FEED_URL=BASE, FEED_API_TOKEN=TOKEN)
        w = subprocess.run(
            [str(VENV_PY), "writers/intelligence_writer.py"],
            cwd=HERE, env=wenv, capture_output=True, text=True)
        print("2. writer:\n%s" % w.stdout.strip())
        assert w.returncode == 0, w.stderr

        s, opps = get("/api/feed/opportunities?type=other&limit=200")
        assert s == 200, opps
        items = opps["items"]
        print("3. GET /api/feed/opportunities?type=other -> total %d" % opps["total"])

        expected = {
            "cad_appraisal": 10, "code_violations": 15, "county_records": 15,
            "delinquent_tax": 14, "local_econ": 12, "osint": 6,
            "preforeclosure": 12, "utility_shutoffs": 12,
            "economic_checker": 6, "political_tracker": 4, "recon_engine": 5,
        }
        total_expected = sum(expected.values())
        assert opps["total"] == total_expected, (
            "expected %d, got %d" % (total_expected, opps["total"]))
        by_module = {}
        for it in items:
            mod = it["provenance"]["module"]
            by_module[mod] = by_module.get(mod, 0) + 1
            assert it["provenance"]["data_status"] == "sample", it["id"]
            assert it["provenance"]["warning"], it["id"]
            assert it["risk_notes"] == it["provenance"]["warning"], it["id"]
            assert it["approval_status"] == "PENDING", it["id"]
            assert it["id"].startswith("intel:"), it["id"]
            assert it["evidence_quality"] == "estimate", it["id"]
        assert by_module == expected, by_module
        print("4. all %d records carry sample provenance + warning intact; "
              "per-module counts match: %s" % (total_expected, by_module))

        # Spot-checks: module-specific warnings + lat/lon survive.
        by_id = {it["id"]: it for it in items}
        cad = [it for it in items if it["provenance"]["module"] == "cad_appraisal"][0]
        assert "not appraisals" in cad["risk_notes"], cad["id"]
        assert cad["provenance"]["lat"] is not None, cad["id"]
        osint = [it for it in items if it["provenance"]["module"] == "osint"][0]
        assert "not a legal standing determination" in osint["risk_notes"], osint["id"]
        util = [it for it in items if it["provenance"]["module"] == "utility_shutoffs"][0]
        assert "no targeting of vulnerable individuals" in util["risk_notes"], util["id"]
        pre = [it for it in items if it["provenance"]["module"] == "preforeclosure"][0]
        assert "Homeowner-respectful" in pre["risk_notes"], pre["id"]
        agenda = by_id.get("intel:county_records:sample-evt-013")
        assert agenda is not None and agenda["est_value_unknown"] is True, agenda
        print("5. warning spot-checks pass (cad/osint/utility/preforeclosure); "
              "agenda record est_value_unknown=True; cad lat/lon present")

        # Idempotent re-post: duplicates, not conflicts.
        w = subprocess.run(
            [str(VENV_PY), "writers/intelligence_writer.py"],
            cwd=HERE, env=wenv, capture_output=True, text=True)
        body = json.loads(w.stdout[w.stdout.index("{"):])
        assert len(body.get("duplicates", [])) == total_expected, body
        assert body.get("conflicts") == [] and body.get("inserted") == [], body
        print("6. re-post all batches -> duplicates %d, conflicts 0 (idempotent)"
              % total_expected)

        s, body = post_noauth("/api/feed/items", {"items": []})
        assert s == 401, (s, body)
        print("7. unauthenticated POST /api/feed/items -> 401 (rejected)")
        print("FEED ROUND-TRIP PASSED: %d/%d records posted and read back "
              "unchanged in meaning." % (total_expected, total_expected))
        return 0
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        if "Traceback" in (out or ""):
            print("--- service log ---\n" + out)


if __name__ == "__main__":
    raise SystemExit(main())
