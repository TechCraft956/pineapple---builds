"""Feed service tests — run: .venv/bin/python -m pytest tests/ -v
Covers the brief's acceptance checks + GPT review patch list:
apps seed, radar fixture round-trip with schema validation on both ends,
unauthenticated POST rejected (401), duplicate POST idempotent, conflict
409, malformed record 422, pagination/filter, restart persistence,
concurrent writers, atomic-write integrity.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE))

TOKEN = "test-token-123"
TMP = tempfile.mkdtemp(prefix="feed-test-")
os.environ["FEED_DATA_DIR"] = TMP
os.environ["FEED_API_TOKEN"] = TOKEN

# Seed the tmp data dir with the recovered feed.json (copy of the original).
shutil.copy(SERVICE / "data" / "feed.json", Path(TMP) / "feed.json")

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402
import jsonschema  # noqa: E402

with open(SERVICE / "opportunity.schema.json", encoding="utf-8") as fh:
    SCHEMA = json.load(fh)

with open(SERVICE / "fixtures" / "radar_items_fixture.json", encoding="utf-8") as fh:
    FIXTURE = json.load(fh)

sys.path.insert(0, str(SERVICE / "writers"))
from patent_radar_writer import map_items  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_apps_returns_two_historical_apps():
    r = client.get("/api/feed/apps")
    assert r.status_code == 200
    ids = {a["app_id"] for a in r.json()["apps"]}
    assert ids == {"marketplace_scraper", "template_app"}
    by_id = {a["app_id"]: a for a in r.json()["apps"]}
    assert by_id["marketplace_scraper"]["app_name"] == "Marketplace Scraper"
    assert by_id["marketplace_scraper"]["status"] == "idle"
    assert by_id["marketplace_scraper"]["last_updated"].startswith("2026-04-17")


def test_roundtrip_radar_fixture():
    records = map_items(FIXTURE["items"], data_status="sample")
    for rec in records:  # schema validation on the writer side
        jsonschema.validate(rec, SCHEMA)
    r = client.post("/api/feed/items", json={"items": records}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert sorted(r.json()["inserted"]) == sorted(rec["id"] for rec in records)
    r = client.get("/api/feed/opportunities?type=patent_product")
    assert r.status_code == 200
    got = {i["id"]: i for i in r.json()["items"]}
    assert len(got) == 3
    for rec in records:  # schema validation on the reader side
        jsonschema.validate(got[rec["id"]], SCHEMA)
        assert got[rec["id"]] == rec  # round-trips unchanged in meaning
    # unknown-vs-zero preserved: the expiring sample keeps its flag
    assert got["radar:SAMPLE-0003"]["est_value_unknown"] is True
    assert got["radar:SAMPLE-0003"]["est_value"] == 0
    assert got["radar:SAMPLE-0001"]["est_value_unknown"] is False


def test_unauthenticated_post_rejected():
    records = map_items(FIXTURE["items"], data_status="sample")
    assert client.post("/api/feed/items", json={"items": records}).status_code == 401
    assert client.post("/api/feed/items", json={"items": records},
                       headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_duplicate_post_idempotent():
    records = map_items(FIXTURE["items"], data_status="sample")
    r = client.post("/api/feed/items", json={"items": records}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["inserted"] == []
    assert sorted(r.json()["duplicates"]) == sorted(rec["id"] for rec in records)


def test_conflict_same_id_different_payload_409():
    records = map_items(FIXTURE["items"], data_status="sample")
    changed = dict(records[0])
    changed["title"] = "A different title for the same id"
    r = client.post("/api/feed/items", json={"items": [changed]}, headers=AUTH)
    assert r.status_code == 409
    assert "radar:SAMPLE-0001" in r.json()["detail"]["conflicts"]


def test_malformed_record_422():
    bad = {"id": "bad:1", "type": "patent_product"}  # missing required fields
    r = client.post("/api/feed/items", json={"items": [bad]}, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["detail"]["validation_errors"][0]["id"] == "bad:1"


def test_app_status_post_roundtrip():
    r = client.post("/api/feed/apps/marketplace_scraper",
                    json={"app_name": "Marketplace Scraper", "status": "scanning",
                          "metrics": {"new_listings": 3}},
                    headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "scanning"
    r = client.get("/api/feed/apps")
    by_id = {a["app_id"]: a for a in r.json()["apps"]}
    assert by_id["marketplace_scraper"]["status"] == "scanning"
    assert by_id["template_app"]["status"] == "idle"  # other apps untouched
    assert client.post("/api/feed/apps/x", json={"status": "idle"}).status_code == 401


def test_pagination_and_filter():
    r = client.get("/api/feed/opportunities?limit=2&offset=0")
    assert r.status_code == 200 and len(r.json()["items"]) == 2
    assert r.json()["total"] == 3
    r = client.get("/api/feed/opportunities?type=resale_arbitrage")
    assert r.json()["total"] == 0


def test_restart_persistence():
    # A fresh client over the same on-disk data still sees the records.
    from app import app as app2
    client2 = TestClient(app2)
    r = client2.get("/api/feed/opportunities")
    assert r.json()["total"] == 3


def test_concurrent_writers_no_corruption():
    base = map_items(FIXTURE["items"], data_status="sample")
    results = []

    def post_one(n):
        rec = dict(base[0])
        rec = {**rec, "id": f"concurrent:{n}", "listing_key": f"concurrent:{n}"}
        results.append(client.post("/api/feed/items", json={"items": [rec]},
                                   headers=AUTH).status_code)

    threads = [threading.Thread(target=post_one, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [200] * 5
    r = client.get("/api/feed/opportunities?limit=200")
    assert r.status_code == 200
    assert len({i["id"] for i in r.json()["items"]}) == len(r.json()["items"])
    assert not list(Path(TMP).glob("*.tmp"))  # no stray temp files


def test_audit_log_written():
    audit = Path(TMP) / "audit.jsonl"
    assert audit.exists()
    lines = [json.loads(line) for line in audit.read_text().splitlines()]
    assert any(e.get("event") == "upsert" and e.get("inserted") for e in lines)
