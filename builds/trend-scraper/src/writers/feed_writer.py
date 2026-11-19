"""Shared-feed writer: TrendRecord -> Opportunity Engine record (brief #2).

Maps onto the feed's opportunity schema v0.2 (POST /api/feed/items).
Follows the patent_radar_writer.py pattern from the feed-dash build:
- est_value is never invented: resale price unknown => est_value 0 plus
  est_value_unknown=true (unknown is never confused with $0).
- approval_status PENDING + next_action REVIEW_REQUIRED: a trend lead is
  not a listing decision, and licence clearance must be verified on the
  source page before any sale.
- No licence clearance is claimed here: risk_notes states the record is
  NOT legal clearance.

Usage:
  FEED_URL=http://127.0.0.1:8100 FEED_API_TOKEN=<token> \
    python -m src.writers.feed_writer data/trend_records.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8100").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:80] or "untitled"


def map_record(rec, data_status: str = "fixture") -> dict:
    """Map one TrendRecord (or dict) onto a feed opportunity record."""
    d = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
    rec_id = f"trend:{d['source']}:{_slug(d['title'])}"
    licence = d.get("licence")
    record = {
        "id": rec_id,
        "listing_key": rec_id,
        "type": "sellable_print",
        "title": d["title"],
        "source": d.get("url") or d["source"],
        "collected_at": d.get("collected_at_utc")
                        or datetime.now(timezone.utc).isoformat(),
        "collected_at_source": "sweep_ran_at",
        "purchase_price": 0,
        "est_value": 0,
        "est_value_unknown": True,
        "confidence": min(float(d.get("confidence", 0.5)), 0.85),
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": (
            f"likes={d.get('likes')} downloads={d.get('downloads')} "
            f"remixes={d.get('remixes')} spike={d.get('spike')} "
            f"licence={licence!r} filament_fit={d.get('filament_fit')}"
        ),
        "risk_level": "medium" if d.get("sellable") else "high",
        "risk_notes": (
            f"Sellable: {d.get('sellable')} ({d.get('sellable_reason')}). "
            "Trend lead only — NOT legal clearance; verify the licence on "
            "the source page and check sold comps before listing. "
            "Filament fit is a heuristic, not a print guarantee."
        ),
        "costs": {"transport": 0, "fees": 0, "repairs": 0, "other": 0},
        "next_action": "REVIEW_REQUIRED",
        "provenance": {
            "writer": "trend_feed_writer v1",
            "trend_data_status": data_status,
            "trend_source": d["source"],
            "licence_verbatim": licence,
            "likes": d.get("likes"),
            "downloads": d.get("downloads"),
            "remixes": d.get("remixes"),
            "spike": d.get("spike"),
            "filament_fit": d.get("filament_fit"),
            "sellable": d.get("sellable"),
            "sellable_reason": d.get("sellable_reason"),
            "source_url": d.get("url"),
        },
    }
    return record


def map_records(records, data_status: str = "fixture") -> list[dict]:
    return [map_record(r, data_status) for r in records]


def post_records(records, feed_url: str | None = None,
                 token: str | None = None,
                 data_status: str = "fixture") -> dict:
    """POST mapped records to the feed. Returns the parsed response body."""
    url = (feed_url or FEED_URL).rstrip("/")
    auth = token if token is not None else FEED_API_TOKEN
    if not auth:
        raise RuntimeError("FEED_API_TOKEN unset; cannot POST to the feed")
    payload = {"items": map_records(records, data_status)}
    req = urllib.request.Request(
        f"{url}/api/feed/items",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth}",
            "Idempotency-Key": f"trend-{datetime.now(timezone.utc).date().isoformat()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return {"status": resp.status, "body": json.loads(resp.read())}


def main(argv) -> int:
    if len(argv) < 2:
        print("usage: python -m src.writers.feed_writer <trend_records.json>",
              file=sys.stderr)
        return 2
    from src.models import TrendRecord

    with open(argv[1], encoding="utf-8") as fh:
        raw = json.load(fh)
    records = [TrendRecord.from_dict(d) for d in raw]
    result = post_records(records)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
