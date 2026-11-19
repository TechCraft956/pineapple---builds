#!/usr/bin/env python3
"""
Local Economic + Permits Radar  -  04_INTELLIGENCE/local_econ

Surfaces local economic signals for the Rio Grande Valley (Hidalgo, Cameron,
Starr, Willacy + neighbors) and scores each for OPPORTUNITY:

    - new business openings / EDC announcements   -> marketplace demand, services
    - building / construction permits             -> contractor leads, suppliers
    - road & infrastructure projects (TxDOT)      -> civil subs, RE corridor lift
    - public bids / RFPs (city, county, SAM.gov)  -> direct contractor leads
    - city council economic-development items      -> early-warning pipeline
    - grants (EDA, Texas Gov, grants.gov)          -> capital / positioning intel

Each signal is scored across three opportunity lenses:
    contractor_lead  - is there work to bid / a job pipeline?
    realestate_lift  - does this push nearby property values / demand?
    marketplace_demand - does this drive buying/selling of equipment, goods, services?

OUTPUT is shaped to feed the existing decision engine: items() returns a list of
dicts with title, category, source, action, est_value, risk, location, url,
confidence (+ extras the brief can use).

This module is OFFLINE and READ-ONLY. It ships REALISTIC SAMPLE data
(data/sample_signals.json, every record tagged status='sample') and documents the
REAL live source portals in PLUGIN['sources'] and in each sample record's
'real_source' field, ready to wire later.

Run:
    python local_econ.py --selftest          # health summary, exit 0 on success
    python local_econ.py                      # print scored radar to console
    python local_econ.py --json               # dump items() as JSON to stdout
    python local_econ.py --write              # write radar to 00_PROCESSED (and own folder)

Pure Python 3.11 stdlib only. UTF-8.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths  (write ONLY inside this folder or 00_PROCESSED)
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
SAMPLE_FILE = DATA_DIR / "sample_signals.json"
OUT_LOCAL = HERE / "output"


def _find_root() -> Path | None:
    for a in [HERE, *HERE.parents]:
        if (a / ".pineapple_root").exists():
            return a
    return None


ROOT = _find_root()
PROCESSED = (ROOT / "00_PROCESSED") if ROOT else None
ALLOWED_WRITE_ROOTS = tuple(
    p.resolve() for p in (HERE, PROCESSED) if p is not None
)


# ---------------------------------------------------------------------------
# Plugin manifest  (decision-engine contract)
# ---------------------------------------------------------------------------
PLUGIN = {
    "id": "local_econ",
    "name": "Local Economic + Permits Radar",
    "category": "MONEY",  # surfaces money/opportunity signals into the brief
    "authority": "04_INTELLIGENCE",
    "status": "sample",
    "inputs": [
        "data/sample_signals.json (offline sample; replace with live portal pulls)",
    ],
    "outputs": [
        "items() -> list[dict] scored opportunity signals",
        "00_PROCESSED/local_econ_radar.json (when --write)",
        "output/local_econ_radar.json (when --write)",
    ],
    # REAL live data sources to wire later (currently offline; sample data only)
    "sources": [
        "https://www.mcallen.net/departments/development-services",            # McAllen permits
        "https://www.mcallen.net/departments/purchasing/bids",                 # McAllen bids/RFPs
        "https://www.cityofedinburg.com/departments/planning_and_zoning",      # Edinburg permits
        "https://www.cityofedinburg.com/government/city_council/agendas_and_minutes",  # Edinburg agendas
        "https://www.cob.us/197/Building-Inspection",                          # Brownsville permits
        "https://www.cob.us/AgendaCenter",                                     # Brownsville agendas
        "https://www.myharlingen.us/179/Permits-Licensing",                    # Harlingen permits
        "https://www.cameroncountytx.gov/purchasing/",                         # Cameron County bids
        "https://www.txdot.gov/business/letting-bids.html",                    # TxDOT lettings
        "https://www.txdot.gov/about/districts/pharr.html",                    # TxDOT Pharr District
        "https://sam.gov/content/opportunities",                              # Federal bids/RFPs
        "https://www.grants.gov/search-grants",                               # Federal grants
        "https://www.eda.gov/funding",                                        # US EDA funding
        "https://gov.texas.gov/business/page/economic-development-finance",   # Texas econ-dev incentives
        "https://www.medc.org/news",                                          # McAllen EDC announcements
        "https://edinburgedc.com/news/",                                      # Edinburg EDC announcements
    ],
    "safety": (
        "OFFLINE, READ-ONLY. No live network calls. Ships clearly-labeled SAMPLE "
        "data only; writes ONLY inside this module folder or 00_PROCESSED. "
        "Dollar amounts/dates are illustrative. Verify every signal against the "
        "real source portal before acting. Public bids are competitive and have "
        "hard deadlines/bonding requirements - confirm on the official portal."
    ),
}


# ---------------------------------------------------------------------------
# Scoring model
# ---------------------------------------------------------------------------
# Base opportunity weight by signal kind, plus which lenses it lights up.
# weight 0-100 is the floor; deadline urgency + dollar size + freshness adjust it.
KIND_PROFILE = {
    # kind            : (base, contractor, realestate, marketplace, default_action)
    "building_permit": (62, 0.95, 0.65, 0.35,
                        "Reach out to GC/owner; line up sub-trade bid or supply quote"),
    "business_opening": (58, 0.40, 0.70, 0.85,
                        "Position services/inventory ahead of opening; track follow-on permits"),
    "public_bid":      (78, 1.00, 0.20, 0.30,
                        "Pull the solicitation, attend pre-bid, submit before deadline"),
    "federal_bid":     (74, 0.95, 0.15, 0.30,
                        "Check SAM.gov registration; assess IDIQ fit and submit"),
    "road_project":    (66, 0.85, 0.80, 0.45,
                        "Target prime/sub scope (concrete, striping, trucking); scout corridor RE"),
    "council_econdev": (54, 0.50, 0.75, 0.40,
                        "Watch the vote; if approved, get ahead of the permit/bid pipeline"),
    "grant":           (50, 0.25, 0.30, 0.40,
                        "Confirm eligibility; assess application ROI before the deadline"),
}

# Counties we care about (RGV core + neighbors). Outside = lower confidence.
CORE_COUNTIES = {"Hidalgo", "Cameron", "Starr", "Willacy"}
NEIGHBOR_COUNTIES = {"Brooks", "Kenedy", "Jim Hogg", "Zapata"}

# Map our internal category for the decision engine.
KIND_TO_CATEGORY = {
    "building_permit": "ASSETS",
    "business_opening": "OPPORTUNITIES",
    "public_bid": "OPPORTUNITIES",
    "federal_bid": "OPPORTUNITIES",
    "road_project": "ASSETS",
    "council_econdev": "OPPORTUNITIES",
    "grant": "OPPORTUNITIES",
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _days_until(d):
    if d is None:
        return None
    return (d - _today()).days


def _risk_for(kind, deadline_days, dollar):
    """Map a signal to LOW/MED/HIGH 'risk' (here: execution risk / competitiveness)."""
    # Bids are competitive + bonded => higher execution risk.
    if kind in ("public_bid", "federal_bid"):
        base = "HIGH" if (dollar or 0) >= 2_000_000 else "MED"
    elif kind in ("building_permit", "road_project"):
        base = "MED"
    else:
        base = "LOW"
    # A deadline already passed (sample staleness) bumps risk.
    if deadline_days is not None and deadline_days < 0:
        return "HIGH"
    return base


def _score_signal(sig: dict) -> dict:
    kind = sig.get("kind", "")
    base, w_con, w_re, w_mkt, default_action = KIND_PROFILE.get(
        kind, (40, 0.3, 0.3, 0.3, "Review signal against the source portal")
    )

    posted = _parse_date(sig.get("posted_date"))
    deadline = _parse_date(sig.get("deadline"))
    deadline_days = _days_until(deadline)
    dollar = sig.get("dollar_amount")
    county = sig.get("county", "")

    score = float(base)

    # --- dollar size: bigger projects => more opportunity, log-ish bands ---
    if isinstance(dollar, (int, float)) and dollar > 0:
        if dollar >= 25_000_000:
            score += 18
        elif dollar >= 10_000_000:
            score += 14
        elif dollar >= 5_000_000:
            score += 10
        elif dollar >= 1_000_000:
            score += 6
        else:
            score += 3

    # --- deadline urgency: open + soon = act now (good); passed = penalize ---
    if deadline_days is not None:
        if deadline_days < 0:
            score -= 25  # stale / missed
        elif deadline_days <= 7:
            score += 12  # urgent, actionable
        elif deadline_days <= 30:
            score += 8
        elif deadline_days <= 60:
            score += 4

    # --- freshness: recently posted ranks higher ---
    if posted is not None:
        age = (_today() - posted).days
        if age <= 7:
            score += 6
        elif age <= 21:
            score += 3
        elif age > 120:
            score -= 6

    # --- geography confidence ---
    if county in CORE_COUNTIES:
        geo_conf = 0.9
    elif county in NEIGHBOR_COUNTIES:
        geo_conf = 0.7
    else:
        geo_conf = 0.55
        score -= 4

    score = max(0.0, min(100.0, score))

    # Opportunity lens sub-scores (0-100), normalized by lens weight.
    lens = {
        "contractor_lead": round(score * w_con, 1),
        "realestate_lift": round(score * w_re, 1),
        "marketplace_demand": round(score * w_mkt, 1),
    }
    best_lens = max(lens, key=lens.get)

    risk = _risk_for(kind, deadline_days, dollar)

    # Confidence: sample data is inherently lower-confidence; blend geo + freshness.
    confidence = round(min(0.85, geo_conf * (0.95 if posted else 0.8)) *
                       (0.9 if sig.get("source") == "sample" else 1.0), 2)

    return {
        "score": round(score, 1),
        "lens": lens,
        "best_lens": best_lens,
        "risk": risk,
        "deadline_days": deadline_days,
        "geo_conf": geo_conf,
        "confidence": confidence,
        "default_action": default_action,
    }


def _action_text(sig: dict, sc: dict) -> str:
    parts = [sc["default_action"]]
    dd = sc["deadline_days"]
    if dd is not None:
        if dd < 0:
            parts.append("(deadline PASSED in sample - reconfirm live)")
        elif dd <= 7:
            parts.append(f"DEADLINE in {dd}d - act now")
        else:
            parts.append(f"deadline in {dd}d")
    parts.append(f"Verify: {sig.get('real_source','')}")
    return " | ".join(p for p in parts if p)


def load_signals(path: Path | None = None) -> list[dict]:
    p = path or SAMPLE_FILE
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return doc.get("signals", []) if isinstance(doc, dict) else (doc or [])


def items(path: Path | None = None) -> list[dict]:
    """Return scored opportunity signals shaped for the decision engine."""
    out = []
    for sig in load_signals(path):
        sc = _score_signal(sig)
        loc = ", ".join(x for x in (sig.get("city"), sig.get("county")) if x)
        if sig.get("county") in CORE_COUNTIES or sig.get("county") in NEIGHBOR_COUNTIES:
            loc += " County, TX" if not loc.endswith("TX") else ""
        item = {
            # ---- required decision-engine fields ----
            "title": sig.get("title", "(untitled signal)"),
            "category": KIND_TO_CATEGORY.get(sig.get("kind", ""), "OPPORTUNITIES"),
            "source": f"{PLUGIN['name']} [sample]",
            "action": _action_text(sig, sc),
            "est_value": sig.get("dollar_amount"),  # number or null
            "risk": sc["risk"],                      # LOW / MED / HIGH
            "location": loc or "Rio Grande Valley, TX",
            "url": sig.get("real_source", ""),
            "confidence": sc["confidence"],          # 0-1
            # ---- extras the brief / learning loop can use ----
            "id": sig.get("id"),
            "kind": sig.get("kind"),
            "agency": sig.get("agency"),
            "posted_date": sig.get("posted_date"),
            "deadline": sig.get("deadline"),
            "deadline_days": sc["deadline_days"],
            "opportunity_score": sc["score"],
            "opportunity_lens": sc["lens"],
            "best_lens": sc["best_lens"],
            "naics": sig.get("naics"),
            "summary": sig.get("summary"),
            "status": "sample",
        }
        out.append(item)
    out.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Output / rendering
# ---------------------------------------------------------------------------
def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_safe_write(p: Path):
    rp = p.resolve()
    if not any(str(rp).startswith(str(root)) for root in ALLOWED_WRITE_ROOTS):
        raise PermissionError(
            "REFUSED write outside module folder / 00_PROCESSED: %s" % rp
        )


def _payload() -> dict:
    its = items()
    return {
        "generated": _utcnow(),
        "module": PLUGIN["id"],
        "status": "sample",
        "region": "Rio Grande Valley, South Texas",
        "count": len(its),
        "sources": PLUGIN["sources"],
        "safety": PLUGIN["safety"],
        "items": its,
    }


def write_outputs() -> list[str]:
    payload = _payload()
    blob = json.dumps(payload, indent=2)
    written = []
    OUT_LOCAL.mkdir(parents=True, exist_ok=True)
    targets = [OUT_LOCAL / "local_econ_radar.json"]
    if PROCESSED is not None:
        PROCESSED.mkdir(parents=True, exist_ok=True)
        targets.append(PROCESSED / "local_econ_radar.json")
    for t in targets:
        _assert_safe_write(t)
        t.write_text(blob, encoding="utf-8")
        written.append(str(t))
    return written


def render(its: list[dict]):
    bar = "=" * 70
    print(bar)
    print("  LOCAL ECONOMIC + PERMITS RADAR  -  RGV  -  " + _utcnow())
    print("  [SAMPLE DATA - offline. Verify each on the official portal.]")
    print(bar)
    for i, it in enumerate(its, 1):
        val = ("$" + format(it["est_value"], ",.0f")) if isinstance(it["est_value"], (int, float)) else "n/a"
        print("  %2d. [%5.1f] %-13s %s" % (i, it["opportunity_score"], it["kind"], it["title"][:44]))
        print("        %-22s  %s  est=%s  risk=%s  conf=%.2f"
              % (it["location"][:22], it["best_lens"], val, it["risk"], it["confidence"]))
        print("        -> %s" % it["action"][:96])
    print(bar)
    print("  %d signals scored. Top lens spread:" % len(its))
    spread = {}
    for it in its:
        spread[it["best_lens"]] = spread.get(it["best_lens"], 0) + 1
    print("    " + "  ".join("%s=%d" % (k, v) for k, v in spread.items()))
    print(bar)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
def selftest() -> int:
    ok = True
    msgs = []

    sigs = load_signals()
    if len(sigs) < 10:
        ok = False
        msgs.append("FAIL: expected >=10 sample signals, got %d" % len(sigs))
    else:
        msgs.append("OK: loaded %d sample signals" % len(sigs))

    cities = {s.get("city") for s in sigs}
    want_cities = {"McAllen", "Edinburg", "Brownsville", "Harlingen"}
    missing = want_cities - cities
    if missing:
        ok = False
        msgs.append("FAIL: missing required cities: %s" % ", ".join(sorted(missing)))
    else:
        msgs.append("OK: McAllen/Edinburg/Brownsville/Harlingen all present")

    kinds = {s.get("kind") for s in sigs}
    want_kinds = {"building_permit", "business_opening", "public_bid",
                  "road_project", "council_econdev", "grant"}
    missing_k = want_kinds - kinds
    if missing_k:
        ok = False
        msgs.append("FAIL: missing signal kinds: %s" % ", ".join(sorted(missing_k)))
    else:
        msgs.append("OK: all 6 core signal kinds present (%d total kinds)" % len(kinds))

    its = items()
    if len(its) != len(sigs):
        ok = False
        msgs.append("FAIL: items() returned %d, expected %d" % (len(its), len(sigs)))

    required = {"title", "category", "source", "action", "est_value", "risk",
                "location", "url", "confidence"}
    for it in its:
        missing_f = required - set(it)
        if missing_f:
            ok = False
            msgs.append("FAIL: item '%s' missing fields: %s"
                        % (it.get("title", "?")[:30], ", ".join(sorted(missing_f))))
            break
        if it["risk"] not in ("LOW", "MED", "HIGH"):
            ok = False
            msgs.append("FAIL: bad risk '%s' on '%s'" % (it["risk"], it["title"][:30]))
            break
        if not (0.0 <= it["confidence"] <= 1.0):
            ok = False
            msgs.append("FAIL: confidence out of range on '%s'" % it["title"][:30])
            break
        if it["est_value"] is not None and not isinstance(it["est_value"], (int, float)):
            ok = False
            msgs.append("FAIL: est_value not number/null on '%s'" % it["title"][:30])
            break
    else:
        if its:
            msgs.append("OK: all %d items have required fields + valid risk/confidence/est_value" % len(its))

    # PLUGIN contract
    plugin_required = {"id", "name", "category", "authority", "status",
                       "inputs", "outputs", "sources", "safety"}
    if plugin_required - set(PLUGIN):
        ok = False
        msgs.append("FAIL: PLUGIN missing keys: %s" % ", ".join(sorted(plugin_required - set(PLUGIN))))
    elif PLUGIN["status"] != "sample":
        ok = False
        msgs.append("FAIL: PLUGIN.status must be 'sample'")
    elif not PLUGIN["sources"]:
        ok = False
        msgs.append("FAIL: PLUGIN.sources is empty (need real source URLs)")
    else:
        msgs.append("OK: PLUGIN contract valid (%d real sources documented)" % len(PLUGIN["sources"]))

    # Write-path safety check (no escape outside allowed roots)
    try:
        _assert_safe_write(HERE / "output" / "x.json")
        if PROCESSED is not None:
            _assert_safe_write(PROCESSED / "x.json")
        try:
            _assert_safe_write(HERE.parent / "escape.json")
            ok = False
            msgs.append("FAIL: write-guard did not block escape path")
        except PermissionError:
            msgs.append("OK: write-guard blocks paths outside module/00_PROCESSED")
    except PermissionError as e:
        ok = False
        msgs.append("FAIL: write-guard rejected an allowed path: %s" % e)

    print("local_econ selftest:")
    for m in msgs:
        print("  " + m)
    print("  RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Local Economic + Permits Radar (RGV)")
    ap.add_argument("--selftest", action="store_true", help="run health checks, exit 0 on success")
    ap.add_argument("--json", action="store_true", help="print items() as JSON")
    ap.add_argument("--write", action="store_true", help="write radar to output/ and 00_PROCESSED")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.json:
        print(json.dumps(items(), indent=2))
        return 0

    its = items()
    render(its)
    if args.write:
        for w in write_outputs():
            print("  wrote: %s" % w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
