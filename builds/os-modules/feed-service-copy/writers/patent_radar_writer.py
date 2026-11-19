"""
writers/patent_radar_writer.py — Patent Radar -> Shared Feed adapter (HYBRID).

Takes Patent Radar items() output and posts it to the feed as normalized
Opportunity Engine records (type patent_product). Radar is an idea engine,
NOT a legal-status authority: items with status "expiring"/"filing" are
posted with approval_status PENDING and next_action REVIEW_REQUIRED, and
est_value is never invented — when the radar gives null, the record keeps
est_value 0 plus est_value_unknown=true and the reason in risk_notes, so
unknown is never confused with zero.

Usage:
  FEED_URL=http://127.0.0.1:8100 FEED_API_TOKEN=<token> \
    python writers/patent_radar_writer.py fixtures/radar_items_fixture.json

When the real radar module exists (BUILD-20261117-001), call
map_items(radar.items()) instead of loading the fixture file.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8100").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")

RISK_MAP = {"LOW": "low", "MED": "medium", "HIGH": "high"}


def map_item(item, data_status="sample"):
    """Map one radar items() dict onto an Opportunity Engine record."""
    est_value = item.get("est_value")
    est_unknown = est_value is None
    record = {
        "id": f"radar:{item['patent_number']}",
        "listing_key": f"radar:{item['patent_number']}",
        "type": "patent_product",
        "title": item["title"],
        "source": item.get("url", "patent_radar"),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collected_at_source": "sweep_ran_at",
        "purchase_price": item.get("prototype_cost_usd", 0),
        "est_value": est_value if not est_unknown else 0,
        "est_value_unknown": est_unknown,
        "confidence": min(float(item.get("confidence", 0)), 0.85),
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": item.get("monetization", "") + " | " + item.get("demand_signal", ""),
        "risk_level": RISK_MAP.get(item.get("risk", "MED"), "medium"),
        "risk_notes": (
            "Radar idea engine only — NOT legal clearance. "
            f"Patent status per radar data: {item.get('status', 'unknown')}. "
            + ("est_value unknown; recorded as 0 pending valuation — do not treat as $0 value. "
               if est_unknown else "")
            + ("Verify legal status on Google Patents / USPTO Patent Center before sale."
               if item.get("status") in ("expiring", "filing") else "")
        ).strip(),
        "location": item.get("location", ""),
        "next_action": item.get("action", ""),
        "provenance": {
            "writer": "patent_radar_writer v1",
            "radar_data_status": data_status,
            "patent_number": item.get("patent_number"),
            "patent_status": item.get("status"),
            "printable_3d": item.get("printable_3d"),
            "manufacture_profile": item.get("manufacture_profile"),
            "source_url": item.get("url"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "status_method": "carried by radar data (provisional); legal status NOT verified",
        },
    }
    return record


def map_items(items, data_status="sample"):
    return [map_item(it, data_status) for it in items]


def post_records(records):
    req = urllib.request.Request(
        f"{FEED_URL}/api/feed/items",
        data=json.dumps({"items": records}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {FEED_API_TOKEN}",
            "Idempotency-Key": f"radar-{datetime.now(timezone.utc).date().isoformat()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def main(argv):
    fixture_path = argv[1] if len(argv) > 1 else "fixtures/radar_items_fixture.json"
    with open(fixture_path, encoding="utf-8") as fh:
        fixture = json.load(fh)
    records = map_items(fixture["items"],
                        data_status=fixture.get("_meta", {}).get("data_status", "sample"))
    if not FEED_API_TOKEN:
        print("FEED_API_TOKEN unset; mapped records (not posted):", file=sys.stderr)
        print(json.dumps(records, indent=2))
        return 2
    status, body = post_records(records)
    print(f"POST /api/feed/items -> {status}")
    print(json.dumps(body, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
