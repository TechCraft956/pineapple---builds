"""
feed-service/store.py — JSON feed storage with atomic writes.

v1 storage: two JSON files (apps + opportunities) in the service data dir,
same write discipline as recovered shared-feed/feed.py (tmp file + os.replace).
A threading lock + an fcntl file lock serialize writers in-process and
across processes. The storage layer is one module so it can be swapped for
SQLite/Postgres later without changing the API.
"""
import fcntl
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

DATA_DIR = Path(os.environ.get("FEED_DATA_DIR", Path(__file__).parent / "data"))
APPS_FILE = DATA_DIR / "feed.json"
OPPS_FILE = DATA_DIR / "opportunities.json"
AUDIT_FILE = DATA_DIR / "audit.jsonl"
LOCK_FILE = DATA_DIR / ".feed.lock"

_lock = threading.Lock()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _write_lock():
    """Serialize writers: in-process threading lock + cross-process fcntl lock."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(LOCK_FILE, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)


def _read_json(path, default):
    try:
        if not path.exists():
            return default
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else default
    except Exception:
        return default


def _atomic_write(path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)  # os.replace semantics: atomic on POSIX


def read_apps():
    """App statuses, feed.py semantics: {app_id: {app_name, status, ...}}."""
    return _read_json(APPS_FILE, {})


def write_app_status(app_id, app_name, status, metrics=None,
                     recent_events=None, actions=None):
    with _write_lock():
        feed = read_apps()
        feed[app_id] = {
            "app_name": app_name,
            "status": status,
            "last_updated": utcnow(),
            "metrics": metrics or {},
            "recent_events": (recent_events or [])[-10:],
            "actions": actions or [],
        }
        _atomic_write(APPS_FILE, feed)
        return feed[app_id]


def read_opportunities():
    """Opportunity records: {"schema_version": 1, "items": [...]}."""
    doc = _read_json(OPPS_FILE, {"schema_version": SCHEMA_VERSION, "items": []})
    if isinstance(doc, list):  # tolerate a bare-list legacy file
        return {"schema_version": SCHEMA_VERSION, "items": doc}
    doc.setdefault("schema_version", SCHEMA_VERSION)
    doc.setdefault("items", [])
    return doc


def append_audit(event):
    with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": utcnow(), **event}) + "\n")


def _canonical(rec):
    """Identity for dedupe: the record minus volatile writer timestamps.
    Two posts of the same logical record are duplicates even though the
    writer stamped a fresh collected_at / retrieved_at each time."""
    out = {k: v for k, v in rec.items() if k != "collected_at"}
    prov = dict(out.get("provenance") or {})
    prov.pop("retrieved_at", None)
    if prov:
        out["provenance"] = prov
    return out


def upsert_opportunities(records, actor="writer", idempotency_key=None):
    """
    Insert records, deduped by `id`.
    Returns (inserted, duplicates, conflicts):
      - duplicate: same id and identical payload already stored -> skipped
      - conflict: same id with a different payload -> rejected, not stored
    Atomic: the whole batch is written in one locked replace.
    """
    with _write_lock():
        doc = read_opportunities()
        by_id = {r["id"]: r for r in doc["items"]}
        inserted, duplicates, conflicts = [], [], []
        for rec in records:
            existing = by_id.get(rec["id"])
            if existing is None:
                by_id[rec["id"]] = rec
                inserted.append(rec["id"])
            elif _canonical(existing) == _canonical(rec):
                duplicates.append(rec["id"])
            else:
                conflicts.append(rec["id"])
        if inserted:
            doc["items"] = list(by_id.values())
            _atomic_write(OPPS_FILE, doc)
        append_audit({
            "event": "upsert",
            "actor": actor,
            "idempotency_key": idempotency_key,
            "inserted": inserted,
            "duplicates": duplicates,
            "conflicts": conflicts,
        })
        return inserted, duplicates, conflicts
