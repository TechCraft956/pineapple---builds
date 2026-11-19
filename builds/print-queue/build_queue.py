#!/usr/bin/env python3
"""3D Print Business Queue — builder (v1).

Reads the three input files plus the filament snapshot under inputs/,
applies the hard gates, computes transparent scores, and writes
queue.json (source of truth) + PRINT_QUEUE.md (human artifact).

Python standard library only. No network, no printer access, no scheduling.

Score = market_points x ease_points x fit_points, with H=3, M=2, L=1.
The score is a prioritization heuristic, NOT a profit prediction.

Hard gates:
  * Blocklisted patents (AVOID verdicts + the commercially-dead item from
    the Patent Radar deep check) never enter the queue — validation
    rejects them if they ever appear in an input file.
  * A record with next_action WAITING-ON-AIRAM renders in its own
    section and can never occupy an actionable rank.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"

GRADE_POINTS = {"H": 3, "M": 2, "L": 1}
MAKE_ROUTES = {"PRINT", "PRINT+HARDWARE", "RE-HOUSE", "METAL FAB", "MODEL-FIRST"}
NEXT_ACTIONS = {"MODEL", "PRINT", "LIST", "WAITING-ON-AIRAM"}
SIZE_CLASSES = {"small", "medium", "large"}
USE_CONTEXTS = {"indoor", "outdoor"}
SUITABILITIES = {"good", "partial", "poor"}
TRACK_ORDER = {"patent": 0, "siren": 1, "feed": 2, "manual": 3}
PLA_MATERIALS = {"PLA+", "PLA", "PLA (silk)"}

# Deep-check AVOID verdicts + the commercially-dead item. These must
# NEVER enter the queue (enforced in validation, tested in the suite).
BLOCKLISTED_PATENTS = {"US11344061", "US3869005", "US4008893"}

HEURISTIC_DISCLAIMER = (
    "Scores are a prioritization heuristic (market x ease x filament fit), "
    "NOT a profit prediction."
)


class InputError(ValueError):
    pass


# ---------------------------------------------------------------- validation

def _require(obj, field, ctx):
    if field not in obj or obj[field] in (None, ""):
        raise InputError(f"{ctx}: missing required field {field!r}")
    return obj[field]


def _grade(obj, field, ctx):
    value = _require(obj, field, ctx)
    if value not in GRADE_POINTS:
        raise InputError(f"{ctx}: unknown factor value {value!r} for {field} (want H|M|L)")
    return value


def validate_common(raw, ctx):
    _require(raw, "id", ctx)
    _require(raw, "title", ctx)
    _grade(raw, "market_grade", ctx)
    _grade(raw, "ease_grade", ctx)
    evidence = _require(raw, "market_evidence", ctx)
    if not isinstance(evidence, str) or len(evidence.strip()) < 10:
        raise InputError(f"{ctx}: market_evidence must be a real one-line evidence string")
    route = _require(raw, "make_route", ctx)
    if route not in MAKE_ROUTES:
        raise InputError(f"{ctx}: unknown make_route {route!r}")
    action = _require(raw, "next_action", ctx)
    if action not in NEXT_ACTIONS:
        raise InputError(f"{ctx}: unknown next_action {action!r}")
    if _require(raw, "size_class", ctx) not in SIZE_CLASSES:
        raise InputError(f"{ctx}: unknown size_class {raw['size_class']!r}")
    if _require(raw, "use_context", ctx) not in USE_CONTEXTS:
        raise InputError(f"{ctx}: unknown use_context {raw['use_context']!r}")
    if _require(raw, "material_suitability", ctx) not in SUITABILITIES:
        raise InputError(f"{ctx}: unknown material_suitability {raw['material_suitability']!r}")
    grams = raw.get("est_filament_g")
    if grams is not None:
        if not isinstance(grams, (int, float)) or isinstance(grams, bool) or grams <= 0:
            raise InputError(
                f"{ctx}: est_filament_g must be null (unknown) or a positive number, never 0"
            )


# ---------------------------------------------------------------- filament fit

def compute_filament_fit(raw, filament):
    """Return (grade, assigned_name, reasons[list], flags[list]).

    Rules (brief): colour/material match raises fit; PLA assigned to an
    outdoor piece is a poor fit (softens ~60 C in Roma sun); a large item
    on the scarce gold silk stock scores fit L; poor material suitability
    (e.g. PLA next to ash/heat) scores L; partial suitability caps at M;
    scarce stock on a non-large item caps at M.
    """
    reasons, flags = [], []
    material = filament["material"]
    stock = filament["stock_level"]
    size = raw["size_class"]

    if stock == "scarce" and size == "large":
        reasons.append(
            f"{filament['name']} stock is scarce ('a little') and this is a large item — fit L"
        )
        flags.append("scarce_stock_large_item")
        return "L", filament["name"], reasons, flags
    if raw["use_context"] == "outdoor" and material in PLA_MATERIALS:
        reasons.append(
            "PLA assigned to an outdoor piece is a poor fit — PLA softens ~60 C in Roma sun"
        )
        flags.append("pla_for_outdoor_poor_fit")
        return "L", filament["name"], reasons, flags
    if raw["material_suitability"] == "poor":
        reasons.append("Material suitability is poor for this item's real use (see fit context)")
        flags.append("material_suitability_poor")
        return "L", filament["name"], reasons, flags

    grade = "H"
    if raw["material_suitability"] == "partial":
        grade = "M"
        reasons.append("Material suitability is only partial for this item (see fit context)")
        flags.append("material_suitability_partial")
    if stock == "scarce":
        grade = "M" if grade == "H" else grade
        reasons.append(f"{filament['name']} stock is scarce ('a little') — batch size is capped")
        flags.append("scarce_stock")
    if not raw.get("colour_match", False):
        grade = "M" if grade == "H" else grade
        reasons.append("No exact colour match on hand; assigned filament is the closest available")
        flags.append("colour_mismatch")
    if grade == "H":
        reasons.append(
            f"Colour and material match: {filament['name']} suits this "
            f"{raw['use_context']} {size} item and stock is {stock}"
        )
    reasons.append(raw.get("fit_context", ""))
    return grade, filament["name"], [r for r in reasons if r], flags


# ---------------------------------------------------------------- scoring

def compute_score(market_grade, ease_grade, fit_grade):
    return GRADE_POINTS[market_grade] * GRADE_POINTS[ease_grade] * GRADE_POINTS[fit_grade]


def sort_key(entry):
    """Actionable ordering: score desc, then market desc, then track
    order (patent -> siren -> feed -> manual), then input order (stable)."""
    idx, rec = entry
    return (
        -rec["score"],
        -rec["factors"]["market"]["points"],
        TRACK_ORDER[rec["source_track"]],
        idx,
    )


# ---------------------------------------------------------------- loaders

def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _base_record(raw, track, inventory, ctx):
    validate_common(raw, ctx)
    filament_id = _require(raw, "assigned_filament_id", ctx)
    if filament_id not in inventory:
        raise InputError(f"{ctx}: unknown filament id {filament_id!r}")
    fit_grade, assigned, reasons, flags = compute_filament_fit(raw, inventory[filament_id])
    factors = {
        "market": {"grade": raw["market_grade"], "points": GRADE_POINTS[raw["market_grade"]]},
        "ease": {"grade": raw["ease_grade"], "points": GRADE_POINTS[raw["ease_grade"]]},
        "fit": {"grade": fit_grade, "points": GRADE_POINTS[fit_grade]},
    }
    return {
        "id": raw["id"],
        "title": raw["title"],
        "source_track": track,
        "source_ref": raw.get("source_ref", ""),
        "legal_status": raw.get("legal_status"),
        "market_evidence": {"grade": raw["market_grade"], "evidence": raw["market_evidence"]},
        "make_ease": raw["ease_grade"],
        "make_route": raw["make_route"],
        "filament_fit": {
            "grade": fit_grade,
            "assigned_filament": assigned,
            "assigned_filament_id": filament_id,
            "why": " ".join(
                r if r.rstrip().endswith((".", "!", "?")) else r.rstrip() + "."
                for r in reasons
            ),
            "flags": flags,
        },
        "est_filament_g": raw.get("est_filament_g"),
        "factors": factors,
        "score": compute_score(raw["market_grade"], raw["ease_grade"], fit_grade),
        "next_action": raw["next_action"],
        "blocker": raw.get("blocker"),
    }


def load_patent_winners(path, inventory):
    data = _load_json(path)
    records = []
    for i, raw in enumerate(data["candidates"]):
        ctx = f"patent_winners[{i}]"
        ref = (raw.get("source_ref") or "").replace(" ", "").upper()
        if ref in BLOCKLISTED_PATENTS:
            raise InputError(f"{ctx}: {ref} is blocklisted (AVOID / commercially dead) — never queued")
        rec = _base_record(raw, "patent", inventory, ctx)
        rec["notes"] = raw.get("brand_note", "")
        rec["retrieved_at_utc"] = data.get("retrieved_at_utc")
        rec["queued_at_utc"] = data.get("queued_at_utc")
        records.append(rec)
    return records


def load_feed_candidates(path, inventory):
    data = _load_json(path)
    records = []
    for i, raw in enumerate(data.get("candidates", [])):
        ctx = f"feed_candidates[{i}]"
        # Hard default from the trend-scraper build: licence unknown =>
        # sellable:false. Only genuinely sellable records may be seeded.
        if raw.get("sellable") is not True:
            raise InputError(
                f"{ctx}: feed candidate is not sellable:true — the trend-scraper "
                "hard default (licence unknown => sellable:false) must be respected; "
                "remove it or prove a commercial licence"
            )
        licence = (raw.get("licence") or "").strip()
        if not licence or licence.lower() in ("unknown", "none", "not stated"):
            raise InputError(f"{ctx}: sellable feed candidate with unknown licence is forbidden")
        upper = licence.upper()
        if "NC" in upper or "NON-COMMERCIAL" in upper or "NONCOMMERCIAL" in upper:
            raise InputError(f"{ctx}: non-commercial licence cannot be sellable")
        if "ND" in upper or "NO DERIVATIVES" in upper:
            raise InputError(f"{ctx}: no-derivatives licence is not cleared for sale")
        rec = _base_record(raw, "feed", inventory, ctx)
        rec["legal_status"] = f"Licence (verbatim): {licence} — {raw.get('sellable_reason', '')}"
        rec["notes"] = raw.get("sellable_reason", "")
        rec["retrieved_at_utc"] = raw.get("retrieved_at_utc")
        rec["queued_at_utc"] = data.get("queued_at_utc")
        records.append(rec)
    return records


def load_projects(path, inventory):
    data = _load_json(path)
    records = []
    for i, raw in enumerate(data["projects"]):
        ctx = f"projects[{i}]"
        rec = _base_record(raw, "siren", inventory, ctx)
        rec["notes"] = raw.get("state", "")
        rec["after_waiting_next_action"] = raw.get("after_waiting_next_action")
        rec["retrieved_at_utc"] = raw.get("retrieved_at_utc")
        rec["queued_at_utc"] = data.get("queued_at_utc")
        if rec["next_action"] == "PRINT":
            raise InputError(f"{ctx}: a project entry must never be ranked PRINT in v1")
        records.append(rec)
    return records


def load_inventory(path):
    data = _load_json(path)
    inventory = {f["id"]: f for f in data["filaments"]}
    return data, inventory


# ---------------------------------------------------------------- build

def build(root=ROOT, generated_at=None):
    root = Path(root)
    inputs = root / "inputs"
    inv_data, inventory = load_inventory(inputs / "filament_inventory.json")
    loaded = (
        load_patent_winners(inputs / "patent_winners.json", inventory)
        + load_feed_candidates(inputs / "feed_candidates.json", inventory)
        + load_projects(inputs / "projects.json", inventory)
    )
    ids = [r["id"] for r in loaded]
    if len(ids) != len(set(ids)):
        raise InputError(f"duplicate queue ids: {sorted(ids)}")

    indexed = list(enumerate(loaded))
    actionable = sorted((e for e in indexed if e[1]["next_action"] != "WAITING-ON-AIRAM"), key=sort_key)
    waiting = sorted((e for e in indexed if e[1]["next_action"] == "WAITING-ON-AIRAM"), key=sort_key)

    records = []
    for rank, (_, rec) in enumerate(actionable, start=1):
        rec = dict(rec, section="actionable", rank=rank)
        records.append(rec)
    for rank, (_, rec) in enumerate(waiting, start=1):
        rec = dict(rec, section="waiting_on_airam", rank=None, section_rank=rank)
        records.append(rec)

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    queue = {
        "generated_at_utc": generated_at,
        "heuristic_disclaimer": HEURISTIC_DISCLAIMER,
        "printer": inv_data["printer"],
        "filament_snapshot": {
            "snapshot_date": inv_data["snapshot_date"],
            "note": inv_data["note"],
            "filaments": inv_data["filaments"],
        },
        "counts": {
            "total": len(records),
            "actionable": len(actionable),
            "waiting_on_airam": len(waiting),
            "by_track": {
                t: sum(1 for r in records if r["source_track"] == t)
                for t in ("patent", "feed", "siren", "manual")
            },
        },
        "records": records,
    }
    return queue


# ---------------------------------------------------------------- renderer

def _factor_triple(rec):
    f = rec["factors"]
    return f"{f['market']['grade']}/{f['ease']['grade']}/{f['fit']['grade']}"


def render_markdown(queue):
    snap = queue["filament_snapshot"]
    lines = []
    lines.append("# 3D Print Business Queue")
    lines.append("")
    lines.append(f"Generated: {queue['generated_at_utc']} (UTC)")
    lines.append(f"Filament snapshot date: {snap['snapshot_date']}")
    lines.append(f"Printer: {queue['printer']}")
    lines.append("")
    lines.append(f"> {queue['heuristic_disclaimer']}")
    lines.append("> Score = market x ease x filament-fit points (H=3, M=2, L=1), stored per record in queue.json.")
    lines.append("> Hand-edits go in the files under inputs/ — never in queue.json or this file; both are regenerated by build_queue.py.")
    lines.append("")
    lines.append("## Filament on hand (snapshot)")
    lines.append("")
    for fil in snap["filaments"]:
        lines.append(f"- {fil['name']} — stock: {fil['stock_level']}")
    lines.append(f"- Note: {snap['note']}")
    lines.append("")
    lines.append("## Ranked actionable queue")
    lines.append("")
    lines.append("| Rank | ID | Item | Score | Market/Ease/Fit | Filament | Route | Next |")
    lines.append("|---|---|---|---|---|---|---|---|")
    actionable = [r for r in queue["records"] if r["section"] == "actionable"]
    for rec in actionable:
        lines.append(
            f"| {rec['rank']} | {rec['id']} | {rec['title']} | {rec['score']} | "
            f"{_factor_triple(rec)} | {rec['filament_fit']['assigned_filament']} | "
            f"{rec['make_route']} | {rec['next_action']} |"
        )
    lines.append("")
    lines.append("### Per-item notes (actionable)")
    lines.append("")
    for rec in actionable:
        lines.append(
            f"- **{rec['title']}** — score {rec['score']} "
            f"(market {rec['factors']['market']['grade']}, ease {rec['factors']['ease']['grade']}, "
            f"fit {rec['factors']['fit']['grade']}). Evidence: {rec['market_evidence']['evidence']}. "
            f"Filament: {rec['filament_fit']['assigned_filament']} — {rec['filament_fit']['why']} "
            f"Est. filament: {rec['est_filament_g'] if rec['est_filament_g'] is not None else 'unknown (null, never 0)'}. "
            f"Next action: {rec['next_action']}. Note: {rec['notes']}"
        )
    lines.append("")
    lines.append("## Waiting on Airam")
    lines.append("")
    lines.append("These records are real but blocked on Airam. They are listed separately and never occupy an actionable rank.")
    lines.append("")
    lines.append("| ID | Item | Score | Market/Ease/Fit | Filament | Blocker | After that |")
    lines.append("|---|---|---|---|---|---|---|")
    for rec in [r for r in queue["records"] if r["section"] == "waiting_on_airam"]:
        lines.append(
            f"| {rec['id']} | {rec['title']} | {rec['score']} | {_factor_triple(rec)} | "
            f"{rec['filament_fit']['assigned_filament']} | {rec['blocker']} | "
            f"{rec.get('after_waiting_next_action') or '—'} |"
        )
    lines.append("")
    for rec in [r for r in queue["records"] if r["section"] == "waiting_on_airam"]:
        lines.append(
            f"State — {rec['title']}: {rec['notes']} "
            f"Filament if it proceeds: {rec['filament_fit']['assigned_filament']} — {rec['filament_fit']['why']}"
        )
        lines.append("")
    lines.append("## How this queue works")
    lines.append("")
    lines.append("- Sources: Patent Radar deep-check winners (patent track), the sellable-print Feed track (feed track — currently no verified sellable candidates, see inputs/feed_candidates.json), and Airam's own projects (siren).")
    lines.append("- Hard gates: blocklisted patents never enter the queue; WAITING-ON-AIRAM records render only in their own section; a route that needs a non-print process (RE-HOUSE, METAL FAB) keeps that label — the queue never pretends a re-house is a pure print.")
    lines.append("- Refresh is manual: edit the inputs, run `python3 build_queue.py`, read the result. There is no cron for this queue. See OPERATING_NOTE.md.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the 3D Print Business Queue")
    parser.add_argument("--generated-at", default=None,
                        help="fixed generated-at timestamp (for deterministic test runs)")
    parser.add_argument("--out-dir", default=None, help="output directory (default: this folder)")
    args = parser.parse_args(argv)

    queue = build(ROOT, generated_at=args.generated_at)
    out_dir = Path(args.out_dir) if args.out_dir else ROOT
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "queue.json").write_text(
        json.dumps(queue, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "PRINT_QUEUE.md").write_text(render_markdown(queue), encoding="utf-8")
    print(
        f"wrote queue.json + PRINT_QUEUE.md: {queue['counts']['total']} records "
        f"({queue['counts']['actionable']} actionable, "
        f"{queue['counts']['waiting_on_airam']} waiting on Airam)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
