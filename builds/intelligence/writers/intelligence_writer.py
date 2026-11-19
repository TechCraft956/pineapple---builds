"""
writers/intelligence_writer.py — 04_INTELLIGENCE -> Shared Feed adapter.

Takes every module's items() (or, for the three IntelModule-based ones,
scan() Opportunities) and posts them to the feed as normalized Opportunity
Engine records (type "other"). Every record carries data_status "sample",
the module's warning intact, lat/lon in provenance where the module
carries it, and the real-source portal URL for the live path.

Usage (against a LOCAL feed-service copy; never a deployed service):
  FEED_URL=http://127.0.0.1:8102 FEED_API_TOKEN=<token> \
    python writers/intelligence_writer.py

Without FEED_API_TOKEN it maps records and prints them (no post).
"""
import importlib.util
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE / "_lib"))

FEED_URL = os.environ.get("FEED_URL", "http://127.0.0.1:8102").rstrip("/")
FEED_API_TOKEN = os.environ.get("FEED_API_TOKEN", "")

SAMPLE_WARNING = (
    "SAMPLE data — fabricated for development/testing only; verify against "
    "the official source before acting."
)
CAD_WARNING = (
    "Planning signal only: CAD market values are planning signals, not "
    "appraisals. Verify against the live CAD before any outreach or offer. "
    + SAMPLE_WARNING
)
OSINT_WARNING = (
    "Public-record snapshot only — not a legal standing determination. "
    "Verify every field against the official source before acting. "
    + SAMPLE_WARNING
)
UTILITY_WARNING = (
    "Property-condition signal only — no targeting of vulnerable individuals. "
    + SAMPLE_WARNING
)
PREFORECLOSURE_WARNING = (
    "Homeowner-respectful outreach only; verify title and sale status "
    "against the official record before any contact. " + SAMPLE_WARNING
)

WARNINGS = {
    "cad_appraisal": CAD_WARNING,
    "osint": OSINT_WARNING,
    "utility_shutoffs": UTILITY_WARNING,
    "preforeclosure": PREFORECLOSURE_WARNING,
}

RISK_MAP = {"LOW": "low", "MED": "medium", "MEDIUM": "medium", "HIGH": "high"}

# (module_id, module file, loader kind)
MODULES = [
    ("cad_appraisal", "cad_appraisal/cad_appraisal.py", "items"),
    ("code_violations", "code_violations/code_violations.py", "items"),
    ("county_records", "county_records/county_records.py", "items"),
    ("delinquent_tax", "delinquent_tax/delinquent_tax.py", "items"),
    ("local_econ", "local_econ/local_econ.py", "items"),
    ("osint", "osint/osint_public.py", "items"),
    ("preforeclosure", "preforeclosure/preforeclosure.py", "items"),
    ("utility_shutoffs", "utility_shutoffs/utility_shutoffs.py", "items"),
    ("economic_checker", "economic_checker/economic_checker.py", "scan"),
    ("political_tracker", "political_tracker/political_tracker.py", "scan"),
    ("recon_engine", "recon_engine/recon_engine.py", "scan"),
]

_SCAN_CLASSES = {
    "economic_checker": "EconomicChecker",
    "political_tracker": "PoliticalTracker",
    "recon_engine": "ReconEngine",
}


def _load_module(module_id, relpath):
    path = WORKSPACE / relpath
    spec = importlib.util.spec_from_file_location(
        "intel_%s" % module_id, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["intel_%s" % module_id] = mod
    spec.loader.exec_module(mod)
    return mod


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:80] or "item"


def _latlon_for(module_id, mod, item):
    """Best lat/lon for an item: direct fields, else look the record up."""
    if isinstance(item.get("lat"), (int, float)) and isinstance(item.get("lon"), (int, float)):
        return item["lat"], item["lon"]
    try:
        if module_id == "cad_appraisal":
            for p in mod.load_parcels():
                if p.get("account") == item.get("account"):
                    return p.get("lat"), p.get("lon")
        elif module_id == "county_records":
            for ev in mod.load_events():
                if ev.get("id") == item.get("record_id"):
                    return ev.get("lat"), ev.get("lon")
        elif module_id == "local_econ":
            for s in mod.load_signals():
                if s.get("id") == item.get("id"):
                    return s.get("lat"), s.get("lon")
    except Exception:
        pass
    return None, None


def _stable_key(module_id, item):
    if module_id == "cad_appraisal" and item.get("account"):
        return "account-%s" % _slug(item["account"])
    if module_id == "county_records" and item.get("record_id"):
        return _slug(item["record_id"])
    if module_id == "local_econ" and item.get("id"):
        return _slug(item["id"])
    if module_id == "osint" and item.get("dossier", {}).get("entity"):
        return _slug(item["dossier"]["entity"])
    return _slug("%s-%s" % (item.get("title", ""), item.get("location", "")))


