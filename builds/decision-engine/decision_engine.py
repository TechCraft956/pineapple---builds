#!/usr/bin/env python3
"""
PINEAPPLE OS - Decision Engine  (outside-in).

SCOPE — HISTORICAL OS AGGREGATOR ONLY. This engine is NOT the production
Pineapple NEXT v1.2.0 trading system and NOT the Life Briefing system. It must
never import, read, modify, schedule, or otherwise touch NEXT, its schedules,
or Life Briefing. A boundary-guard test (tests/test_decision_engine.py)
enforces this. The engine ranks and recommends only; it never places orders,
moves money, or contacts anyone.

The morning brief. It does not start from modules; it starts from the decisions
the Owner faces today, then pulls modules + context + memory to answer them:

    MONEY         - buy / sell / invest / wait?
    ASSETS        - bikes / houses / auctions worth acting on?
    OPPORTUNITIES - grants / internships / patents / businesses?
    RISKS         - family / health / loans / credit / trading?
    TODAY         - the Top-N highest-ROI actions, everything else filtered out.

Every item is scored (life-quant), checked against doctrine, ranked, and the
recommended actions are logged to 06_DECISION/outcomes_log.jsonl for the learning loop.

    python decision_engine.py            # full brief
    python decision_engine.py --top 11   # change how many actions survive the filter
    python decision_engine.py --quiet
Output: decision_brief.json
"""
from __future__ import annotations
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_lib"))
import pineapple_quant as pq      # noqa: E402
import doctrine as doc            # noqa: E402

INDEX = ROOT / "00_INDEX"
DECISION_DIR = ROOT / "06_DECISION"
OUTCOMES = DECISION_DIR / "outcomes_log.jsonl"


def _load(p, default):
    if Path(p).exists():
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- stale-context rule (build decision, documented in STALE_CONTEXT_RULE.md) --
# Context older than STALE_AFTER_DAYS is not dropped — the owner may still need
# to see it — but it is decayed and flagged so an old risk/deadline cannot
# resurface at full strength forever. Decay is a flat -10 quant, floored at 0.
STALE_AFTER_DAYS = 30
STALE_QUANT_DECAY = 10.0


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def apply_staleness(item, date_modified_iso, now=None):
    """Decay + flag one context item when its source record is stale.

    Returns the item (mutated). Items with no usable date are left untouched
    and treated as fresh — absence of a date is not evidence of staleness.
    """
    dt = _parse_iso(date_modified_iso)
    if dt is None:
        return item
    now = now or datetime.now(timezone.utc)
    age_days = (now - dt).days
    if age_days > STALE_AFTER_DAYS:
        item["quant"] = round(max(0.0, item["quant"] - STALE_QUANT_DECAY), 1)
        item["stale"] = True
        item["age_days"] = age_days
        flags = item.setdefault("doctrine", {}).setdefault("flags", [])
        flags.append("STALE: source is %d days old (rule: >%d days decays -%.0f quant)"
                     % (age_days, STALE_AFTER_DAYS, STALE_QUANT_DECAY))
    return item


# ---- gather items from intelligence/asset modules --------------------------
def items_from_modules(weights=None):
    try:
        import pineapple_os as posys
    except Exception as e:
        print("  (modules unavailable: %s)" % e)
        return []
    out = []
    for bucket, py, cls in posys.discover():
        try:
            res = cls().run(publish=False, quiet=True)
        except Exception as e:
            print("  ! module %s failed: %s" % (cls.module_name, e))
            continue
        for o in res["opportunities"]:
            qi = pq.from_opportunity(o)
            qs = pq.score(qi, weights=weights)
            domain = "assets" if bucket == "03_ASSETS" else ("family_bank" if "family" in cls.module_id else "intelligence")
            ditem = {"risk": qi.risk, "capital": qi.capital,
                     "roi_pct": o.get("roi_estimate") if isinstance(o.get("roi_estimate"), (int, float)) else None,
                     "borrower_score": o.get("score") if "family" in cls.module_id else None}
            verdict = doc.check({k: v for k, v in ditem.items() if v is not None}, domain)
            out.append({
                "title": o["title"], "source": cls.module_name, "category": _categorize(cls, o),
                "quant": round(max(0.0, qs.overall - verdict.penalty), 1),
                "raw_score": o["score"], "action": o["action"], "risk": o.get("risk", "UNKNOWN"),
                "roi_estimate": o.get("roi_estimate"), "doctrine": verdict.to_dict(),
                "dims": qs.dims,
            })
    return out


def _categorize(cls, o):
    mid = cls.module_id
    if "family_bank" in mid:
        return "RISKS"
    if cls.layer == "03_ASSETS" or "real_estate" in mid or "marketplace" in mid:
        return "ASSETS"
    if "economic" in mid:
        return "MONEY"
    return "OPPORTUNITIES"


