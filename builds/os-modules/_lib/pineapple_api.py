"""
pineapple_api - single data + action layer shared by the TUI, GUI, and web dashboard.

So every interface shows the same numbers and runs the same commands. Read helpers
load the JSON the engines produce; action helpers shell out to the real scripts
(no logic duplicated). Pure stdlib.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = None
for _p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
    if (_p / ".pineapple_root").exists():
        ROOT = _p
        break
ROOT = ROOT or Path(__file__).resolve().parents[1]
INDEX = ROOT / "00_INDEX"
NET = ROOT / "07_NETWORK"
PY = sys.executable


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------- reads ----------
def brief() -> dict:
    return _load(ROOT / "decision_brief.json", {"top_actions": [], "by_decision": {}, "total_considered": 0})


def context_digest() -> dict:
    return _load(INDEX / "context_digest.json", {})


def scan_stats() -> dict:
    idx = _load(INDEX / "scan_index.json", {})
    unp = _load(INDEX / "unparsed_report.json", {"count": 0})
    dup = _load(INDEX / "duplicate_report.json", {"count": 0})
    return {"indexed": len(idx), "unparsed": unp.get("count", 0), "duplicates": dup.get("count", 0)}


def network_users() -> list:
    data = _load(NET / "users.json", {"users": {}})
    return [{k: v for k, v in u.items() if "password" not in k} for u in data.get("users", {}).values()]


def plugins() -> list:
    return _load(NET / "registry" / "source_plugins.json", {}).get("sources", [])


def learning_open() -> list:
    log = ROOT / "06_DECISION" / "outcomes_log.jsonl"
    if not log.exists():
        return []
    out = []
    for ln in log.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                r = json.loads(ln)
                if r.get("status") == "recommended":
                    out.append(r)
            except Exception:
                pass
    return out


def learning_stats() -> dict:
    log = ROOT / "06_DECISION" / "outcomes_log.jsonl"
    rows, by = [], {}
    if log.exists():
        for ln in log.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    for r in rows:
        by[r.get("status", "?")] = by.get(r.get("status", "?"), 0) + 1
    return {"total": len(rows), "by_status": by}


def quant_weights() -> dict:
    return _load(INDEX / "quant_weights.json", {}).get("weights", {})


def doctrine_summary() -> dict:
    d = _load(INDEX / "doctrine.json", {})
    return {"version": d.get("version"), "rules": [r["id"] for r in d.get("rules", [])],
            "hierarchy": d.get("decision_hierarchy", [])}


def modules() -> list:
    try:
        sys.path.insert(0, str(ROOT))
        import pineapple_os as posys
        return [{"layer": b, "name": c.module_name, "id": c.module_id}
                for b, _p, c in posys.discover()]
    except Exception as e:
        return [{"layer": "?", "name": "discover failed: %s" % e, "id": ""}]


def evolution() -> dict:
    review = _load(ROOT / "06_DECISION" / "session_review.json", {})
    registry = _load(INDEX / "capability_registry.json", {"capabilities": []})
    backlog = _load(INDEX / "capability_backlog.json", {"items": []})
    roadmap = _load(INDEX / "roadmap_20_year.json", {})
    return {
        "review": review,
        "registry": registry.get("capabilities", []),
        "backlog": backlog.get("items", []),
        "roadmap": roadmap,
        "questions": review.get("questions", []),
    }


# ---------- actions (shell out to the real scripts) ----------
def _run(args, timeout=600) -> tuple[int, str]:
    try:
        p = subprocess.run([PY] + args, cwd=str(ROOT), capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as e:
        return 1, str(e)


def run_decision(top=10):
    return _run(["decision_engine.py", "--top", str(top), "--quiet"])


def run_intake():
    return _run(["context_intake.py"])


def run_scan(source=None):
    args = ["source_scanner.py"]
    if source:
        args += ["--source", source]
    return _run(args, timeout=900)


def run_graph():
    return _run(["_lib/pineapple_graph.py"])


def graph_query(term):
    return _run(["_lib/pineapple_graph.py", "query", term])


def record_outcome(oid, status, roi=None, notes=""):
    args = ["06_DECISION/learning.py", "record", oid, "--status", status]
    if roi is not None:
        args += ["--actual-roi", str(roi)]
    if notes:
        args += ["--notes", notes]
    return _run(args)


def recalibrate():
    return _run(["06_DECISION/learning.py", "recalibrate"])


def run_evolution(note="dashboard"):
    return _run(["evolution_engine.py", "--note", note])


if __name__ == "__main__":
    print("ROOT:", ROOT)
    b = brief()
    print("brief: %d considered, %d top actions" % (b.get("total_considered", 0), len(b.get("top_actions", []))))
    print("modules:", [m["name"] for m in modules()])
    print("users:", [u["username"] for u in network_users()])
    print("scan:", scan_stats())
    print("learning:", learning_stats())
    print("weights:", quant_weights())
