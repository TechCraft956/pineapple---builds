"""Live verification: start the feed service on a scratch data dir, run the
radar writer against it, then simulate the dashboard's poll loop — poll,
change one app-status record via the API, poll again and confirm the change
is visible on the next poll with no rebuild/refresh. Run from feed-service/:
  FEED_API_TOKEN=live-test-token ../.venv/bin/python verify_live.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TOKEN = os.environ.get("FEED_API_TOKEN", "live-test-token")
BASE = "http://127.0.0.1:8100"
HERE = Path(__file__).parent
DATA = HERE / "data-live"
shutil.rmtree(DATA, ignore_errors=True)
DATA.mkdir()
shutil.copy(HERE / "data" / "feed.json", DATA / "feed.json")

env = dict(os.environ, FEED_DATA_DIR=str(DATA), FEED_API_TOKEN=TOKEN,
           FEED_CORS_ORIGINS="http://localhost:3000", FEED_PORT="8100")
proc = subprocess.Popen(
    [str(HERE.parent / ".venv" / "bin" / "python"), "-m", "uvicorn",
     "app:app", "--host", "127.0.0.1", "--port", "8100"],
    cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    def get(path, headers=None):
        with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=headers or {}), timeout=10) as r:
            return r.status, json.loads(r.read())

    def post(path, body, token=True):
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {TOKEN}"
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    for _ in range(30):
        try:
            s, _ = get("/health")
            if s == 200:
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("FAIL: service did not come up"); sys.exit(1)
    print("1. service up: GET /health -> 200")

    s, apps = get("/api/feed/apps")
    ids = sorted(a["app_id"] for a in apps["apps"])
    assert ids == ["marketplace_scraper", "template_app"], ids
    print("2. GET /api/feed/apps -> 200, two historical apps:", ids)

    # Writer round-trip against the LIVE service (not TestClient).
    wenv = dict(os.environ, FEED_URL=BASE, FEED_API_TOKEN=TOKEN)
    w = subprocess.run([str(HERE.parent / ".venv" / "bin" / "python"),
                        "writers/patent_radar_writer.py",
                        "fixtures/radar_items_fixture.json"],
                       cwd=HERE, env=wenv, capture_output=True, text=True)
    print("3. writer output:\n" + w.stdout.strip())
    assert w.returncode == 0, w.stderr
    s, opps = get("/api/feed/opportunities?type=patent_product")
    assert s == 200 and opps["total"] == 3, opps
    print("4. GET /api/feed/opportunities?type=patent_product -> total 3, "
          "ids:", sorted(i["id"] for i in opps["items"]))

    s, body = post("/api/feed/items", {"items": []}, token=False)
    assert s == 401, (s, body)
    print("5. unauthenticated POST /api/feed/items -> 401 (rejected)")

    # Dashboard poll simulation: poll, change one record, poll again.
    s, before = get("/api/feed/apps")
    before_status = {a["app_id"]: a["status"] for a in before["apps"]}
    print("6. poll 1 (dashboard view):", before_status)
    s, upd = post("/api/feed/apps/template_app",
                  {"app_name": "Template App", "status": "running",
                   "metrics": {"items_checked": 20, "items_matched": 14}})
    assert s == 200, upd
    s, after = get("/api/feed/apps")
    after_status = {a["app_id"]: a["status"] for a in after["apps"]}
    assert after_status["template_app"] == "running"
    assert after_status["marketplace_scraper"] == before_status["marketplace_scraper"]
    print("7. poll 2 after one record changed via API:", after_status)
    print("LIVE VERIFICATION PASSED: change visible on next poll, no rebuild.")
finally:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    if "Traceback" in (out or ""):
        print("--- service log ---\n" + out)
