#!/usr/bin/env python3
"""
County Records Radar  -  04_INTELLIGENCE

Surfaces high-ROI PUBLIC-RECORD events across the Rio Grande Valley and its
neighbor counties, then ranks them for the Pineapple decision engine:

    - tax_delinquent      delinquent tax rolls / struck-off resale lots
    - constable_sale      constable & sheriff tax-judgment sales
    - foreclosure_posting substitute-trustee / lien Notices of Sale (first Tuesday)
    - county_auction      county surplus / fleet / equipment auctions
    - commissioners_agenda commissioners court agendas signaling infra/zoning moves

Target counties:
    Core RGV   : Hidalgo, Cameron, Starr, Willacy
    Neighbors  : Brooks, Kenedy, Jim Hogg, Zapata

OFFLINE / SAMPLE MODE
    This module ships with realistic SAMPLE events in data/sample_events.json
    (clearly marked, fabricated). It never fetches live network data. To go live,
    wire the REAL sources documented in REAL_SOURCES below into _fetch_live()
    (kept as a stub) and feed the same record shape into rank/items.

------------------------------------------------------------------------------
REAL LIVE PUBLIC SOURCES  (for later wiring -- all official / public record)
------------------------------------------------------------------------------
Hidalgo County
  County Clerk public notices ....... https://www.hidalgocounty.us/162/County-Clerk
  Constable sales ................... https://www.hidalgocounty.us/1817/Constable-Sales
  Tax Office delinquent roll ........ https://www.hidalgocountytax.org/
  Commissioners Court agendas ....... https://www.hidalgocounty.us/AgendaCenter
Cameron County
  County Clerk ...................... https://www.cameroncountyclerk.com/
  Tax Office / struck-off resale .... https://www.cameroncountytax.com/
  Commissioners Court ............... https://www.cameroncounty.us/
Starr County ........................ https://www.co.starr.tx.us/
Willacy County ...................... https://www.co.willacy.tx.us/
Neighbor counties:
  Brooks ............................ https://www.co.brooks.tx.us/
  Jim Hogg .......................... (county clerk / road dept postings)
  Zapata ............................ https://www.co.zapata.tx.us/
  Kenedy ............................ (county clerk postings)
Statewide / aggregators (law firms that run TX tax sales -- public sale lists):
  Linebarger struck-off / resale .... https://actweb.acttax.com/
  MVBA tax sales .................... https://www.mvbalaw.com/tax-sales/
  Perdue Brandon tax sales .......... https://pbfcm.com/tax-sales/
County surplus auctions ............. https://www.publicsurplus.com/
Legal basis (struck-off / resale) ... TX Tax Code ch. 34, TX Local Gov Code 263
Foreclosure (first Tuesday sales) ... TX Property Code 51.002 (Notice of Sale)
------------------------------------------------------------------------------

Run:
    python county_records.py --selftest      # health check, exit 0 on success
    python county_records.py                 # print ranked radar
    python county_records.py --json          # dump ranked items() as JSON
    python county_records.py --publish       # write 00_PROCESSED/county_records_items.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths -- write ONLY inside this module folder or 00_PROCESSED.               #
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
SAMPLE_FILE = DATA_DIR / "sample_events.json"


def _find_root() -> Path | None:
    for a in [HERE, *HERE.parents]:
        if (a / ".pineapple_root").exists():
            return a
    return None


ROOT = _find_root()
PROCESSED = (ROOT / "00_PROCESSED") if ROOT else (HERE / "00_PROCESSED")
ALLOWED_WRITE_ROOTS = tuple(
    p.resolve() for p in {HERE, PROCESSED} if p is not None
)

CORE_COUNTIES = {"Hidalgo", "Cameron", "Starr", "Willacy"}
NEIGHBOR_COUNTIES = {"Brooks", "Kenedy", "Jim Hogg", "Zapata"}

# --------------------------------------------------------------------------- #
# Plugin descriptor consumed by the registry / decision engine.               #
# --------------------------------------------------------------------------- #
REAL_SOURCES = [
    "https://www.hidalgocounty.us/162/County-Clerk",
    "https://www.hidalgocounty.us/1817/Constable-Sales",
    "https://www.hidalgocountytax.org/",
    "https://www.hidalgocounty.us/AgendaCenter",
    "https://www.cameroncountyclerk.com/",
    "https://www.cameroncountytax.com/",
    "https://www.cameroncounty.us/",
    "https://www.co.starr.tx.us/",
    "https://www.co.willacy.tx.us/",
    "https://www.co.brooks.tx.us/",
    "https://www.co.zapata.tx.us/",
    "https://www.mvbalaw.com/tax-sales/",
    "https://pbfcm.com/tax-sales/",
    "https://www.publicsurplus.com/",
]

PLUGIN = {
    "id": "county_records",
    "name": "County Records Radar",
    "category": "ASSETS",
    "authority": "official public records (county clerk, tax office, constable, commissioners court)",
    "status": "sample",
    "inputs": ["data/sample_events.json"],
    "outputs": [
        "items() -> ranked list[dict] for the decision engine",
        "00_PROCESSED/county_records_items.json (on --publish)",
    ],
    "sources": REAL_SOURCES,
    "safety": (
        "READ-ONLY toward source records. Offline/sample mode -- no live fetch. "
        "Surfaces public-record leads only; does not file bids, contact owners, "
        "or take any legal action. Verify every record against the official "
        "source and consult counsel before acting. Tax/foreclosure sales carry "
        "title, redemption-period, and as-is risk."
    ),
}

# --------------------------------------------------------------------------- #
# Scoring                                                                      #
# --------------------------------------------------------------------------- #
# Base desirability of each event type for an asset-hunter (0-1).
TYPE_WEIGHT = {
    "tax_delinquent": 0.85,       # cheap basis, but redemption-period exposure
    "constable_sale": 0.80,       # firm sale date, tax-judgment titles
    "foreclosure_posting": 0.70,  # larger tickets, more competition
    "county_auction": 0.55,       # equipment/surplus, smaller upside
    "commissioners_agenda": 0.75,  # signal not asset; positions you ahead of moves
}

# Type-level risk floor; refined per-event below.
TYPE_RISK = {
    "tax_delinquent": "MED",
    "constable_sale": "MED",
    "foreclosure_posting": "HIGH",
    "county_auction": "LOW",
    "commissioners_agenda": "LOW",
}

CATEGORY_MAP = {
    "tax_delinquent": "ASSETS",
    "constable_sale": "ASSETS",
    "foreclosure_posting": "ASSETS",
    "county_auction": "ASSETS",
    "commissioners_agenda": "OPPORTUNITIES",
}


def _today() -> date:
    return date.today()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _equity_spread(ev: dict):
    """Estimated upside = assessed_value - what it takes to acquire.

    Acquisition cost approximated by minimum_bid if present, else amount_owed.
    Returns a non-negative number or None when value data is missing.
    """
    assessed = ev.get("assessed_value")
    if not isinstance(assessed, (int, float)) or assessed <= 0:
        return None
    cost = ev.get("minimum_bid")
    if not isinstance(cost, (int, float)) or cost <= 0:
        cost = ev.get("amount_owed")
    if not isinstance(cost, (int, float)) or cost <= 0:
        return None
    return max(0.0, float(assessed) - float(cost))


def _est_value(ev: dict):
    """Number fed to the decision engine as est_value.

    Asset events  -> estimated equity spread (assessed - acquisition cost).
    Agenda signals-> None (informational, no direct dollar figure).
    """
    if ev.get("type") == "commissioners_agenda":
        return None
    return _equity_spread(ev)


def _risk(ev: dict) -> str:
    risk = TYPE_RISK.get(ev.get("type"), "MED")
    # Escalate tax/constable risk when title is murky or owner-occupancy unclear.
    owner = (ev.get("owner_status") or "").lower()
    murky = any(w in owner for w in ("heir", "probate", "estate", "deceased", "multiple owners"))
    if murky and risk == "MED":
        risk = "HIGH"
    if murky and risk == "LOW":
        risk = "MED"
    # Big foreclosure tickets stay HIGH; small surplus stays LOW.
    spread = _equity_spread(ev)
    if ev.get("type") == "tax_delinquent" and spread and spread > 80000 and not murky:
        # large clean spread -> still MED, opportunity outweighs but flag stands
        risk = "MED"
    return risk


def _confidence(ev: dict) -> float:
    """How firm the lead is (0-1). Posted sale date + amounts = high."""
    c = 0.45
    if _parse_date(ev.get("auction_date")) or _parse_date(ev.get("meeting_date")):
        c += 0.20
    if isinstance(ev.get("assessed_value"), (int, float)):
        c += 0.10
    if isinstance(ev.get("minimum_bid"), (int, float)) or isinstance(ev.get("amount_owed"), (int, float)):
        c += 0.10
    if ev.get("case_or_notice_no"):
        c += 0.08
    if ev.get("county") in CORE_COUNTIES:
        c += 0.05
    # SAMPLE data is fabricated; cap so it never masquerades as a verified lead.
    return round(min(c, 0.85), 2)


def _urgency(ev: dict) -> float:
    """0-1: closer sale/meeting date = more urgent."""
    d = _parse_date(ev.get("auction_date")) or _parse_date(ev.get("meeting_date"))
    if not d:
        return 0.3
    days = (d - _today()).days
    if days < 0:
        return 0.0  # already passed
    if days <= 7:
        return 1.0
    if days <= 21:
        return 0.7
    if days <= 45:
        return 0.5
    return 0.35


def _score(ev: dict) -> float:
    """Composite 0-100 rank score: value spread x type x location x urgency x risk."""
    type_w = TYPE_WEIGHT.get(ev.get("type"), 0.5)
    loc_w = 1.0 if ev.get("county") in CORE_COUNTIES else (
        0.8 if ev.get("county") in NEIGHBOR_COUNTIES else 0.6)

    spread = _equity_spread(ev)
    # Normalize spread on a soft curve: $150k spread ~= full marks.
    if spread is None:
        # agenda / no-value events score on signal strength, not dollars
        kws = ev.get("agenda_keywords") or []
        signal_strength = min(1.0, 0.4 + 0.15 * len(kws))
        value_component = signal_strength
    else:
        value_component = min(1.0, spread / 150000.0)

    risk = _risk(ev)
    risk_mult = {"LOW": 1.0, "MED": 0.9, "HIGH": 0.78}.get(risk, 0.85)
    urgency = _urgency(ev)

    raw = (
        0.45 * value_component
        + 0.20 * type_w
        + 0.15 * loc_w
        + 0.20 * urgency
    ) * risk_mult
    return round(min(100.0, raw * 100.0), 1)


# --------------------------------------------------------------------------- #
# Data loading                                                                 #
# --------------------------------------------------------------------------- #
def load_events() -> list[dict]:
    """Load sample events (offline). Returns [] if the file is missing."""
    if not SAMPLE_FILE.exists():
        return []
    try:
        doc = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(doc, dict):
        return list(doc.get("events", []))
    if isinstance(doc, list):
        return doc
    return []


def _fetch_live(_county=None):  # pragma: no cover - intentional offline stub
    """STUB. Wire the REAL_SOURCES here when going live.

    Each source page is HTML / PDF of public notices. Suggested approach:
      1. fetch the county clerk / tax office / constable / agenda page
      2. parse postings into the same record shape as data/sample_events.json
      3. return list[dict]
    Kept disabled to honor the offline guarantee.
    """
    raise NotImplementedError(
        "Live fetch disabled (offline mode). Wire REAL_SOURCES into _fetch_live()."
    )


def _action(ev: dict) -> str:
    t = ev.get("type")
    cty = ev.get("county", "?")
    when = ev.get("auction_date") or ev.get("meeting_date") or "TBD"
    notice = ev.get("case_or_notice_no", "")
    if t == "tax_delinquent":
        return (f"Pull deed/title history & redemption status on {ev.get('parcel_account','parcel')} "
                f"({cty} CAD); confirm on official roll before any bid.")
    if t == "constable_sale":
        return (f"Register for {cty} constable sale on {when}; verify min bid "
                f"{ev.get('minimum_bid','?')} and title (case {notice}).")
    if t == "foreclosure_posting":
        return (f"Review Notice of Sale {notice}; sale {when} at courthouse steps. "
                f"Confirm lien position & payoff before attending.")
    if t == "county_auction":
        return (f"Inspect lot ({ev.get('lot_description','surplus')}); auction {when}. "
                f"Set max bid vs resale comps.")
    if t == "commissioners_agenda":
        kws = ", ".join(ev.get("agenda_keywords", [])) or ev.get("agenda_signal", "")
        return (f"Read {cty} commissioners agenda for {when}: {kws}. "
                f"Map affected parcels; position ahead of the vote.")
    return f"Review {cty} record {notice}."


# --------------------------------------------------------------------------- #
# Public contract: items()                                                      #
# --------------------------------------------------------------------------- #
def items() -> list[dict]:
    """Ranked list of decision-engine items.

    Each item has at least: title, category, source, action, est_value,
    risk, location, url, confidence. Sorted best-first by composite score.
    """
    events = load_events()
    out = []
    for ev in events:
        cty = ev.get("county", "?")
        score = _score(ev)
        risk = _risk(ev)
        loc = ev.get("address") or cty
        if ev.get("county"):
            loc = f"{loc} | {cty} County, TX"
        out.append({
            "title": ev.get("title", ev.get("id", "county record")),
            "category": CATEGORY_MAP.get(ev.get("type"), "ASSETS"),
            "source": "County Records Radar (SAMPLE)",
            "action": _action(ev),
            "est_value": _est_value(ev),
            "risk": risk,
            "location": loc,
            "url": ev.get("source_url", ""),
            "confidence": _confidence(ev),
            # extra fields (decision engine ignores unknowns, kept for richness)
            "score": score,
            "event_type": ev.get("type"),
            "county": cty,
            "auction_date": ev.get("auction_date") or ev.get("meeting_date"),
            "amount_owed": ev.get("amount_owed"),
            "assessed_value": ev.get("assessed_value"),
            "record_id": ev.get("id"),
            "is_sample": True,
        })
    out.sort(key=lambda x: (x["score"], x["est_value"] or 0), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Output / publish                                                              #
# --------------------------------------------------------------------------- #
def _assert_safe_write(p: Path):
    rp = p.resolve()
    if not any(str(rp).startswith(str(r)) for r in ALLOWED_WRITE_ROOTS):
        raise PermissionError(f"REFUSED write outside module/00_PROCESSED: {rp}")


def publish() -> Path:
    """Write ranked items to 00_PROCESSED for the decision engine to pick up."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED / "county_records_items.json"
    _assert_safe_write(out_path)
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugin": PLUGIN["id"],
        "status": PLUGIN["status"],
        "count": None,
        "items": items(),
    }
    payload["count"] = len(payload["items"])
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def render(rows: list[dict]) -> None:
    bar = "#" * 70
    print("\n" + bar)
    print("#  COUNTY RECORDS RADAR  -  RGV public-record opportunities  [SAMPLE]")
    print(bar)
    print(f"#  {len(rows)} events ranked. Verify on official source before acting.\n#")
    for i, r in enumerate(rows, 1):
        ev = f"${r['est_value']:,.0f}" if isinstance(r["est_value"], (int, float)) else "n/a"
        print(f"#  {i:2d}. [{r['score']:5.1f}] {r['risk']:4} {r['event_type']:<20} {r['title'][:42]}")
        print(f"#         {r['county']} County | est_value {ev} | conf {r['confidence']}")
        print(f"#         -> {r['action'][:88]}")
    print(bar)


