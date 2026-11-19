#!/usr/bin/env python3
"""
PINEAPPLE OS - Read-Only Source Scanner.

Looks at existing folders (Downloads, Documents, Desktop, Screenshots, ...) for
context WITHOUT ever touching the originals. It only ever writes inside
PINEAPPLE_OS/00_INDEX and PINEAPPLE_OS/00_PROCESSED.

    python source_scanner.py            # scan all enabled sources
    python source_scanner.py --source Downloads
    python source_scanner.py --dry-run  # list what WOULD be scanned, write nothing

HARD SAFETY GUARANTEES (enforced in code below):
  * opens files read-only ('rb'/'r'); never write/rename/move/delete a source
  * refuses to write anything outside 00_INDEX / 00_PROCESSED
  * skips excluded folders and oversized files
  * dedups by content hash; skips unchanged files on re-run (safe to repeat)

Config: 00_INDEX/source_config.json
Outputs: scan_index.json, scan_log.jsonl, unparsed_report.json,
         duplicate_report.json, context_digest_sources.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_lib"))
import pineapple_context as pc  # noqa: E402

INDEX = ROOT / "00_INDEX"
PROCESSED = ROOT / "00_PROCESSED"
CONFIG = INDEX / "source_config.json"
SCAN_INDEX = INDEX / "scan_index.json"
SCAN_LOG = INDEX / "scan_log.jsonl"
UNPARSED = INDEX / "unparsed_report.json"
DUPES = INDEX / "duplicate_report.json"

ALLOWED_WRITE_ROOTS = (INDEX.resolve(), PROCESSED.resolve())


def _assert_safe_write(p: Path):
    rp = p.resolve()
    if not any(str(rp).startswith(str(root)) for root in ALLOWED_WRITE_ROOTS):
        raise PermissionError("REFUSED write outside 00_INDEX/00_PROCESSED: %s" % rp)


def _save(p: Path, obj):
    _assert_safe_write(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _load(p, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _resolve_host_path(win_path: str, cfg: dict) -> Path | None:
    """Translate a configured Windows path to whatever this runtime can actually read."""
    pmap = cfg.get("_path_map_for_this_sandbox", {})
    if win_path in pmap and Path(pmap[win_path]).exists():
        return Path(pmap[win_path])
    p = Path(win_path)
    return p if p.exists() else None


def scan(only_source=None, dry_run=False):
    cfg = _load(CONFIG, {})
    if not cfg:
        print("No source_config.json found at %s" % CONFIG)
        return
    d = cfg.get("defaults", {})
    max_bytes = int(d.get("max_file_size_mb", 25)) * 1024 * 1024
    max_files = int(d.get("max_files_per_scan", 400))
    excluded = set(d.get("excluded_folders", []))
    allowed = set(d.get("allowed_file_types", []))

    index = _load(SCAN_INDEX, {})
    by_hash = {}
    for k, v in index.items():
        by_hash.setdefault(v.get("sha256"), []).append(k)

    log_lines, unparsed, dupes = [], [], []
    totals = {"scanned": 0, "new": 0, "skipped_unchanged": 0, "skipped_excluded": 0,
              "skipped_toobig": 0, "unparsed": 0, "duplicates": 0}

    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        if only_source and src["name"] != only_source:
            continue
        host = _resolve_host_path(src["path"], cfg)
        if not host:
            print("  [%s] not reachable from this runtime (run locally): %s" % (src["name"], src["path"]))
            continue
        meta_only = bool(src.get("metadata_only"))
        src_excluded = excluded | set(src.get("excluded_folders", []))
        subdirs = src.get("subdirs")
        roots = [host / sd for sd in subdirs] if subdirs else [host]
        roots = [r for r in roots if r.exists()]
        print("  Scanning %s (%s)%s ..." % (src["name"], src["path"], " [metadata-only, no download]" if meta_only else ""))
        count_this = 0
        for root in roots:
            if count_this >= max_files:
                break
            walker = os.walk(root) if src.get("recursive", True) else [(str(root), [], [x.name for x in root.iterdir() if x.is_file()])]
            for dirpath, dirnames, filenames in walker:
                dirnames[:] = [dn for dn in dirnames if dn not in src_excluded and not dn.startswith(".")]
                for fn in filenames:
                    if count_this >= max_files:
                        break
                    fpath = Path(dirpath) / fn
                    ext = fpath.suffix.lower()
                    if ext not in allowed:
                        continue
                    try:
                        size = fpath.stat().st_size
                        mtime = fpath.stat().st_mtime
                    except Exception:
                        continue
                    if size > max_bytes:
                        totals["skipped_toobig"] += 1
                        continue
                    key = src["name"] + "::" + str(fpath)
                    count_this += 1
                    totals["scanned"] += 1
                    prev = index.get(key)
                    if prev and abs(prev.get("_mtime", 0) - mtime) < 1 and not dry_run:
                        totals["skipped_unchanged"] += 1
                        continue
                    if dry_run:
                        continue
                    if meta_only:
                        # metadata only: NEVER reads file bytes, so cloud files are NOT downloaded
                        iso = datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        index[key] = {"source_path": str(fpath), "source_name": src["name"],
                            "filename": fpath.name, "extension": ext, "size_bytes": size,
                            "date_modified": iso, "sha256": "", "parser_used": "metadata-only",
                            "status": "indexed-meta", "title": fpath.stem.replace("_", " ")[:120],
                            "summary": "", "confidence": 0.1,
                            "tags": [src["name"].lower().split()[0], ext.lstrip(".") or "file"],
                            "truth": {}, "entities": {}, "_mtime": mtime}
                        totals["new"] += 1
                        log_lines.append(json.dumps({"ts": pc.utcnow(), "source": src["name"],
                            "path": str(fpath), "status": "indexed-meta", "tags": index[key]["tags"]}))
                        continue
                    rec = pc.build_record(fpath, source_name=src["name"])
                    if rec.sha256 in by_hash and key not in by_hash[rec.sha256]:
                        dupes.append({"hash": rec.sha256, "path": str(fpath),
                                      "duplicate_of": by_hash[rec.sha256][0]})
                        totals["duplicates"] += 1
                    by_hash.setdefault(rec.sha256, []).append(key)
                    row = rec.to_dict()
                    row["_mtime"] = mtime
                    index[key] = row
                    totals["new"] += 1
                    if rec.status == "ok":
                        _route(rec, src["name"])
                    else:
                        totals["unparsed"] += 1
                        unparsed.append({"path": str(fpath), "status": rec.status,
                                         "reason": rec.reason, "parser": rec.parser_used})
                    log_lines.append(json.dumps({"ts": pc.utcnow(), "source": src["name"],
                                                 "path": str(fpath), "status": rec.status,
                                                 "tags": rec.tags}))
                if count_this >= max_files:
                    print("    (hit max_files_per_scan=%d cap for %s)" % (max_files, src["name"]))
                    break
        src["last_scanned"] = pc.utcnow()

    if dry_run:
        print("\nDRY RUN: would scan %d files. Nothing written." % totals["scanned"])
        return totals

    _save(SCAN_INDEX, index)
    _save(UNPARSED, {"generated": pc.utcnow(), "count": len(unparsed), "items": unparsed[:500]})
    _save(DUPES, {"generated": pc.utcnow(), "count": len(dupes), "items": dupes[:500]})
    _assert_safe_write(SCAN_LOG)
    with open(SCAN_LOG, "a", encoding="utf-8") as f:
        for ln in log_lines:
            f.write(ln + "\n")
    cfg_out = INDEX / "source_config.json"
    _save(cfg_out, cfg)  # persist last_scanned

    print("\n  RESULTS: " + "  ".join("%s=%d" % (k, v) for k, v in totals.items()))
    print("  Index: %d files  ·  unparsed_report.json: %d  ·  duplicate_report.json: %d"
          % (len(index), len(unparsed), len(dupes)))
    _digest(index)
    return totals


def _route(rec, source_name):
    stem = (source_name + "_" + Path(rec.filename).stem)[:60].replace(" ", "_")
    base = PROCESSED / "summaries"
    base.mkdir(parents=True, exist_ok=True)
    _save(base / (stem + ".json"),
          {"title": rec.title, "summary": rec.summary, "truth": rec.truth,
           "tags": rec.tags, "confidence": rec.confidence, "source": rec.source_path,
           "scanned_from": source_name})


def _digest(index):
    agg = {}
    for v in index.values():
        for k, vals in (v.get("entities") or {}).items():
            agg.setdefault(k, [])
            for x in vals:
                if x not in agg[k]:
                    agg[k].append(x)
    out = INDEX / "context_digest_sources.json"
    _save(out, {"generated": pc.utcnow(), "files_indexed": len(index),
                "top": {k: agg[k][:15] for k in agg}})
    print("  Source context digest: %s" % out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    scan(only_source=args.source, dry_run=args.dry_run)
