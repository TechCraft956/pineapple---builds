"""
writers/decision_brief_writer.py — Decision Engine brief -> Shared Feed adapter.

Takes decision_brief.json top actions and posts them to the feed as
normalized Opportunity Engine records (POST /api/feed/items).

Mapping (full rationale in FEED_MAPPING.md):
  * quant (0-100)        -> confidence (quant/100, clamped 0..1)
  * roi_estimate         -> provenance.roi_estimate, kept EXACTLY as the
                            brief has it: null stays null, never 0. Its units
                            are module-defined (some modules emit dollar-ish
                            values), so it is carried raw, never normalized
                            and never written into est_value.
  * est_value            -> 0 + est_value_unknown=true always: no dollar
                            realizable value exists for a ranked action.
  * purchase_price       -> 0: no purchase is modelled by a ranked action.
  * doctrine flags       -> evidence / risk_notes
  * approval_status      -> PENDING (a recommendation needs the owner)
  * type                 -> "other" (a ranked action is none of the
                            resale/patent/venture/trading types)

Usage:
  FEED_URL=http://127.0.0.1:8123 FEED_API_TOKEN=<token> \
    python writers/decision_brief_writer.py [decision_brief.json]

Stdlib only. No network except the single POST to the configured feed URL.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8100").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")

RISK_MAP = {"LOW": "low", "MED": "medium", "MEDIUM": "medium", "HIGH": "high"}


def _slug(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:n] or "action"


def map_item(item, brief_generated, index):
    """Map one brief top-action dict onto an Opportunity Engine record."""
    quant = float(item.get("quant", 0))
    roi = item.get("roi_estimate")  # None or a number — preserved exactly as-is
    doctrine = item.get("doctrine") or {}
    flags = list(doctrine.get("flags") or [])
    dims = item.get("dims") or {}
    date_part = (brief_generated or "")[:10].replace("-", "")
    record_id = "decision:%s:%02d:%s" % (date_part or "unknown", index + 1,
                                         _slug(item.get("title", "")))
    risk_notes = []
    if flags:
        risk_notes.append("Doctrine flags: " + "; ".join(flags))
    if item.get("stale"):
        risk_notes.append("Stale context: source %s days old; quant decayed -10."
                          % item.get("age_days"))
    if roi is None:
        risk_notes.append("roi_estimate unknown; recorded as null in provenance — "
                          "never 0. est_value is 0 with est_value_unknown=true "
                          "because no dollar realizable value exists for this action.")
    evidence = ("quant %.1f (raw score %s); dims %s"
                % (quant, item.get("raw_score"), json.dumps(dims, sort_keys=True)))
    if flags:
        evidence += "; doctrine: " + "; ".join(flags)
    return {
        "id": record_id,
        "listing_key": record_id,
        "type": "other",
        "title": item.get("title", ""),
        "source": "decision_engine:%s" % item.get("source", "unknown"),
        "collected_at": brief_generated,
        "collected_at_source": "sweep_ran_at",
        "purchase_price": 0,
        "est_value": 0,
        "est_value_unknown": True,
        "confidence": round(max(0.0, min(1.0, quant / 100.0)), 4),
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": evidence,
        "risk_level": RISK_MAP.get(str(item.get("risk", "")).upper()),
        "risk_notes": " ".join(risk_notes),
        "location": "",
        "next_action": item.get("action", ""),
        "provenance": {
            "writer": "decision_brief_writer v1",
            "brief_generated": brief_generated,
            "decision_category": item.get("category"),
            "decision_source": item.get("source"),
            "quant": quant,
            "raw_score": item.get("raw_score"),
            "dims": dims,
            "roi_estimate": roi,  # raw value exactly as the brief carries it; null stays null, never 0
            "doctrine": doctrine,
            "stale": bool(item.get("stale", False)),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def map_items(brief):
    generated = brief.get("generated")
    return [map_item(it, generated, i) for i, it in enumerate(brief.get("top_actions", []))]


def post_records(records):
    req = urllib.request.Request(
        "%s/api/feed/items" % FEED_URL,
        data=json.dumps({"items": records}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % FEED_API_TOKEN,
            "Idempotency-Key": "decision-%s" % datetime.now(timezone.utc).date().isoformat(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def main(argv):
    brief_path = argv[1] if len(argv) > 1 else "decision_brief.json"
    with open(brief_path, encoding="utf-8") as fh:
        brief = json.load(fh)
    records = map_items(brief)
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
