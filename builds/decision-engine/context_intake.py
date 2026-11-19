#!/usr/bin/env python3
"""
PINEAPPLE OS - Context Intake Engine.

Dump anything into 00_INBOX/. This reads each file, extracts decision-useful
context (summary + facts/people/money/risks/opportunities under the FACTS/LIKELY/
UNKNOWN truth standard), indexes it, and routes structured outputs into
00_PROCESSED/. Originals in 00_INBOX are READ ONLY - never modified or deleted.

    python context_intake.py            # ingest everything new in 00_INBOX
    python context_intake.py --digest   # print today's context digest
    python context_intake.py --rebuild  # re-ingest all (ignore dedup cache)

Index: 00_INDEX/context_index.json  ·  Sources: 00_INDEX/source_registry.json
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_lib"))
import pineapple_context as pc  # noqa: E402

INBOX = ROOT / "00_INBOX"
PROCESSED = ROOT / "00_PROCESSED"
INDEX = ROOT / "00_INDEX"
CTX_INDEX = INDEX / "context_index.json"
SRC_REG = INDEX / "source_registry.json"

CATEGORY_FILES = {
    "money_items": "money_amounts", "opportunities": "opportunities", "risks": "risks",
    "people": "people", "projects": "projects", "decisions": "decisions",
}


def _load(p, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def ingest(rebuild=False):
    index = {} if rebuild else _load(CTX_INDEX, {})
    seen_hashes = {v.get("sha256") for v in index.values()}
    registry = _load(SRC_REG, {"sources": []})
    files = [p for p in INBOX.rglob("*") if p.is_file() and not p.name.startswith(".")]
    new, skipped, unparsed = 0, 0, 0

    for f in files:
        rel = str(f.relative_to(ROOT))
        try:
            quick_hash = pc.file_sha256(f)
        except Exception:
            continue
        if quick_hash in seen_hashes and not rebuild:
            skipped += 1
            continue
        rec = pc.build_record(f, source_name="00_INBOX/" + f.parent.name)
        index[rel] = rec.to_dict()
        seen_hashes.add(rec.sha256)
        if rec.status == "ok":
            new += 1
            _route(rec)
        else:
            unparsed += 1

    _save(CTX_INDEX, index)
    # source registry: where context came from
    reg_paths = {s["path"] for s in registry["sources"]}
    for sub in sorted({p.parent.name for p in files}):
        if sub not in reg_paths:
            registry["sources"].append({"path": sub, "kind": "inbox", "added": pc.utcnow()})
    _save(SRC_REG, registry)

    print("Context Intake: %d new, %d unchanged(skipped), %d unparsed. Index: %d items"
          % (new, skipped, unparsed, len(index)))
    return index


def _route(rec):
    """Write structured slices into 00_PROCESSED/<category>/."""
    PROCESSED.mkdir(exist_ok=True)
    stem = Path(rec.filename).stem[:50]
    (PROCESSED / "summaries").mkdir(parents=True, exist_ok=True)
    _save(PROCESSED / "summaries" / (stem + ".json"),
          {"title": rec.title, "summary": rec.summary, "truth": rec.truth,
           "tags": rec.tags, "confidence": rec.confidence, "source": rec.source_path})
    for cat, ent_key in CATEGORY_FILES.items():
        vals = rec.entities.get(ent_key, [])
        if vals:
            d = PROCESSED / cat
            d.mkdir(parents=True, exist_ok=True)
            _save(d / (stem + ".json"),
                  {"source": rec.source_path, "items": vals, "date": rec.date_modified})


def digest(index=None):
    index = index or _load(CTX_INDEX, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    agg = {"money_amounts": [], "opportunities": [], "risks": [], "deadlines": [],
           "tasks": [], "decisions": [], "people": []}
    items = sorted(index.values(), key=lambda v: v.get("date_added", ""), reverse=True)
    for v in items:
        for k in agg:
            agg[k] += v.get("entities", {}).get(k, [])
    def top(k, n=8):
        out = []
        for x in agg[k]:
            if x not in out:
                out.append(x)
            if len(out) >= n:
                break
        return out

    print("\n" + "=" * 62)
    print("  PINEAPPLE CONTEXT DIGEST  ·  " + today)
    print("=" * 62)
    print("  %d items indexed from 00_INBOX\n" % len(index))
    for label, key in [("MONEY", "money_amounts"), ("OPPORTUNITIES", "opportunities"),
                       ("RISKS", "risks"), ("DEADLINES", "deadlines"),
                       ("TASKS", "tasks"), ("DECISIONS", "decisions"), ("PEOPLE", "people")]:
        vals = top(key)
        if vals:
            print("  %s:" % label)
            for v in vals:
                print("    - %s" % str(v)[:90])
            print("")
    out = INDEX / "context_digest.json"
    _save(out, {"generated": pc.utcnow(), "counts": {k: len(set(map(str, agg[k]))) for k in agg},
                "top": {k: top(k) for k in agg}})
    print("  Saved: %s\n" % out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    if args.digest:
        digest()
    else:
        idx = ingest(rebuild=args.rebuild)
        digest(idx)