# ---- gather items from ingested context ------------------------------------
def items_from_context(now=None):
    out = []
    for idx_file in ("context_index.json", "scan_index.json"):
        idx = _load(INDEX / idx_file, {})
        for rec in idx.values():
            ents = rec.get("entities") or {}
            src = rec.get("filename", rec.get("source_path", "context"))
            rec_date = rec.get("date_modified") or rec.get("date_added")
            for opp in ents.get("opportunities", [])[:3]:
                out.append(apply_staleness(
                    {"title": "Context: %s" % opp[:50], "source": src, "category": "OPPORTUNITIES",
                     "quant": 45.0, "action": "Review source: %s" % src, "risk": "UNKNOWN",
                     "roi_estimate": None, "doctrine": {"aligned": True, "flags": []}, "dims": {}},
                    rec_date, now=now))
            for rk in ents.get("risks", [])[:3]:
                out.append(apply_staleness(
                    {"title": "Risk flagged: %s" % str(rk)[:50], "source": src, "category": "RISKS",
                     "quant": 55.0, "action": "Inspect risk in %s" % src, "risk": "MEDIUM",
                     "roi_estimate": None, "doctrine": {"aligned": True, "flags": []}, "dims": {}},
                    rec_date, now=now))
            for dl in ents.get("deadlines", [])[:2]:
                out.append(apply_staleness(
                    {"title": "Deadline: %s" % str(dl)[:50], "source": src, "category": "RISKS",
                     "quant": 60.0, "action": "Meet/clear deadline (%s)" % src, "risk": "MEDIUM",
                     "roi_estimate": None, "doctrine": {"aligned": True, "flags": []}, "dims": {}},
                    rec_date, now=now))
    # dedup by title
    seen, uniq = set(), []
    for it in out:
        if it["title"] not in seen:
            seen.add(it["title"]); uniq.append(it)
    return uniq[:40]


def build_brief(top_n=10, use_learned_weights=True):
    """Build the brief.

    use_learned_weights=True (default) scores module items with the weights
    file 00_INDEX/quant_weights.json when present — the learning loop's
    read-back seam (learning.py recalibrate writes that file; see
    LEARNING_LOOP_AUDIT.md). False forces the built-in default weights.
    With zero realized outcomes the weights file does not exist yet, so both
    paths currently score identically; the flag exists so the loop can be
    switched off for a clean comparison once outcomes exist.
    """
    weights = None if use_learned_weights else dict(pq.DEFAULT_WEIGHTS)
    items = items_from_modules(weights=weights) + items_from_context()
    items.sort(key=lambda x: x["quant"], reverse=True)
    cats = {"MONEY": [], "ASSETS": [], "OPPORTUNITIES": [], "RISKS": []}
    for it in items:
        cats.get(it["category"], cats["OPPORTUNITIES"]).append(it)
    top = items[:top_n]

    brief = {"generated": utcnow(), "total_considered": len(items),
             "top_actions": top, "by_decision": {k: v[:8] for k, v in cats.items()}}
    DECISION_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "decision_brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")

    # log recommended actions for the learning loop
    with open(OUTCOMES, "a", encoding="utf-8") as f:
        for it in top:
            f.write(json.dumps({
                "id": uuid.uuid4().hex[:10], "date": utcnow(), "title": it["title"],
                "category": it["category"], "predicted_quant": it["quant"],
                "dims": it.get("dims", {}), "action": it["action"],
                "status": "recommended", "actual_roi": None, "notes": ""
            }) + "\n")
    return brief


def render(brief):
    bar = "#" * 64
    print("\n" + bar)
    print("#  PINEAPPLE DECISION BRIEF  -  " + brief["generated"])
    print(bar)
    print("#  %d items considered. Here is what is worth your attention:\n#" % brief["total_considered"])
    for cat in ("MONEY", "ASSETS", "OPPORTUNITIES", "RISKS"):
        rows = brief["by_decision"].get(cat, [])
        print("#  %s" % cat)
        if not rows:
            print("#     (nothing actionable)\n#")
            continue
        for r in rows[:4]:
            warn = "  !DOCTRINE" if not r["doctrine"].get("aligned", True) else ""
            print("#     [%5.1f] %s%s" % (r["quant"], r["title"][:46], warn))
            print("#            -> %s" % r["action"][:80])
        print("#")
    print(bar)
    print("#  TODAY - TOP ACTIONS (everything else filtered out):")
    for i, r in enumerate(brief["top_actions"], 1):
        print("#  %2d. [%5.1f] %-11s %s" % (i, r["quant"], r["category"], r["title"][:42]))
    print(bar)
    print("#  Logged %d recommendations to 06_DECISION/outcomes_log.jsonl" % len(brief["top_actions"]))
    print("#  Record an outcome later:  python 06_DECISION/learning.py list\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-learned-weights", action="store_true",
                    help="score with built-in default weights, ignoring 00_INDEX/quant_weights.json")
    args = ap.parse_args()
    b = build_brief(args.top, use_learned_weights=not args.no_learned_weights)
    if not args.quiet:
        render(b)
