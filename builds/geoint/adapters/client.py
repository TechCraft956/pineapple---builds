"""adapters/client.py — minimal ArcGIS REST HTTP client with retries + cache.

FEMA's NFHL service intermittently resets connections (HTTP 000 seen 4x
during verification 2026-11-17), so every fetch retries. Raw responses are
cached to ../cache/ with retrieved_at_utc + source URL (provenance, same
discipline as the Patent Radar adapter).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE.parent / "cache"
USER_AGENT = "Pineapple-GEOINT/1.0 (planning-signal research; contact via Hidalgo AD)"

MAX_ATTEMPTS = 3
BACKOFF_S = (2, 5)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_json(url: str, timeout: int = 40) -> dict:
    """GET a URL, parse JSON, retrying transient failures. Raises on failure."""
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_S[attempt])
    raise RuntimeError("fetch failed after %d attempts: %s (url %s)"
                       % (MAX_ATTEMPTS, last_err, url))


def arcgis_query(base_url: str, params: dict) -> dict:
    """GET <base_url>/query?<urlencoded params> as JSON."""
    url = base_url.rstrip("/") + "/query?" + urllib.parse.urlencode(params)
    return fetch_json(url)


def cache_response(name: str, source_url: str, payload: dict) -> Path:
    """Write a raw response to cache/ with provenance. Returns the path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().replace(":", "").replace("-", "")
    path = CACHE_DIR / ("%s_%s.json" % (name, stamp))
    record = {
        "retrieved_at_utc": utcnow(),
        "source_url": source_url,
        "response": payload,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path
