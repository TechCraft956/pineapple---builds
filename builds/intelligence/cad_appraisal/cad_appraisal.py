#!/usr/bin/env python3
"""
CAD Appraisal  —  04_INTELLIGENCE / cad_appraisal
County Appraisal District (CAD = County Appraisal District, NOT computer-aided design)
property intelligence for the Rio Grande Valley.

Given a parcel/account, returns:
    owner, situs address, market value, land/improvement split,
    year built, acreage, and a computed EQUITY-vs-COMPS signal.

items() flags candidates for the real-estate radar:
    - UNDER-ASSESSED   (CAD market value sits below comp-implied value -> instant equity)
    - HIGH-EQUITY      (large land+improvement value, low/older basis -> room to deal)
    - LONG-OWNED       (held many years -> motivated/tired landlord, low loan balance likely)
    - ESTATE / TRUST   (probate-adjacent owner names -> motivated heirs)

These items are shaped to feed the existing Decision Engine (decision_engine.py),
which expects per-item: title, category, source, action, est_value, risk, location,
url, confidence (plus extras it ignores).

Run:
    python cad_appraisal.py                 # print flagged radar candidates (JSON)
    python cad_appraisal.py --account P504217   # full record for one account
    python cad_appraisal.py --list          # list all sample accounts
    python cad_appraisal.py --selftest      # health summary, exit 0 on success

Data:
    data/sample_parcels.json  (~12 RGV parcels, Hidalgo + Cameron, clearly SAMPLE)

------------------------------------------------------------------------------
REAL LIVE SOURCES  (offline here — wire these in for production; all public):
------------------------------------------------------------------------------
  Hidalgo County Appraisal District (HCAD)
    - Public property search (esearch): https://esearch.hidalgoad.org/
    - Main site / data & forms:         https://www.hidalgoad.org/
    - Texas open-records / data export:  request via HCAD; many TX CADs publish
      a yearly appraisal roll / "data download" (fixed-width or CSV).
  Cameron County Appraisal District (CCAD)
    - Public property search (esearch): https://esearch.cameroncad.org/
    - Main site:                         https://www.cameroncad.org/
  Starr County AD:    https://www.starrcad.org/        (Starr County)
  Willacy County AD:  https://willacycad.org/          (Willacy County)
  Neighbors: Brooks CAD, Kenedy CAD, Jim Hogg CAD, Zapata CAD (county-named CADs)
  Statewide context:
    - Texas Comptroller PTAD (Property Tax Assistance Div):
      https://comptroller.texas.gov/taxes/property-tax/
    - Texas appraisal data portal (some CADs use True Automation / TrueProdigy esearch).
  Wiring note: esearch portals expose per-account detail pages; some CADs offer a
  bulk roll export. Scrape per-account detail or load the yearly export into
  data/parcels.json with the SAME schema as data/sample_parcels.json, then this
  module works unchanged (set PLUGIN['status'] = 'live').
------------------------------------------------------------------------------
Pure Python 3.11 stdlib only. Read-only. Writes only inside this folder / 00_PROCESSED.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "data" / "sample_parcels.json"


# ----------------------------------------------------------------------------
# PLUGIN contract (read by the Pineapple registry / decision engine)
# ----------------------------------------------------------------------------
PLUGIN = {
    "id": "cad_appraisal",
    "name": "CAD Appraisal (County Appraisal District) Intelligence",
    "category": "ASSETS",
    "authority": "Hidalgo County AD + Cameron County AD (RGV) public property records",
    "status": "sample",  # flip to "live" once data/parcels.json is wired to esearch/roll exports
    "inputs": [
        "parcel/account id (e.g. Hidalgo PID 'P504217' or Cameron 'NN-NNNN-NNNN-NNNN-NN')",
        "data/sample_parcels.json (CAD-shaped property records)",
    ],
    "outputs": [
        "per-parcel record: owner, situs, market_value, land/improvement split, "
        "year_built, acreage, equity_vs_comps signal",
        "items(): flagged under-assessed / high-equity / long-owned radar candidates",
    ],
    "sources": [
        "https://esearch.hidalgoad.org/",
        "https://www.hidalgoad.org/",
        "https://esearch.cameroncad.org/",
        "https://www.cameroncad.org/",
        "https://www.starrcad.org/",
        "https://willacycad.org/",
        "https://comptroller.texas.gov/taxes/property-tax/",
    ],
    "safety": (
        "READ-ONLY. Public appraisal records only. SAMPLE data is synthetic and marked "
        "'(sample)'; do not treat owners/values as real. No skip-tracing, no contacting "
        "owners from this module — it only flags candidates for the real-estate radar. "
        "Verify against the live CAD before any outreach or offer."
    ),
}

# How "fresh" the CAD record is treated for the decision engine (sample == lower confidence).
_BASE_CONFIDENCE = 0.55


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_parcels(path: Path | None = None) -> list[dict]:
    """Load CAD-shaped parcels. Prefers a live data/parcels.json if present,
    else falls back to the bundled sample. Pure stdlib JSON."""
    if path is not None:
        src = path
    else:
        live = HERE / "data" / "parcels.json"
        src = live if live.exists() else DATA_FILE
    raw = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("parcels", [])
    return raw  # allow a bare list too


# ----------------------------------------------------------------------------
# Core analytics
# ----------------------------------------------------------------------------
def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def equity_vs_comps(parcel: dict) -> dict:
    """Compute the equity-vs-comps signal for one parcel.

    Logic:
      comp_value   = living_area_sqft * comp_median_value_per_sqft  (neighborhood comp)
      market_value = CAD's appraised market value
      under_assessed_pct = how far CAD market sits BELOW comp value
          (positive => CAD undervalues vs comps => latent equity on acquisition)
      For land-only parcels (no improvement / no sqft), comp basis is unavailable,
      so the signal falls back to acreage-driven land equity.
    """
    sqft = _f(parcel.get("living_area_sqft"))
    ppsf = _f(parcel.get("comp_median_value_per_sqft"))
    market = _f(parcel.get("market_value"))
    land = _f(parcel.get("land_value"))
    improvement = _f(parcel.get("improvement_value"))

    comp_value = round(sqft * ppsf, 0) if (sqft and ppsf) else None

    under_assessed_pct = None
    if comp_value and market:
        # comps say it's worth comp_value; CAD says market. gap as % of comp_value.
        under_assessed_pct = round((comp_value - market) / comp_value * 100, 1)

    # Equity proxy: full market value is the equity ceiling absent a known loan.
    # We surface CAD market as "est_value" (the equity the deal can capture).
    est_value = market if market else (land + improvement)

    return {
        "comp_value": comp_value,
        "comp_basis_ppsf": ppsf or None,
        "market_value": market or None,
        "under_assessed_pct": under_assessed_pct,
        "land_value": land or None,
        "improvement_value": improvement or None,
        "land_share_pct": round(land / market * 100, 1) if market else None,
        "est_value": est_value or None,
    }


def years_owned(parcel: dict) -> int | None:
    y = parcel.get("last_deed_year")
    try:
        y = int(y)
    except (TypeError, ValueError):
        return None
    if y <= 0:
        return None
    return max(datetime.now().year - y, 0)


def parcel_url(parcel: dict) -> str:
    """Best-guess public detail URL for the account (documented, not fetched)."""
    cad = (parcel.get("cad") or parcel.get("county") or "").lower()
    acct = parcel.get("account", "")
    if cad.startswith("hidalgo"):
        return f"https://esearch.hidalgoad.org/Property/View/{acct}"
    if cad.startswith("cameron"):
        return f"https://esearch.cameroncad.org/Property/View/{acct}"
    if cad.startswith("starr"):
        return "https://www.starrcad.org/"
    if cad.startswith("willacy"):
        return "https://willacycad.org/"
    return "https://comptroller.texas.gov/taxes/property-tax/"


def lookup(account: str, parcels: list[dict] | None = None) -> dict | None:
    """Return the full enriched record for a parcel/account id."""
    parcels = parcels if parcels is not None else load_parcels()
    acct = str(account).strip().lower()
    for p in parcels:
        if str(p.get("account", "")).strip().lower() == acct \
                or str(p.get("geo_id", "")).strip().lower() == acct:
            return describe(p)
    return None


def describe(parcel: dict) -> dict:
    """Full normalized record: owner, situs, values, split, year, acreage, signal."""
    eq = equity_vs_comps(parcel)
    yo = years_owned(parcel)
    return {
        "account": parcel.get("account"),
        "geo_id": parcel.get("geo_id"),
        "cad": parcel.get("cad") or parcel.get("county"),
        "owner": parcel.get("owner"),
        "situs": parcel.get("situs"),
        "city": parcel.get("city"),
        "county": parcel.get("county"),
        "market_value": eq["market_value"],
        "assessed_value": _f(parcel.get("assessed_value")) or None,
        "land_value": eq["land_value"],
        "improvement_value": eq["improvement_value"],
        "land_share_pct": eq["land_share_pct"],
        "year_built": parcel.get("year_built") or None,
        "living_area_sqft": parcel.get("living_area_sqft") or None,
        "acreage": parcel.get("acreage"),
        "last_deed_year": parcel.get("last_deed_year"),
        "years_owned": yo,
        "homestead": parcel.get("homestead"),
        "equity_signal": eq,
        "url": parcel_url(parcel),
        "is_sample": "sample" in str(parcel.get("owner", "")).lower(),
    }


# ----------------------------------------------------------------------------
# Flagging -> decision-engine items
# ----------------------------------------------------------------------------
# thresholds
UNDER_ASSESSED_PCT = 8.0     # CAD market this % below comps => under-assessed flag
HIGH_EQUITY_VALUE = 200000   # land+improvement (or market) above this => high-equity
LONG_OWNED_YEARS = 25        # held this long => long-owned/tired-owner flag


def _risk_from(parcel: dict, eq: dict) -> str:
    """More land share + more equity headroom = LOWER acquisition risk."""
    land_share = eq.get("land_share_pct") or 0
    est = eq.get("est_value") or 0
    if land_share >= 70 or est >= 250000:
        return "LOW"
    if est >= 100000:
        return "MED"
    return "HIGH"


def _classify(parcel: dict, rec: dict) -> list[str]:
    flags = []
    eq = rec["equity_signal"]
    ua = eq.get("under_assessed_pct")
    if ua is not None and ua >= UNDER_ASSESSED_PCT:
        flags.append("under_assessed")
    if (eq.get("est_value") or 0) >= HIGH_EQUITY_VALUE:
        flags.append("high_equity")
    yo = rec.get("years_owned")
    if yo is not None and yo >= LONG_OWNED_YEARS:
        flags.append("long_owned")
    owner = str(parcel.get("owner", "")).lower()
    if any(k in owner for k in ("estate", "trust", "heirs")):
        flags.append("estate_or_trust")
    # land-heavy / no-improvement raw land = development/flip candidate
    if not parcel.get("improvement_value") and _f(parcel.get("acreage")) >= 5:
        flags.append("raw_land")
    return flags


_FLAG_ACTION = {
    "under_assessed": "CAD market sits below comps — verify roll, then target for below-market acquisition",
    "high_equity": "High equity / value — owner has room to deal; route to real-estate radar",
    "long_owned": "Held 25+ yrs — likely low loan balance & tired owner; prioritize outreach via radar",
    "estate_or_trust": "Estate/Trust owner — probate-adjacent, motivated heirs; verify before any contact",
    "raw_land": "Raw land — development/subdivision or land-flip candidate; check zoning & utilities",
}


def _confidence(parcel: dict, flags: list[str]) -> float:
    c = _BASE_CONFIDENCE
    # multiple corroborating flags raise confidence; sample data caps it
    c += 0.05 * max(len(flags) - 1, 0)
    if PLUGIN["status"] == "sample":
        c = min(c, 0.70)
    return round(min(c, 0.95), 2)


def items() -> list[dict]:
    """Return flagged radar candidates, shaped for the Decision Engine.

    Each item: title, category, source, action, est_value, risk, location, url,
    confidence (+ flags/owner/signal extras the engine ignores)."""
    parcels = load_parcels()
    out: list[dict] = []
    for p in parcels:
        rec = describe(p)
        flags = _classify(p, rec)
        if not flags:
            continue
        eq = rec["equity_signal"]
        # headline = strongest flag's action; combine the rest
        primary = flags[0]
        action_bits = [_FLAG_ACTION[f] for f in flags if f in _FLAG_ACTION]
        action = action_bits[0] if action_bits else "Review parcel"
        if len(action_bits) > 1:
            action += " | also: " + "; ".join(b.split(" — ")[0].split(" / ")[0]
                                              for b in action_bits[1:])

        ua = eq.get("under_assessed_pct")
        ua_txt = f" | CAD {ua:+.0f}% vs comps" if ua is not None else ""
        yo = rec.get("years_owned")
        yo_txt = f" | held {yo}y" if yo is not None else ""
        title = f"[{rec['cad']}] {rec['situs']}{ua_txt}{yo_txt}"

        out.append({
            "title": title,
            "category": "ASSETS",
            "source": PLUGIN["name"],
            "action": action,
            "est_value": eq.get("est_value"),
            "risk": _risk_from(p, eq),
            "location": rec["situs"] or rec["city"],
            "url": rec["url"],
            "confidence": _confidence(p, flags),
            # ---- extras (ignored by engine, useful downstream) ----
            "account": rec["account"],
            "owner": rec["owner"],
            "flags": flags,
            "primary_flag": primary,
            "under_assessed_pct": ua,
            "years_owned": yo,
            "land_value": eq.get("land_value"),
            "improvement_value": eq.get("improvement_value"),
            "comp_value": eq.get("comp_value"),
            "is_sample": rec["is_sample"],
        })

    # rank: under-assessed magnitude, then est_value
    out.sort(key=lambda i: ((i["under_assessed_pct"] or 0), (i["est_value"] or 0)),
             reverse=True)
    return out


# ----------------------------------------------------------------------------
# Optional: write a processed snapshot (own folder OR 00_PROCESSED)
# ----------------------------------------------------------------------------
def _pineapple_root() -> Path | None:
    for a in [HERE, *HERE.parents]:
        if (a / ".pineapple_root").exists():
            return a
    return None


def write_snapshot() -> Path:
    """Write flagged items to 00_PROCESSED/cad_appraisal_items.json if reachable,
    else to this module's own folder. Allowed write targets only."""
    payload = {
        "generated": _now(),
        "plugin": PLUGIN["id"],
        "status": PLUGIN["status"],
        "count": None,
        "items": items(),
    }
    payload["count"] = len(payload["items"])
    root = _pineapple_root()
    if root is not None:
        outdir = root / "00_PROCESSED"
        outdir.mkdir(parents=True, exist_ok=True)
        dest = outdir / "cad_appraisal_items.json"
    else:
        dest = HERE / "cad_appraisal_items.json"
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


