#!/usr/bin/env python3
"""
Patent / Product-Opportunity Radar  -  04_INTELLIGENCE

From the owner's backlog: track EXPIRED / EXPIRING patents, NEW filings, and trend
signals to surface buildable or licensable product ideas - with a bias toward
3D-printable or cheap-to-manufacture items the owner can prototype locally in the
Rio Grande Valley.

Three signal types (see data/sample_patents.json):
  * expired   -> term ended or lapsed -> in the PUBLIC DOMAIN -> build & sell freely
  * expiring  -> expires within a window -> license / design-around opportunity window
  * filing    -> newly published application -> trend / whitespace signal (where the
                 market is heading; do NOT copy a live application)

Each surfaced idea carries: idea, monetization_path, difficulty, capital_needed,
prototype_steps, opportunity_score, plus the decision-engine item contract
(title, category, source, action, est_value, risk, location, url, confidence).

Run:
    python patent_radar.py            # print ideas, write output JSON
    python patent_radar.py --selftest # health check, exit 0 on success
    python patent_radar.py --json     # dump items() as JSON to stdout

Output (written only inside this module folder + 00_PROCESSED/opportunities):
    output/ideas.json

ALL DATA IS SAMPLE. Real live sources are documented in PLUGIN["sources"] and in
data/sample_patents.json -> _meta.real_sources (USPTO PatFT/AppFT, PatentsView API,
USPTO Maintenance Fee Events bulk data, Google Patents / BigQuery public datasets).
This module is OFFLINE: it never fetches the network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- locate Pineapple root without modifying anything -----------------------
HERE = Path(__file__).resolve().parent
# BUILD-20261117-001 (Task 2): the live adapter may point the module at a live
# data file via PATENT_RADAR_DATA; the sample file stays the default.
DATA = Path(os.environ.get("PATENT_RADAR_DATA", HERE / "data" / "sample_patents.json"))
OUT_DIR = HERE / "output"


def _find_root() -> Path | None:
    for a in [HERE, *HERE.parents]:
        if (a / ".pineapple_root").exists():
            return a
    return None


ROOT = _find_root()
PROCESSED = (ROOT / "00_PROCESSED" / "opportunities") if ROOT else None
USER_LOCATION = "Rio Grande Valley, South Texas (Hidalgo/Cameron/Starr/Willacy)"

# REAL live data sources (documented for later wiring; not fetched here).
REAL_SOURCES = [
    "https://search.patentsview.org/api/v1/patent/",            # PatentsView API (free JSON)
    "https://patentsview.org/download/data-download-tables",    # PatentsView bulk downloads
    "https://ppubs.uspto.gov/pubwebapp/",                       # USPTO Patent Public Search (ex-PatFT/AppFT)
    "https://bulkdata.uspto.gov/",                              # USPTO Maintenance Fee Events (early lapses)
    "https://patents.google.com/",                              # Google Patents (browse + status)
    "https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data",  # BigQuery
]

PLUGIN = {
    "id": "patent_radar",
    "name": "Patent / Product-Opportunity Radar",
    "category": "OPPORTUNITIES",
    "authority": "USPTO (PatFT/AppFT, Patent Public Search), PatentsView, Google Patents",
    "status": "sample",
    "inputs": ["data/sample_patents.json"],
    "outputs": ["output/ideas.json", "00_PROCESSED/opportunities/patent_radar_ideas.json"],
    "sources": REAL_SOURCES,
    "safety": (
        "OFFLINE + READ-ONLY. Writes only inside this module folder and 00_PROCESSED. "
        "All records are clearly-marked SAMPLE data. NOT legal advice: always re-verify "
        "legal status (expired / lapsed / in-force) on USPTO Patent Center or Google Patents "
        "before building or licensing. 'expired' here means public-domain candidate; "
        "newly-filed applications are TREND signals only - do not copy a live application."
    ),
}

# ----------------------------------------------------------------------------
# Scoring model
# ----------------------------------------------------------------------------
# Higher score = more attractive buildable/licensable opportunity for THIS owner.
_STATUS_WEIGHT = {
    "expired": 1.0,    # clean public domain -> best
    "expiring": 0.7,   # license/design-around window
    "filing": 0.45,    # trend signal only
}

_DEMAND_KEYWORDS = {
    "high": 1.0, "strong": 0.9, "rising": 0.85, "elevated": 0.8,
    "steady": 0.6, "evergreen": 0.85, "seasonal": 0.55, "saturated": 0.4,
    "crowded": 0.35, "thin": 0.3, "commodity": 0.45,
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_blob() -> dict:
    """Full data file: {"_meta": {...}, "patents": [...]}."""
    if not DATA.exists():
        raise FileNotFoundError("missing sample data: %s" % DATA)
    return json.loads(DATA.read_text(encoding="utf-8"))


def _load_patents() -> list[dict]:
    return _load_blob().get("patents", [])


def _data_status(blob: dict | None = None) -> str:
    """'sample' for fixtures, 'live' for adapter output (from _meta)."""
    try:
        b = blob if blob is not None else _load_blob()
        return str(b.get("_meta", {}).get("data_status", "sample"))
    except Exception:
        return "sample"


def _demand_factor(signal: str) -> float:
    s = (signal or "").lower()
    best = 0.5
    for kw, w in _DEMAND_KEYWORDS.items():
        if kw in s:
            best = max(best, w)
    return best


def _difficulty(p: dict) -> str:
    prof = (p.get("manufacture_profile") or "").lower()
    if prof.startswith("trivial"):
        return "TRIVIAL"
    if prof.startswith("low"):
        return "LOW"
    if prof.startswith("medium") or "medium" in prof:
        return "MEDIUM"
    if prof.startswith("high"):
        return "HIGH"
    return "MEDIUM"


_CAPITAL_BY_DIFFICULTY = {
    "TRIVIAL": "$0-50 (filament you already own)",
    "LOW": "$50-200 (filament + minor hardware)",
    "MEDIUM": "$200-1500 (molds, multi-material, springs/seals)",
    "HIGH": "$1500+ (tooling / injection molding)",
}

_DIFFICULTY_SCORE = {"TRIVIAL": 1.0, "LOW": 0.85, "MEDIUM": 0.55, "HIGH": 0.3}


def _risk(status: str, difficulty: str) -> str:
    # IP risk: building on a live application or near-expiry patent is riskier.
    if status == "filing":
        return "HIGH"      # trend only; copying a pending app risks future infringement
    if status == "expiring":
        return "MED"       # design-around / license window; verify the exact date
    # expired:
    return "LOW" if difficulty in ("TRIVIAL", "LOW") else "MED"


def _monetization_path(p: dict, status: str) -> str:
    domain = p.get("domain", "product")
    if status == "expired":
        return (
            "Public-domain build: manufacture locally (3D print / cheap parts), sell "
            "direct on Facebook Marketplace / Etsy / flea markets + Amazon FBA; bundle "
            "with existing %s flips." % domain
        )
    if status == "expiring":
        return (
            "Prep for window: design-around now, or approach the assignee for a license; "
            "be first-to-market in %s when the patent lapses." % domain
        )
    return (
        "Trend/whitespace signal in %s: do NOT copy the pending application. Build an "
        "adjacent, non-infringing product or supply the maker market around it." % domain
    )


def _prototype_steps(p: dict, difficulty: str) -> list[str]:
    printable = bool(p.get("printable_3d"))
    steps = []
    steps.append("Pull the full patent + drawings from Google Patents (%s) and confirm legal status on USPTO Patent Center." % p.get("patent_number", "?"))
    if printable:
        steps.append("Model the part in CAD (Fusion 360 / FreeCAD) from the patent figures; keep it single-piece where possible.")
        steps.append("Slice and print a v1 in PETG/PLA on the local printer; test fit and function.")
    else:
        steps.append("Identify which parts must be molded/sourced (springs, seals, silicone) vs. 3D-printable; 3D-print the MOLD if molding is needed.")
        steps.append("Source the non-printable parts cheaply (AliExpress/McMaster) and assemble a v1.")
    steps.append("Cost the bill of materials + print time; set a target margin.")
    steps.append("List 3-5 units locally (Marketplace) to validate demand before scaling.")
    if difficulty in ("MEDIUM", "HIGH"):
        steps.append("If validated, get an injection-mold quote (Protolabs / overseas) for unit-cost reduction.")
    return steps


def _idea_text(p: dict, status: str) -> str:
    title = p.get("title", "Untitled")
    if status == "expired":
        return "Build & sell: %s (patent in public domain)" % title
    if status == "expiring":
        return "Position for: %s (patent expiring - license or design-around)" % title
    return "Watch trend: %s (new filing - whitespace signal)" % title


def _opportunity_score(p: dict, difficulty: str) -> float:
    status = p.get("status", "filing")
    sw = _STATUS_WEIGHT.get(status, 0.4)
    df = _DIFFICULTY_SCORE.get(difficulty, 0.5)
    dem = _demand_factor(p.get("demand_signal", ""))
    printable_bonus = 0.1 if p.get("printable_3d") else 0.0
    # weighted blend -> 0..100
    raw = (0.40 * sw) + (0.30 * df) + (0.30 * dem) + printable_bonus
    return round(min(raw, 1.0) * 100, 1)


def _google_patents_url(num: str) -> str:
    return "https://patents.google.com/patent/%s/en" % (num or "").strip()


def build_ideas() -> list[dict]:
    """Core transform: sample patents -> ranked product-opportunity ideas."""
    blob = _load_blob()
    pats = blob.get("patents", [])
    ds = _data_status(blob)
    ideas = []
    for p in pats:
        status = p.get("status", "filing")
        difficulty = _difficulty(p)
        score = _opportunity_score(p, difficulty)
        capital = _CAPITAL_BY_DIFFICULTY.get(difficulty, "unknown")
        # GPT review patch (RESULT-BUILD-20261117-001-GPT): this radar is an
        # IDEA ENGINE, not a legal-status authority. Every idea is
        # REVIEW_REQUIRED until legal status is re-verified on USPTO Patent
        # Center / Google Patents. Scores are heuristics, never legal clearance.
        if ds == "sample":
            review_reason = ("SAMPLE data — illustrative only. Verify legal status on "
                             "USPTO Patent Center / Google Patents before building "
                             "or licensing. Scores are heuristics, not legal clearance.")
        else:
            review_reason = p.get(
                "review_reason",
                "Verify legal status on USPTO Patent Center / Google Patents "
                "before building or licensing. Scores are heuristics, not "
                "legal clearance.")
        idea = {
            "idea": _idea_text(p, status),
            "monetization_path": _monetization_path(p, status),
            "difficulty": difficulty,
            "capital_needed": capital,
            "prototype_steps": _prototype_steps(p, difficulty),
            "opportunity_score": score,
            # supporting context
            "patent_number": p.get("patent_number"),
            "patent_status": status,
            "expiration_date": p.get("expiration_date"),
            "domain": p.get("domain"),
            "printable_3d": bool(p.get("printable_3d")),
            "demand_signal": p.get("demand_signal"),
            "url": _google_patents_url(p.get("patent_number")),
            "data_status": ds,
            "review_required": True,
            "review_reason": review_reason,
            # live-adapter provenance, passed through when present
            "status_method": p.get("status_method"),
            "status_uncertainty": p.get("status_uncertainty"),
            "jurisdiction": p.get("jurisdiction"),
        }
        ideas.append(idea)
    ideas.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return ideas


# ----------------------------------------------------------------------------
# Decision-engine contract
# ----------------------------------------------------------------------------
def items() -> list[dict]:
    """Return ideas shaped to feed the Pineapple decision engine.

    Each item has at least:
    title, category, source, action, est_value (number|null), risk (LOW/MED/HIGH),
    location, url, confidence (0-1).
    """
    out = []
    for idea in build_ideas():
        status = idea["patent_status"]
        difficulty = idea["difficulty"]
        # crude est_value: public-domain + easy + high-demand -> higher est. monthly upside
        base = {"TRIVIAL": 600, "LOW": 450, "MEDIUM": 250, "HIGH": 120}.get(difficulty, 200)
        status_mult = {"expired": 1.0, "expiring": 0.5, "filing": 0.2}.get(status, 0.3)
        est_value = round(base * status_mult * (idea["opportunity_score"] / 100.0))
        if est_value <= 0:
            est_value = None
        # confidence: scaled opportunity_score, but capped because data is SAMPLE
        confidence = round(min(0.85, 0.25 + (idea["opportunity_score"] / 100.0) * 0.55), 2)
        action = "%s | %s | Capital: %s" % (
            idea["idea"], idea["monetization_path"].split(":")[0], idea["capital_needed"]
        )
        out.append({
            "title": idea["idea"],
            "category": "OPPORTUNITIES",
            "source": PLUGIN["name"] + " (SAMPLE)",
            "action": action,
            "est_value": est_value,
            "risk": _risk(status, difficulty),
            "location": USER_LOCATION,
            "url": idea["url"],
            "confidence": confidence,
            # extras the engine may ignore but are useful downstream
            "monetization_path": idea["monetization_path"],
            "difficulty": difficulty,
            "capital_needed": idea["capital_needed"],
            "prototype_steps": idea["prototype_steps"],
            "opportunity_score": idea["opportunity_score"],
            "patent_number": idea["patent_number"],
            "patent_status": status,
            "data_status": idea["data_status"],
            "review_required": True,
            "review_reason": idea["review_reason"],
            "status_method": idea.get("status_method"),
            "status_uncertainty": idea.get("status_uncertainty"),
            "jurisdiction": idea.get("jurisdiction"),
        })
    return out


# ----------------------------------------------------------------------------
# Output writing (sandboxed to this folder + 00_PROCESSED)
# ----------------------------------------------------------------------------
def _safe_write(path: Path, obj) -> None:
    rp = path.resolve()
    allowed = [HERE.resolve()]
    if PROCESSED is not None:
        allowed.append(PROCESSED.resolve())
    if not any(str(rp).startswith(str(a)) for a in allowed):
        raise PermissionError("REFUSED write outside module/00_PROCESSED: %s" % rp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_output() -> Path:
    payload = {
        "generated": utcnow(),
        "module": PLUGIN["id"],
        "status": _data_status(),
        "review_required": True,
        "disclaimer": ("Idea engine, not a legal-status authority. Verify legal "
                       "status on USPTO Patent Center / Google Patents before "
                       "building or licensing. Scores are heuristics."),
        "location": USER_LOCATION,
        "real_sources": REAL_SOURCES,
        "count": 0,
        "ideas": items(),
    }
    payload["count"] = len(payload["ideas"])
    out = OUT_DIR / "ideas.json"
    _safe_write(out, payload)
    if PROCESSED is not None:
        try:
            _safe_write(PROCESSED / "patent_radar_ideas.json", payload)
        except Exception as e:  # never fail the run on the optional mirror
            print("  (note: could not mirror to 00_PROCESSED: %s)" % e)
    return out


# ----------------------------------------------------------------------------
# CLI / selftest
# ----------------------------------------------------------------------------
def render(its: list[dict]) -> None:
    bar = "#" * 64
    ds = (its[0].get("data_status", "sample") if its else "sample").upper()
    print(bar)
    print("#  PATENT / PRODUCT-OPPORTUNITY RADAR  (%s DATA)" % ds)
    print("#  %s" % utcnow())
    print(bar)
    print("#  %d buildable/licensable ideas (highest score first):\n#" % len(its))
    for i, it in enumerate(its, 1):
        print("#  %2d. [score %5.1f] [%s] %s" % (
            i, it["opportunity_score"], it["risk"], it["title"][:48]))
        ev = "n/a" if it["est_value"] is None else ("$%d/mo est." % it["est_value"])
        print("#        diff=%s  capital=%s  %s  conf=%.2f" % (
            it["difficulty"], it["capital_needed"], ev, it["confidence"]))
        print("#        -> %s" % it["monetization_path"][:80])
    print(bar)
    print("#  Reminder: SAMPLE data. Verify legal status on USPTO Patent Center /")
    print("#  Google Patents before building or licensing. Not legal advice.")
    print(bar)


def selftest() -> int:
    problems = []
    try:
        pats = _load_patents()
    except Exception as e:
        print("FAIL: cannot load sample patents: %s" % e)
        return 1
    if len(pats) < 5:
        problems.append("expected >=5 sample patents, got %d" % len(pats))

    its = items()
    if not its:
        problems.append("items() returned empty")

    required = {"title", "category", "source", "action", "est_value",
                "risk", "location", "url", "confidence"}
    for it in its:
        missing = required - set(it.keys())
        if missing:
            problems.append("item missing keys %s: %s" % (missing, it.get("title")))
            break
        if it["risk"] not in ("LOW", "MED", "HIGH"):
            problems.append("bad risk value: %r" % it["risk"])
            break
        if not (0.0 <= it["confidence"] <= 1.0):
            problems.append("confidence out of range: %r" % it["confidence"])
            break
        if it["est_value"] is not None and not isinstance(it["est_value"], (int, float)):
            problems.append("est_value not number/null: %r" % it["est_value"])
            break

    # extended-shape sanity (idea fields)
    for it in its:
        for k in ("idea_present",):
            pass
    for idea in build_ideas():
        for k in ("idea", "monetization_path", "difficulty", "capital_needed",
                  "prototype_steps", "opportunity_score"):
            if k not in idea:
                problems.append("idea missing %s" % k)
                break
        if not isinstance(idea["prototype_steps"], list) or not idea["prototype_steps"]:
            problems.append("prototype_steps empty for %s" % idea.get("idea"))
        break  # one representative check is enough

    # write output and confirm it lands inside the sandbox
    try:
        out = write_output()
        if not out.exists():
            problems.append("output not written")
    except Exception as e:
        problems.append("write_output failed: %s" % e)

    # PLUGIN contract
    for k in ("id", "name", "category", "authority", "status", "inputs",
              "outputs", "sources", "safety"):
        if k not in PLUGIN:
            problems.append("PLUGIN missing key: %s" % k)
    if PLUGIN["status"] != "sample":
        problems.append("PLUGIN status must be 'sample'")
    if not PLUGIN["sources"]:
        problems.append("PLUGIN.sources empty")

    if problems:
        print("SELFTEST FAILED:")
        for p in problems:
            print("  - %s" % p)
        return 1

    top = its[0]
    print("SELFTEST OK")
    print("  patents loaded : %d (%s)" % (len(pats), _data_status()))
    print("  ideas surfaced : %d" % len(its))
    print("  top idea       : [%.1f] %s" % (top["opportunity_score"], top["title"][:50]))
    print("  output written : output/ideas.json (+ 00_PROCESSED mirror if reachable)")
    print("  data status    : %s  | sources documented: %d real endpoints" % (
        _data_status().upper(), len(PLUGIN["sources"])))
    print("  review state   : REVIEW_REQUIRED on all ideas (idea engine, not legal authority)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Patent / product-opportunity radar (sample data).")
    ap.add_argument("--selftest", action="store_true", help="run health check and exit")
    ap.add_argument("--json", action="store_true", help="print items() as JSON")
    ap.add_argument("--quiet", action="store_true", help="suppress the pretty table")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    its = items()
    write_output()
    if args.json:
        print(json.dumps(its, indent=2))
        return 0
    if not args.quiet:
        render(its)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
