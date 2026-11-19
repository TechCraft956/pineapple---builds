"""Feed round-trip test (brief #3 task 2/5): trend records POST to the REAL
shared-feed service and come back from GET /api/feed/opportunities
unchanged in meaning.

Runs the feed service in-process via fastapi TestClient (no network, no
deployed service). FEED_DATA_DIR points at a tmp dir; the feed-dash
workspace is read, never modified. If the feed service is absent, the
test fails loudly (not skipped) — the round-trip is an acceptance check.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FEED_SERVICE = Path.home() / "workspace" / "pineapple" / "builds" / "feed-dash" / "feed-service"
FEED_SCHEMA = FEED_SERVICE / "opportunity.schema.json"

from src.models import TrendRecord  # noqa: E402
from src.writers.feed_writer import map_records  # noqa: E402


@pytest.fixture()
def feed_client(tmp_path, monkeypatch):
    assert FEED_SERVICE.exists(), f"feed service missing: {FEED_SERVICE}"
    monkeypatch.setenv("FEED_DATA_DIR", str(tmp_path / "feed-data"))
    monkeypatch.setenv("FEED_API_TOKEN", "test-token-trend-scraper")
    sys.path.insert(0, str(FEED_SERVICE))
    import importlib

    import app as feed_app
    importlib.reload(feed_app)
    from fastapi.testclient import TestClient

    with TestClient(feed_app.app) as client:
        yield client
    sys.path.remove(str(FEED_SERVICE))


def _fixture_records():
    from src.processors.paste_parser import parse_pasted_text
    from src.scrapers import printables_scraper as prs

    fx = ROOT / "tests" / "fixtures"
    recs = parse_pasted_text(
        (fx / "thingiverse_paste_2026-11-17.txt").read_text(), source="thingiverse")
    recs = recs[:3]
    model = prs.parse_model_page_html(
        (fx / "printables_model_2026-11-17.html").read_text(),
        url="https://www.printables.com/model/589261-honeycomb-wall-miniature-paint-holder-citadel-vall")
    recs.append(model)
    return recs


def test_feed_round_trip(feed_client):
    import jsonschema

    schema = json.loads(FEED_SCHEMA.read_text())
    recs = _fixture_records()
    mapped = map_records(recs)
    for rec in mapped:
        jsonschema.validate(rec, schema)  # schema-valid before POST

    resp = feed_client.post(
        "/api/feed/items", json={"items": mapped},
        headers={"Authorization": "Bearer test-token-trend-scraper"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["inserted"]) == len(mapped)

    # Round-trip: every posted id is retrievable, meaning unchanged.
    all_items = feed_client.get("/api/feed/opportunities",
                                params={"limit": 200}).json()["items"]
    by_id = {i["id"]: i for i in all_items}
    for rec in mapped:
        stored = by_id[rec["id"]]
        assert stored["title"] == rec["title"]
        assert stored["provenance"]["sellable"] == rec["provenance"]["sellable"]
        assert stored["provenance"]["licence_verbatim"] == rec["provenance"]["licence_verbatim"]
        assert stored["est_value_unknown"] is True
        assert stored["approval_status"] == "PENDING"


def test_feed_rejects_unauthenticated_post(feed_client):
    recs = map_records(_fixture_records()[:1])
    resp = feed_client.post("/api/feed/items", json={"items": recs})
    assert resp.status_code == 401


def test_feed_duplicate_post_is_idempotent(feed_client):
    recs = map_records(_fixture_records()[:1])
    headers = {"Authorization": "Bearer test-token-trend-scraper"}
    first = feed_client.post("/api/feed/items", json={"items": recs},
                             headers=headers)
    assert first.status_code == 200
    second = feed_client.post("/api/feed/items", json={"items": recs},
                              headers=headers)
    assert second.status_code == 200
    assert second.json()["duplicates"] == [recs[0]["id"]]
