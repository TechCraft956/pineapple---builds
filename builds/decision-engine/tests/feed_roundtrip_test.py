"""Feed round-trip test — Decision Engine brief -> shared feed.

Run with the feed service venv (fastapi + TestClient live there):
    ~/workspace/pineapple/builds/feed-dash/.venv/bin/python -m pytest \\
        tests/feed_roundtrip_test.py -v

Uses the REAL feed service app code (imported read-only from the feed-dash
build) with a throwaway FEED_DATA_DIR, so the feed-dash build is never
modified. No network: TestClient is in-process.

Checks the brief's Task 3 acceptance: engine run -> POST ->
GET /api/feed/opportunities shows the same top actions with quant preserved
(confidence == quant/100) and roi_estimate unknown (null in provenance,
est_value_unknown=true, est_value 0 — never a fabricated dollar value).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

WS = Path(__file__).resolve().parents[1]
FEED_SERVICE = Path("~/workspace/pineapple/builds/feed-dash/feed-service").expanduser()

TOKEN = "decision-engine-roundtrip-test-token"
TMP = tempfile.mkdtemp(prefix="de-feed-test-")
os.environ["FEED_DATA_DIR"] = TMP
os.environ["FEED_API_TOKEN"] = TOKEN

shutil.copy(FEED_SERVICE / "data" / "feed.json", Path(TMP) / "feed.json")

sys.path.insert(0, str(FEED_SERVICE))
sys.path.insert(0, str(WS / "writers"))

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
import jsonschema  # noqa: E402
from decision_brief_writer import map_items  # noqa: E402

with open(FEED_SERVICE / "opportunity.schema.json", encoding="utf-8") as fh:
    SCHEMA = json.load(fh)

with open(WS / "decision_brief.json", encoding="utf-8") as fh:
    BRIEF = json.load(fh)

client = TestClient(app)
AUTH = {"Authorization": "Bearer %s" % TOKEN}


def test_roundtrip_top_actions():
    records = map_items(BRIEF)
    assert records, "brief has no top actions to post"
    assert len(records) == len(BRIEF["top_actions"])
    for rec in records:  # writer-side schema validation
        jsonschema.validate(rec, SCHEMA)
    r = client.post("/api/feed/items", json={"items": records}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == [rec["id"] for rec in records]
    assert r.json()["duplicates"] == []

    got = client.get("/api/feed/opportunities", params={"limit": 200})
    assert got.status_code == 200
    by_id = {it["id"]: it for it in got.json()["items"]}
    for rec, action in zip(records, BRIEF["top_actions"]):
        back = by_id[rec["id"]]
        assert back["title"] == action["title"]
        # quant preserved as confidence
        assert back["confidence"] == pytest.approx(float(action["quant"]) / 100.0)
        # roi_estimate preserved exactly: null stays null, numbers stay numbers
        assert back["provenance"]["roi_estimate"] == action.get("roi_estimate")
        if action.get("roi_estimate") is None:
            assert back["provenance"]["roi_estimate"] is None
        assert back["est_value_unknown"] is True
        assert back["est_value"] == 0
        assert back["approval_status"] == "PENDING"
        assert back["provenance"]["quant"] == float(action["quant"])

    # re-post is idempotent: same ids, no new rows, no conflict
    r2 = client.post("/api/feed/items", json={"items": records}, headers=AUTH)
    assert r2.status_code == 200, r2.text
    assert r2.json()["inserted"] == []
    assert sorted(r2.json()["duplicates"]) == sorted(rec["id"] for rec in records)


def test_unauthenticated_post_rejected():
    records = map_items(BRIEF)[:1]
    r = client.post("/api/feed/items", json={"items": records})
    assert r.status_code == 401