# ----------------------------------------------------------------------------
# Selftest
# ----------------------------------------------------------------------------
def selftest() -> int:
    ok = True
    msgs = []

    # 1. data loads
    try:
        parcels = load_parcels()
    except Exception as e:
        print(f"  FAIL  could not load sample_parcels.json: {e}")
        return 1
    n = len(parcels)
    cond = n >= 10
    ok &= cond
    msgs.append(("PASS" if cond else "FAIL", f"loaded {n} sample parcels (>=10 expected)"))

    # 2. both CADs present
    cads = {str(p.get("cad", "")).lower() for p in parcels}
    cond = any("hidalgo" in c for c in cads) and any("cameron" in c for c in cads)
    ok &= cond
    msgs.append(("PASS" if cond else "FAIL", f"CADs present: {sorted(cads)}"))

    # 3. lookup works on a known Hidalgo account
    rec = lookup("P504217", parcels)
    cond = bool(rec is not None and rec.get("owner") and rec.get("situs"))
    ok &= cond
    if cond:
        msgs.append(("PASS", f"lookup P504217 -> {rec['owner']} @ {rec['situs']}"))
    else:
        msgs.append(("FAIL", "lookup P504217 returned nothing"))

    # 4. equity-vs-comps signal computes a number for an improved parcel
    if rec:
        ua = rec["equity_signal"].get("under_assessed_pct")
        cond = ua is not None
        ok &= cond
        msgs.append(("PASS" if cond else "FAIL",
                     f"equity-vs-comps for P504217: under_assessed_pct={ua}"))

    # 5. items() returns engine-shaped flagged candidates
    its = items()
    required = {"title", "category", "source", "action", "est_value",
                "risk", "location", "url", "confidence"}
    cond = len(its) >= 1 and all(required <= set(i) for i in its)
    ok &= cond
    msgs.append(("PASS" if cond else "FAIL",
                 f"items() -> {len(its)} flagged candidates, all engine-shaped"))

    # 6. risk values are in the allowed set
    bad_risk = {i["risk"] for i in its} - {"LOW", "MED", "HIGH"}
    cond = not bad_risk
    ok &= cond
    msgs.append(("PASS" if cond else "FAIL",
                 f"risk values valid (offenders: {bad_risk or 'none'})"))

    # 7. confidences within [0,1]
    cond = all(0.0 <= i["confidence"] <= 1.0 for i in its)
    ok &= cond
    msgs.append(("PASS" if cond else "FAIL", "all confidences within [0,1]"))

    # 8. snapshot writes to an allowed location
    try:
        dest = write_snapshot()
        cond = dest.exists()
        ok &= cond
        msgs.append(("PASS" if cond else "FAIL", f"snapshot written -> {dest}"))
    except Exception as e:
        ok = False
        msgs.append(("FAIL", f"snapshot write failed: {e}"))

    print("=" * 60)
    print("  CAD APPRAISAL (County Appraisal District) — SELFTEST")
    print("=" * 60)
    for status, m in msgs:
        print(f"  [{status}] {m}")
    # quick flag tally
    tally: dict[str, int] = {}
    for i in its:
        for f in i.get("flags", []):
            tally[f] = tally.get(f, 0) + 1
    print("-" * 60)
    print(f"  flags: {tally}")
    print(f"  status: {PLUGIN['status']}  |  sources: {len(PLUGIN['sources'])} real CAD URLs")
    print("=" * 60)
    print("  HEALTH: " + ("OK" if ok else "DEGRADED"))
    return 0 if ok else 1


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CAD (County Appraisal District) property intelligence — RGV")
    ap.add_argument("--selftest", action="store_true", help="run health checks and exit")
    ap.add_argument("--account", metavar="ID", help="show full record for a parcel/account id")
    ap.add_argument("--list", action="store_true", help="list all sample accounts")
    ap.add_argument("--snapshot", action="store_true", help="write flagged items to 00_PROCESSED")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.list:
        for p in load_parcels():
            print(f"  {p.get('account'):<24} {p.get('cad'):<8} {p.get('situs')}")
        return 0

    if args.account:
        rec = lookup(args.account)
        if rec is None:
            print(json.dumps({"error": f"account not found: {args.account}"}, indent=2))
            return 1
        print(json.dumps(rec, indent=2))
        return 0

    if args.snapshot:
        dest = write_snapshot()
        print(f"wrote {dest}")
        return 0

    # default: flagged radar candidates
    print(json.dumps(items(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