# --------------------------------------------------------------------------- #
# Self-test                                                                     #
# --------------------------------------------------------------------------- #
def selftest() -> int:
    problems = []

    # 1. PLUGIN contract
    for key in ("id", "name", "category", "authority", "status", "inputs",
                "outputs", "sources", "safety"):
        if key not in PLUGIN:
            problems.append(f"PLUGIN missing key: {key}")
    if PLUGIN.get("status") != "sample":
        problems.append("PLUGIN.status must be 'sample'")
    if not PLUGIN.get("sources"):
        problems.append("PLUGIN.sources empty")

    # 2. Sample data present
    events = load_events()
    if len(events) < 12:
        problems.append(f"expected ~15 sample events, found {len(events)}")

    # 3. County coverage (core RGV)
    counties = {e.get("county") for e in events}
    missing_core = CORE_COUNTIES - counties
    if missing_core:
        problems.append(f"core counties not covered: {sorted(missing_core)}")

    # 4. Event-type coverage
    types = {e.get("type") for e in events}
    need_types = {"tax_delinquent", "constable_sale", "foreclosure_posting",
                  "county_auction", "commissioners_agenda"}
    missing_types = need_types - types
    if missing_types:
        problems.append(f"event types not covered: {sorted(missing_types)}")

    # 5. items() contract
    its = items()
    if not its:
        problems.append("items() returned empty")
    required = {"title", "category", "source", "action", "est_value",
                "risk", "location", "url", "confidence"}
    for it in its:
        missing = required - set(it)
        if missing:
            problems.append(f"item missing fields {missing}: {it.get('title')}")
            break
        if it["risk"] not in ("LOW", "MED", "HIGH"):
            problems.append(f"bad risk value: {it['risk']}")
            break
        if not (0.0 <= it["confidence"] <= 1.0):
            problems.append(f"confidence out of range: {it['confidence']}")
            break
        if it["est_value"] is not None and not isinstance(it["est_value"], (int, float)):
            problems.append(f"est_value not number/null: {it['est_value']}")
            break

    # 6. ranking sanity (descending score)
    scores = [it["score"] for it in its]
    if scores != sorted(scores, reverse=True):
        problems.append("items() not sorted by score descending")

    if problems:
        print("SELFTEST FAILED:")
        for p in problems:
            print("  - " + p)
        return 1

    print("County Records Radar selftest OK")
    print(f"  events loaded ...... {len(events)}")
    print(f"  ranked items ....... {len(its)}")
    print(f"  counties ........... {len(counties)} ({', '.join(sorted(c for c in counties if c))})")
    print(f"  event types ........ {len(types)}")
    print(f"  top lead ........... [{its[0]['score']}] {its[0]['title']} ({its[0]['county']})")
    top_val = its[0]["est_value"]
    print(f"  top est_value ...... " + (f"${top_val:,.0f}" if isinstance(top_val, (int, float)) else "n/a"))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="County Records Radar (RGV public records)")
    ap.add_argument("--selftest", action="store_true", help="run health check, exit 0 on success")
    ap.add_argument("--json", action="store_true", help="print ranked items() as JSON")
    ap.add_argument("--publish", action="store_true", help="write 00_PROCESSED/county_records_items.json")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    rows = items()
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        render(rows)

    if args.publish:
        path = publish()
        print(f"\nPublished {len(rows)} items -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