def collect_items():
    """Return {module_id: [item, ...]} for all eleven modules."""
    out = {}
    for module_id, relpath, kind in MODULES:
        mod = _load_module(module_id, relpath)
        if kind == "items":
            out[module_id] = list(mod.items())
        else:
            cls = getattr(mod, _SCAN_CLASSES[module_id])
            opps = cls().scan()
            converted = []
            for o in opps:
                d = o.to_dict()
                converted.append({
                    "title": d["title"],
                    "category": "intelligence",
                    "source": cls.module_name,
                    "action": d["action"],
                    "est_value": d.get("roi_estimate"),
                    "risk": d.get("risk", "UNKNOWN"),
                    "location": d.get("fields", {}).get("location", "") or "Rio Grande Valley, TX",
                    "url": d.get("fields", {}).get("url", "") or "",
                    "confidence": round(min(max(float(d.get("score", 0)) / 100.0, 0.0), 1.0), 2),
                    "score": d.get("score"),
                    "signals": d.get("signals", []),
                    "fields": d.get("fields", {}),
                })
            out[module_id] = converted
    return out


def map_item(module_id, item, mod=None):
    """Map one module item onto an Opportunity Engine record."""
    if mod is None:
        relpath = dict((m, r) for m, r, _ in MODULES)[module_id]
        mod = _load_module(module_id, relpath)
    warning = WARNINGS.get(module_id, SAMPLE_WARNING)
    est = item.get("est_value")
    est_num = est if isinstance(est, (int, float)) else 0
    conf = item.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) else 0.5
    conf = min(max(conf, 0.0), 1.0)
    lat, lon = _latlon_for(module_id, mod, item)
    url = item.get("url") or ""
    extra = {k: v for k, v in item.items()
             if k in ("flags", "primary_flag", "under_assessed_pct",
                      "years_owned", "event_type", "county", "score",
                      "kind", "best_lens", "opportunity_score", "status",
                      "violation", "owner_type", "years_delinquent",
                      "days_to_sale", "stage", "utility", "vacancy",
                      "dossier", "fields", "signals")}
    provenance = {
        "writer": "intelligence_writer v1",
        "module": module_id,
        "data_status": "sample",
        "warning": warning,
        "lat": lat,
        "lon": lon,
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    provenance.update(extra)
    return {
        "id": "intel:%s:%s" % (module_id, _stable_key(module_id, item)),
        "listing_key": "intel:%s:%s" % (module_id, _stable_key(module_id, item)),
        "type": "other",
        "title": item.get("title", "(untitled)"),
        "source": "intel:%s (SAMPLE — %s)" % (
            module_id, getattr(mod, "PLUGIN", {}).get("name", module_id)),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "collected_at_source": "sweep_ran_at",
        "purchase_price": est_num,
        "est_value": est_num,
        "est_value_unknown": not isinstance(est, (int, float)),
        "confidence": conf,
        "approval_status": "PENDING",
        "evidence_quality": "estimate",
        "evidence": (
            "Module %s (SAMPLE). %s Risk %s, confidence %.2f."
            % (module_id, item.get("action", "")[:200],
               item.get("risk"), conf)
        ),
        "risk_level": RISK_MAP.get(str(item.get("risk", "")).upper()),
        "risk_notes": warning,
        "location": item.get("location", "") or "Rio Grande Valley, TX",
        "next_action": item.get("action", ""),
        "provenance": provenance,
    }


def map_all(collected=None):
    if collected is None:
        collected = collect_items()
    records = []
    for module_id, items in collected.items():
        relpath = dict((m, r) for m, r, _ in MODULES)[module_id]
        mod = _load_module(module_id, relpath)
        records.extend(map_item(module_id, it, mod) for it in items)
    return records


def post_records(records):
    req = urllib.request.Request(
        "%s/api/feed/items" % FEED_URL,
        data=json.dumps({"items": records}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % FEED_API_TOKEN,
            "Idempotency-Key": "intel-%s" % datetime.now(timezone.utc).date().isoformat(),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def main():
    collected = collect_items()
    for module_id, items in collected.items():
        print("%s: %d items" % (module_id, len(items)))
    records = map_all(collected)
    print("total records mapped: %d" % len(records))
    if not FEED_API_TOKEN:
        print("FEED_API_TOKEN unset; mapped records (not posted):", file=sys.stderr)
        print(json.dumps(records, indent=2))
        return 2
    status, body = post_records(records)
    print("POST /api/feed/items -> %s" % status)
    print(json.dumps(body, indent=2))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
