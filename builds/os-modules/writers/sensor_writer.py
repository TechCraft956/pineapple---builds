"""
writers/sensor_writer.py — Sensor alerts -> Shared Feed adapter (BUILD-20261117-006, Task 5).

Maps sensor_ingest.items() (active household alerts, SAMPLE telemetry) onto
Opportunity Engine records (type "other") and POSTs them to the shared feed.
Every record carries lat/lon, the alert rule that fired, and SAMPLE provenance
— these are fabricated-telemetry alerts, never real events.

Usage (against a LOCAL feed-service copy; never a deployed service):
  FEED_URL=http://127.0.0.1:8102 FEED_API_TOKEN=<token> \
    python writers/sensor_writer.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE / "09_SENSORS"))

import sensor_ingest  # noqa: E402

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8102").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")

RISK_MAP = {"LOW": "low", "MED": "medium", "HIGH": "high"}
SAMPLE_WARNING = ("SAMPLE telemetry — fabricated household sensor data, not a "
                  "real event. Do not treat as a real alert.")


def map_item(item):
    """Map one sensor_ingest items() dict onto an Opportunity Engine record."""
    rule = next((r for r in
                 sensor_ingest.load_devices()[item["device_id"]]["alert_rules"]
                 if r.get("metric") == item["metric"]), {})
    record = {
        "id": "sensor:%s:%s" % (item["device_id"], item["metric"]),
        "listing_key": "sensor:%s:%s" % (item["device_id"], item["metric"]),
        "type": "other",
        "title": item["title"],
        "source": "sensors:%s (ESP32/IoT sensor layer, SAMPLE)" % item["device_id"],
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collected_at_source": "sweep_ran_at",
        # Sensor alerts carry no dollar value; schema requires a number.
        "purchase_price": 0,
        "est_value": 0,
        "est_value_unknown": True,
        "confidence": float(item.get("confidence", 0.5)),
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": (
            "%s. Device %s (%s) at %s, lat %.4f lon %.4f. Latest reading: "
            "%s = %s at %s. Severity %s."
            % (item["title"], item["device_id"], item["sensor_type"],
               item["location"], item["lat"], item["lon"],
               item["metric"], item["value"], item["ts"], item["severity"])
        ),
        "risk_level": RISK_MAP.get(item.get("risk", "MED"), "medium"),
        "risk_notes": SAMPLE_WARNING,
        "location": item.get("location", ""),
        "next_action": item.get("action", ""),
        "provenance": {
            "writer": "sensor_writer v1",
            "device_id": item["device_id"],
            "sensor_type": item["sensor_type"],
            "metric": item["metric"],
            "value": item["value"],
            "ts": item["ts"],
            "severity": item["severity"],
            "rule": rule,
            "lat": item["lat"],
            "lon": item["lon"],
            "warning": SAMPLE_WARNING,
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
            "Idempotency-Key": "os-modules-sensors-%s" % datetime.now(timezone.utc).date().isoformat(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def main(argv):
    items = sensor_ingest.items()
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
