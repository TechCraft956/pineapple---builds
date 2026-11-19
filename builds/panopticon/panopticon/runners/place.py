"""Place / GEOINT runner — OpenStreetMap Nominatim (no key).

Geocodes a place subject: coordinates, display name, class/type, address
context. Nominatim usage policy (GPT gate 3) is enforced in code:
- identifiable User-Agent with contact, sent on every request;
- a global >=1 req/s throttle across all calls in this process;
- a local cache (memory + disk) so repeated identical queries make no
  further requests;
- attribution carried on every finding.
Places only — never used to resolve a private individual's address.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from .http_util import http_fetch

SOURCE_ID = "runner:place_geocode"
ENDPOINT = "https://nominatim.openstreetmap.org/search"

NOMINATIM_USER_AGENT = (
    "Panopticon/1.1 (Pineapple research; contact via https://github.com/TechCraft956)")
ATTRIBUTION = "Geocoding data © OpenStreetMap contributors (ODbL)"
MIN_INTERVAL_S = 1.0

_CACHE_PATH = (Path(__file__).resolve().parent.parent.parent
               / ".cache" / "nominatim_cache.json")
_CACHE: dict[str, list[dict]] = {}
_CACHE_LOADED = False
_LAST_REQUEST_MONO: float | None = None
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_url(place: str) -> str:
    q = urllib.parse.urlencode({"q": place, "format": "jsonv2",
                                "addressdetails": "1", "limit": "3"})
    return "%s?%s" % (ENDPOINT, q)


def _load_disk_cache() -> None:
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    _CACHE_LOADED = True
    try:
        if _CACHE_PATH.exists():
            _CACHE.update(json.loads(_CACHE_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass  # a broken cache must never break a run


def _save_disk_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_CACHE, indent=2), encoding="utf-8")
    except Exception:
        pass  # cache persistence is best-effort


def clear_cache() -> None:
    """Test/support helper: empty the in-memory cache (disk untouched)."""
    global _LAST_REQUEST_MONO
    _CACHE.clear()
    _LAST_REQUEST_MONO = None


def _throttle(clock=time.monotonic, sleep=time.sleep) -> None:
    """Global >=1 req/s throttle. Injectable clock/sleep for offline tests."""
    global _LAST_REQUEST_MONO
    with _LOCK:
        now = clock()
        if _LAST_REQUEST_MONO is not None:
            wait = MIN_INTERVAL_S - (now - _LAST_REQUEST_MONO)
            if wait > 0:
                sleep(wait)
                now = clock()
        _LAST_REQUEST_MONO = now


def _field_confidence(conf: float, now: str) -> dict:
    return {field: {"confidence": conf, "retrieved_at_utc": now,
                    "source_id": SOURCE_ID}
            for field in ("lat", "lon", "display_name", "locality")}


def parse_results(place: str, payload: list, url: str) -> list[dict]:
    now = _now()
    if not payload:
        return [{
            "subject": place, "subject_type": "place",
            "claim": "No geocode result for place %r in OpenStreetMap" % place,
            "detail": {"result": "NOT_FOUND", "attribution": ATTRIBUTION},
            "verification": "UNKNOWN", "confidence": 0.3,
            "field_confidence": _field_confidence(0.3, now),
            "source_id": SOURCE_ID, "source_url": url,
            "retrieved_at_utc": now, "method": "CODE",
        }]
    findings = []
    for i, hit in enumerate(payload):
        conf = 0.9 if i == 0 else 0.6
        addr = hit.get("address") or {}
        locality = (addr.get("city") or addr.get("town") or addr.get("village")
                    or addr.get("county") or "")
        findings.append({
            "subject": place, "subject_type": "place",
            "claim": "Geocoded %r -> %s" % (place, hit.get("display_name", "")),
            "detail": {
                "result": "FOUND",
                "lat": hit.get("lat"), "lon": hit.get("lon"),
                "class": hit.get("class"), "type": hit.get("type"),
                "display_name": hit.get("display_name"),
                "locality": locality,
                "state": addr.get("state"), "country": addr.get("country"),
                "attribution": ATTRIBUTION,
            },
            "verification": "VERIFIED", "confidence": conf,
            "field_confidence": _field_confidence(conf, now),
            "source_id": SOURCE_ID, "source_url": url,
            "retrieved_at_utc": now, "method": "CODE",
        })
    return findings


def run(place: str, fetch=None, cache: dict | None = None,
        clock=time.monotonic, sleep=time.sleep) -> list[dict]:
    """Geocode a place, honoring throttle + cache. `cache` overrides the
    module cache (tests pass their own dict; None = module + disk cache)."""
    fetch = fetch or (lambda u, user_agent=None: http_fetch(u, user_agent=user_agent))
    key = place.strip().lower()
    store = cache if cache is not None else _CACHE
    if cache is None:
        _load_disk_cache()
    if key in store:
        hit = copy.deepcopy(store[key])
        for f in hit:
            f["detail"] = dict(f.get("detail") or {})
            f["detail"]["from_cache"] = True
        return hit
    url = build_url(place)
    now = _now()
    _throttle(clock, sleep)
    try:
        status, body = fetch(url, user_agent=NOMINATIM_USER_AGENT)
    except Exception as e:
        return [{
            "subject": place, "subject_type": "place",
            "claim": "Geocoding for %r unavailable (fetch failed: %s)" % (place, e),
            "detail": {"result": "UNKNOWN", "error": str(e),
                       "attribution": ATTRIBUTION},
            "verification": "UNKNOWN", "confidence": 0.1,
            "field_confidence": _field_confidence(0.1, now),
            "source_id": SOURCE_ID, "source_url": url,
            "retrieved_at_utc": now, "method": "CODE",
        }]
    if status != 200:
        return [{
            "subject": place, "subject_type": "place",
            "claim": "Geocoding for %r unavailable (HTTP %s)" % (place, status),
            "detail": {"result": "UNKNOWN", "http_status": status,
                       "attribution": ATTRIBUTION},
            "verification": "UNKNOWN", "confidence": 0.1,
            "field_confidence": _field_confidence(0.1, now),
            "source_id": SOURCE_ID, "source_url": url,
            "retrieved_at_utc": now, "method": "CODE",
        }]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = []
    findings = parse_results(place, payload, url)
    # Cache only genuine results; an empty/inconclusive answer is not cached.
    if payload:
        store[key] = copy.deepcopy(findings)
        if cache is None:
            _save_disk_cache()
    return findings
