"""Panopticon source registry loader + integrity checks."""
from __future__ import annotations

import json
from pathlib import Path

METHODS = ("CODE", "BROWSER", "HUMAN")
SUBJECT_TYPES = ("username", "person", "place", "organization", "email", "phone")

_REGISTRY_PATH = Path(__file__).with_name("sources.json")


def load_registry(path: Path | None = None) -> dict:
    data = json.loads((path or _REGISTRY_PATH).read_text(encoding="utf-8"))
    validate_registry(data)
    return data


def validate_registry(data: dict) -> None:
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("registry has no sources")
    seen = set()
    for s in sources:
        sid = s.get("id")
        if not sid or sid in seen:
            raise ValueError("duplicate or missing source id: %r" % sid)
        seen.add(sid)
        if s.get("method") not in METHODS:
            raise ValueError("%s: bad method %r" % (sid, s.get("method")))
        for st in s.get("subject_types", []):
            if st not in SUBJECT_TYPES:
                raise ValueError("%s: bad subject_type %r" % (sid, st))
        eth = s.get("ethics")
        if not isinstance(eth, dict) or not {"excluded", "privacy_sensitive",
                                             "purpose_required"} <= set(eth):
            raise ValueError("%s: ethics block incomplete" % sid)
        for field in ("name", "category", "url", "returns", "access"):
            if not s.get(field):
                raise ValueError("%s: missing field %s" % (sid, field))


def by_id(registry: dict) -> dict:
    return {s["id"]: s for s in registry["sources"]}
