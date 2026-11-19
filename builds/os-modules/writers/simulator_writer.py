"""
writers/simulator_writer.py — Decision Simulator results -> Shared Feed adapter
(BUILD-20261117-006, Task 5).

Maps simulator.items() (ranked scenario recommendations, SAMPLE params) onto
Opportunity Engine records (type "other") and POSTs them to the shared feed.
EVERY record carries the simulator's ANALYSIS ONLY warning VERBATIM — in
evidence, risk_notes, and provenance.warning — because a projection is
analysis, never financial/tax/lending/investment advice.

Usage (against a LOCAL feed-service copy; never a deployed service):
  FEED_URL=http://127.0.0.1:8102 FEED_API_TOKEN=<token> \
    python writers/simulator_writer.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE / "06_DECISION" / "simulator"))

import simulator  # noqa: E402

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8102").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")

RISK_MAP = {"LOW": "low", "MED": "medium", "HIGH": "high"}
# Verbatim from simulator.DISCLAIMER — do not paraphrase.
ANALYSIS_ONLY = simulator.DISCLAIMER


def map_item(item):
    """Map one simulator.items() dict onto an Opportunity Engine record."""
    delta = item.get("projected_net_worth_delta", {})
    record = {
        "id": "simulator:%s" % item["scenario"],
        "listing_key": "simulator:%s" % item["scenario"],
        "type": "other",
        "title": item["title"],
        "source": "simulator:%s (End-State Decision Simulator, SAMPLE)" % item["scenario"],
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collected_at_source": "sweep_ran_at",
        # est_value = projected 1yr net-worth delta (signed; may be negative).
        "purchase_price": 0,
        "est_value": float(item.get("est_value") or 0),
        "confidence": float(item.get("confidence", 0.55)),
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": (
            "%s Projected net-worth delta: 1mo %+.2f, 1yr %+.2f, 5yr %+.2f USD. "
            "Risk %s. Bottleneck: %s"
            % (ANALYSIS_ONLY, delta.get("1mo", 0), delta.get("1yr", 0),
               delta.get("5yr", 0), item.get("risk"), item.get("bottleneck"))
        ),
        "risk_level": RISK_MAP.get(item.get("risk", "MED"), "medium"),
        "risk_notes": ANALYSIS_ONLY,
        "location": item.get("location", "Rio Grande Valley, TX"),
        "next_action": item.get("action", ""),
        "provenance": {
            "writer": "simulator_writer v1",
            "scenario": item["scenario"],
            "projected_net_worth_delta": delta,
            "bottleneck": item.get("bottleneck"),
            "warning": ANALYSIS_ONLY,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    return record


def map_items(items):
    return [map_item(it) for it in items]


def post_records(records):
    req = urllib.request.Request(
        "%s/api/feed/items" % FEED_URL,
        data=json.dumps({"items": records}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % FEED_API_TOKEN,
            "Idempotency-Key": "os-modules-simulator-%s" % datetime.now(timezone.utc).date().isoformat(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def main(argv):
    items = simulator.items()
    records = map_items(items)
    if not FEED_API_TOKEN:
        print("FEED_API_TOKEN unset; mapped records (not posted):", file=sys.stderr)
        print(json.dumps(records, indent=2))
        return 2
    status, body = post_records(records)
    print("POST /api/feed/items -> %s" % status)
    print(json.dumps(body, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
