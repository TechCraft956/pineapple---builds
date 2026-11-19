"""verify_feed_roundtrip.py — live feed round-trip for OS modules (Task 5).

Starts a LOCAL COPY of the feed service (feed-service-copy/, never the
original, never deployed) on 127.0.0.1:8102 with a scratch data dir, posts
the sensor alerts (4) + simulator results (3) through writers/, then GETs
them back and verifies every record round-trips unchanged in meaning, with
the ANALYSIS ONLY warning verbatim on every simulator record and lat/lon +
rule on every sensor record. Also checks: unauthenticated POST -> 401,
re-post -> duplicates, 0 conflicts. Run from the os-modules workspace:
  python3 verify_feed_roundtrip.py
The bearer token is generated per run (or FEED_API_TOKEN env) and never
written to a file. The service process is terminated at the end; nothing
is deployed. Log: BUILD_LOG_feed_roundtrip.txt
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FEED = HERE / "feed-service-copy"
VENV_PY = Path("/home/hatch/workspace/pineapple/builds/feed-dash/.venv/bin/python")
TOKEN = os.environ.get("FEED_API_TOKEN") or secrets.token_urlsafe(24)
BASE = "http://127.0.0.1:8102"
DATA = FEED / "data-live-os-modules"
LOG = HERE / "BUILD_LOG_feed_roundtrip.txt"

DISCLAIMER = ("ANALYSIS ONLY - not financial/tax/lending/investment advice. "
              "Projections are deterministic functions of your assumptions; reality "
              "will differ. Validate params against real sources before acting.")


def log(*lines):
    with open(LOG, "a", encoding="utf-8") as fh:
        for ln in lines:
            print(ln)
            fh.write(ln + "\n")


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


def run_writer(name):
    env = dict(os.environ, FEED_URL=BASE, FEED_API_TOKEN=TOKEN)
    proc = subprocess.run(
        [sys.executable, str(HERE / "writers" / name)],
        capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def main():
    if LOG.exists():
        LOG.unlink()
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
            log("FAIL: feed service did not come up")
            return 1
        log("1. feed service up: GET /health -> 200")

        # Unauthenticated POST must be rejected.
        s, body = post_noauth("/api/feed/items", {"items": [{"id": "x"}]})
        assert s == 401, "unauthenticated POST returned %s, expected 401" % s
        log("2. unauthenticated POST /api/feed/items -> 401 (as expected)")

        total_posted = 0
        for writer, label in (("sensor_writer.py", "sensor alerts"),
                              ("simulator_writer.py", "simulator results")):
            rc, out, err = run_writer(writer)
            assert rc == 0, "%s failed rc=%d err=%s" % (writer, rc, err)
            body = json.loads(out[out.index("{"):])
            assert body.get("conflicts") == [], "conflicts: %s" % body
            n = len(body.get("inserted", []))
            total_posted += n
            log("3. writer %s (%s): POST -> 200, inserted %d: %s"
                % (writer, label, n, body["inserted"]))
            assert body.get("duplicates") == [], "unexpected duplicates on first post"

        # Read back and verify meaning.
        s, doc = get("/api/feed/opportunities?limit=200")
        assert s == 200
        items = doc["items"]
        sensors = [i for i in items if i["id"].startswith("sensor:")]
        sims = [i for i in items if i["id"].startswith("simulator:")]
        assert len(sensors) == 4, "expected 4 sensor records, got %d" % len(sensors)
        assert len(sims) == 3, "expected 3 simulator records, got %d" % len(sims)
        log("4. GET /api/feed/opportunities -> %d items (%d sensor + %d simulator)"
            % (len(items), len(sensors), len(sims)))
        for rec in sensors:
            prov = rec["provenance"]
            assert prov["lat"] and prov["lon"], "sensor record missing lat/lon"
            assert prov["rule"], "sensor record missing rule that fired"
            assert "SAMPLE telemetry" in prov["warning"]
        log("5. sensor records: lat/lon + firing rule + SAMPLE warning intact (4/4)")
        for rec in sims:
            assert DISCLAIMER in rec["evidence"], "warning missing from evidence: %s" % rec["id"]
            assert rec["risk_notes"] == DISCLAIMER, "risk_notes not verbatim: %s" % rec["id"]
            assert rec["provenance"]["warning"] == DISCLAIMER, "provenance warning not verbatim"
            assert rec["provenance"]["projected_net_worth_delta"]["1yr"] == rec["est_value"]
        log("6. simulator records: ANALYSIS ONLY warning verbatim in evidence + "
            "risk_notes + provenance (3/3); est_value == 1yr delta (3/3)")

        # Re-post must be idempotent: duplicates, 0 conflicts.
        for writer in ("sensor_writer.py", "simulator_writer.py"):
            rc, out, err = run_writer(writer)
            assert rc == 0, "re-post %s failed rc=%d" % (writer, rc)
            body = json.loads(out[out.index("{"):])
            assert body.get("inserted") == [], "re-post inserted: %s" % body
            assert body.get("conflicts") == [], "re-post conflicts: %s" % body
            log("7. re-post %s -> duplicates %d, conflicts 0 (idempotent)"
                % (writer, len(body.get("duplicates", []))))
        log("ROUND-TRIP PASSED: %d/%d records posted and read back unchanged in meaning"
            % (total_posted, total_posted))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(DATA, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
