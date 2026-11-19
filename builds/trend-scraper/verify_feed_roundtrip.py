"""Live feed round-trip verification (not a test — a runbook script).

Starts the REAL shared-feed service from ~/workspace/pineapple/builds/
feed-dash/feed-service (read, never modified) on a scratch data dir with a
throwaway token, POSTs the fixture trend records via src/writers/feed_writer,
then GETs them back and checks they are unchanged in meaning. Prints a
pass/fail summary and exits non-zero on failure.

Usage (from the trend-scraper repo root):
  .venv/bin/python verify_feed_roundtrip.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEED_SERVICE = (Path.home() / "workspace" / "pineapple" / "builds"
                / "feed-dash" / "feed-service")
FEED_VENV_PY = (Path.home() / "workspace" / "pineapple" / "builds"
                / "feed-dash" / ".venv" / "bin" / "python")
PORT = 8101
TOKEN = "trend-verify-token-20261117"

sys.path.insert(0, str(ROOT))


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def main() -> int:
    import tempfile

    from src.models import TrendRecord
    from src.writers.feed_writer import map_records, post_records

    with tempfile.TemporaryDirectory(prefix="trend-feed-verify-") as tmp:
        env = dict(os.environ, FEED_DATA_DIR=tmp, FEED_API_TOKEN=TOKEN,
                   FEED_PORT=str(PORT))
        proc = subprocess.Popen(
            [str(FEED_VENV_PY), "-m", "uvicorn", "app:app",
             "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(FEED_SERVICE), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # Wait for the service.
            for _ in range(30):
                try:
                    status, _ = _get(f"http://127.0.0.1:{PORT}/health")
                    if status == 200:
                        break
                except Exception:
                    time.sleep(0.5)
            else:
                print("FAIL: feed service did not come up")
                return 1
            print("feed service up on", PORT)

            raw = json.loads((ROOT / "data" / "trend_records.json").read_text())
            records = [TrendRecord.from_dict(d) for d in raw]
            mapped = map_records(records)
            result = post_records(records, feed_url=f"http://127.0.0.1:{PORT}",
                                  token=TOKEN)
            print("POST /api/feed/items ->", result)
            assert result["status"] == 200, result
            assert len(result["body"]["inserted"]) == len(mapped), result

            # Unauthenticated POST must 401.
            try:
                _get(f"http://127.0.0.1:{PORT}/api/feed/opportunities")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{PORT}/api/feed/items",
                    data=json.dumps({"items": mapped[:1]}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10)
                print("FAIL: unauthenticated POST did not 401")
                return 1
            except urllib.error.HTTPError as exc:
                assert exc.code == 401, exc.code
                print("unauthenticated POST -> 401 (as required)")

            # GET back and compare meaning.
            _, body = _get(f"http://127.0.0.1:{PORT}/api/feed/opportunities"
                           f"?limit=200")
            by_id = {i["id"]: i for i in body["items"]}
            assert len(by_id) == len(mapped), (len(by_id), len(mapped))
            for rec in mapped:
                stored = by_id[rec["id"]]
                assert stored["title"] == rec["title"]
                assert stored["provenance"]["sellable"] == rec["provenance"]["sellable"]
                assert stored["provenance"]["licence_verbatim"] == rec["provenance"]["licence_verbatim"]
                assert stored["est_value_unknown"] is True
                assert stored["approval_status"] == "PENDING"
            print(f"ROUND-TRIP OK: {len(mapped)} records posted and "
                  "retrieved unchanged in meaning")
            return 0
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
