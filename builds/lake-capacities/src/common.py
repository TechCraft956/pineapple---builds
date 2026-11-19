"""Shared HTTP + cache helpers (stdlib only).

Every raw response is cached on disk together with a sidecar
``<name>.meta.json`` recording ``retrieved_at_utc`` and the source ``url``,
so any figure in a lake record can be traced back to its raw inputs.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "LakeCapacities/1.0 (Pineapple research; public data)"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_bytes(url: str, cache_dir: str | None = None,
                cache_name: str | None = None, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if cache_dir and cache_name:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, cache_name), "wb") as fh:
            fh.write(data)
        meta = {"url": url, "retrieved_at_utc": utc_now_iso(),
                "bytes": len(data)}
        with open(os.path.join(cache_dir, cache_name + ".meta.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=1)
    return data


def fetch_json(url: str, cache_dir: str | None = None,
               cache_name: str | None = None, timeout: int = 60):
    return json.loads(fetch_bytes(url, cache_dir, cache_name, timeout)
                      .decode("utf-8"))


def fetch_text(url: str, cache_dir: str | None = None,
               cache_name: str | None = None, timeout: int = 60) -> str:
    return fetch_bytes(url, cache_dir, cache_name, timeout).decode(
        "utf-8", "replace")


def read_cache(cache_dir: str, cache_name: str) -> bytes:
    with open(os.path.join(cache_dir, cache_name), "rb") as fh:
        return fh.read()


def read_cache_meta(cache_dir: str, cache_name: str) -> dict:
    path = os.path.join(cache_dir, cache_name + ".meta.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}
