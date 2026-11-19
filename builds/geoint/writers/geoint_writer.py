"""
writers/geoint_writer.py — TerraRecon -> Shared Feed adapter.

Takes gis_parcels.items() output (sample or live) and posts it to the feed
as normalized Opportunity Engine records (type "other"). Every record
carries the planning-signal warning and its data_source — a parcel is a
planning signal, NEVER authoritative title, valuation, or flood
determination.

Usage (against a LOCAL feed-service copy; never a deployed service):
  FEED_URL=http://127.0.0.1:8101 FEED_API_TOKEN=<token> \
    python writers/geoint_writer.py [--items-json PATH] [--live PATH]

Default input is the sample module's items(); --live takes a live canonical
GeoJSON (adapters/run_live.py output) and scores it through the module.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))

import gis_parcels  # noqa: E402

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8101").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")

RISK_MAP = {"LOW": "low", "MED": "medium", "HIGH": "high"}
PLANNING_WARNING = gis_parcels.PLANNING_WARNING


def map_item(item):
    """Map one gis_parcels items() dict onto an Opportunity Engine record."""
    data_source = item.get("data_source", "sample")
    zone = item.get("flood_zone")
    method = item.get("flood_join_method")
    caveat = item.get("flood_caveat")
    est_value = item.get("est_value")
    record = {
        "id": "geoint:%s" % item["parcel_id"],
        "listing_key": "geoint:%s" % item["parcel_id"],
        "type": "other",
        "title": item["title"],
        "source": "geoint:%s (TerraRecon RGV parcels + FEMA NFHL)" % data_source,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collected_at_source": "sweep_ran_at",
        "purchase_price": est_value if isinstance(est_value, (int, float)) else 0,
        "est_value": est_value if isinstance(est_value, (int, float)) else 0,
        "est_value_unknown": not isinstance(est_value, (int, float)),
        "confidence": float(item.get("confidence", 0.45)),
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": (
            "FEMA flood zone %s (risk %s, discount applied in opportunity_score %.2f). "
            "Flood join method: %s. County: %s. Zoning: %s."
            % (zone, item.get("risk"), item.get("opportunity_score"),
               method or "sample data — no live join", item.get("location"),
               item.get("zoning"))
        ),
        "risk_level": RISK_MAP.get(item.get("risk", "MED"), "medium"),
        "risk_notes": (
            PLANNING_WARNING + " "
            + ("Flood caveat: %s. " % caveat if caveat else "")
            + "Verify owner, value, and FEMA zone against county AD records "
              "and FEMA NFHL before any offer."
        ).strip(),
        "location": item.get("location", ""),
        "next_action": item.get("action", ""),
        "provenance": {
            "writer": "geoint_writer v1",
            "parcel_id": item.get("parcel_id"),
            "flood_zone": zone,
            "flood_join_method": method,
            "flood_caveat": caveat,
            "data_source": data_source,
            "zoning": item.get("zoning"),
            "warning": PLANNING_WARNING,
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
            "Idempotency-Key": "geoint-%s" % datetime.now(timezone.utc).date().isoformat(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def load_items(live_path=None):
    if live_path:
        return gis_parcels.items(path=Path(live_path))
    return gis_parcels.items()


def main(argv):
    live_path = None
    if "--live" in argv:
        live_path = argv[argv.index("--live") + 1]
    items = load_items(live_path)
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
