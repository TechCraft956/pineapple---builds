"""verify_feed_roundtrip.py — live feed round-trip for GEOINT (Task 3).

Starts a LOCAL COPY of the feed service (feed-service-copy/, never the
original, never deployed) on 127.0.0.1:8101 with a scratch data dir, posts
the 12 sample parcels + the 20 live parcels through writers/geoint_writer.py,
then GETs them back and verifies every record round-trips with the flood
caveat + data_source intact. Run from the geoint workspace:
  ../.venv/bin/python verify_feed_roundtrip.py
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
FEED = HERE / "feed-service-copy"
VENV_PY = Path("/home/hatch/workspace/pineapple/builds/feed-dash/.venv/bin/python")
TOKEN = "geoint-test-token"
BASE = "http://127.0.0.1:8101"
DATA = FEED / "data-live-geoint"


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
    shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True)
    shutil.copy(FEED / "data" / "feed.json", DATA / "feed.json")
    env = dict(os.environ, FEED_DATA_DIR=str(DATA), FEED_API_TOKEN=TOKEN,
               FEED_PORT="8101")
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "uvicorn", "app:app",
         "--host", "127.0.0.1", "--port", "8101"],
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
        for label, args in (("sample (12)", []),
                            ("live (20)", ["--live", "live/all_live.geojson"])):
            w = subprocess.run(
                [str(VENV_PY), "writers/geoint_writer.py"] + args,
                cwd=HERE, env=wenv, capture_output=True, text=True)
            print("2. writer %s:\n%s" % (label, w.stdout.strip()))
            assert w.returncode == 0, w.stderr

        s, opps = get("/api/feed/opportunities?type=other&limit=200")
        assert s == 200, opps
        items = opps["items"]
        print("3. GET /api/feed/opportunities?type=other -> total %d" % opps["total"])
        assert opps["total"] == 32, opps["total"]
        by_source = {}
        for it in items:
            ds = it["provenance"]["data_source"]
            by_source[ds] = by_source.get(ds, 0) + 1
            assert "PLANNING SIGNAL ONLY" in it["risk_notes"], it["id"]
            assert it["provenance"]["warning"].startswith("PLANNING SIGNAL ONLY")
            assert it["provenance"]["parcel_id"]
            assert it["approval_status"] == "PENDING"
            assert it["id"].startswith("geoint:")
        print("4. all 32 records carry warning + data_source; by source:", by_source)
        assert by_source.get("sample") == 12, by_source
        assert by_source.get("starr_cad_live", 0) + by_source.get(
            "willacy_cad_live", 0) + by_source.get("stratmap_live", 0) == 20, by_source

        # Idempotent re-post of the sample batch: duplicates, not conflicts.
        w = subprocess.run([str(VENV_PY), "writers/geoint_writer.py"],
                           cwd=HERE, env=wenv, capture_output=True, text=True)
        body = json.loads(w.stdout[w.stdout.index("{"):])
        assert len(body.get("duplicates", [])) == 12, body
        assert body.get("conflicts") == [] and body.get("inserted") == [], body
        print("5. re-post sample batch -> duplicates 12, conflicts 0 (idempotent)")

        s, body = post_noauth("/api/feed/items", {"items": []})
        assert s == 401, (s, body)
        print("6. unauthenticated POST /api/feed/items -> 401 (rejected)")
        print("FEED ROUND-TRIP PASSED: 32/32 records posted and read back "
              "unchanged in meaning.")
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
