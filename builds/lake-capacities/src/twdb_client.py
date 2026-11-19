"""TWDB Water Data for Texas client (stdlib, keyless).

Structured paths discovered and verified live 2026-11-17/18 — these are
the download formats TWDB itself documents on
https://waterdatafortexas.org/reservoirs/download :

  Recent conditions (one record per reservoir, JSON):
    https://waterdatafortexas.org/reservoirs/recent-conditions.json
    Fields per reservoir: volume (total reservoir storage, ac-ft),
    conservation_storage (ac-ft counted against conservation capacity),
    conservation_capacity, conservation_pool_elevation, elevation,
    percent_full, timestamp (daily-average date).

  Per-reservoir daily history (CSV, '#' comment header):
    https://waterdatafortexas.org/reservoirs/individual/<slug>-30day.csv
    Columns: date, water_level, surface_area, reservoir_storage,
    conservation_storage, percent_full, conservation_capacity,
    dead_pool_capacity.

Binational nuance (TWDB's own footnote on the Falcon/Amistad pages):
for Falcon and Amistad (and shared Toledo Bend), conservation_capacity
and conservation_storage are the TEXAS share of the pool (Falcon 58.6%,
Amistad 56.2% of total), while `volume` / `reservoir_storage` are totals.
Percent-full is conservation_storage / conservation_capacity.
"""
from __future__ import annotations

import csv
import io
import json

from common import fetch_json, fetch_text

RECENT_URL = "https://waterdatafortexas.org/reservoirs/recent-conditions.json"
INDIVIDUAL_BASE = "https://waterdatafortexas.org/reservoirs/individual"


def csv_url(slug: str, window: str = "30day") -> str:
    return f"{INDIVIDUAL_BASE}/{slug}-{window}.csv"


def page_url(slug: str) -> str:
    return f"{INDIVIDUAL_BASE}/{slug}"


def parse_recent(payload: dict, condensed_name: str) -> dict | None:
    rec = payload.get(condensed_name)
    if not rec:
        return None
    return {
        "full_name": rec.get("full_name"),
        "timestamp": rec.get("timestamp"),  # YYYY-MM-DD, daily average
        "elevation_ft": rec.get("elevation"),
        "total_storage_acre_ft": rec.get("volume"),
        "conservation_storage_acre_ft": rec.get("conservation_storage"),
        "conservation_capacity_acre_ft": rec.get("conservation_capacity"),
        "total_capacity_at_conservation_pool_acre_ft":
            rec.get("volume_under_conservation_pool_elevation"),
        "conservation_pool_elevation_ft":
            rec.get("conservation_pool_elevation"),
        "percent_full_published": rec.get("percent_full"),
        "surface_area_acres": rec.get("area"),
    }


def parse_history_csv(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if not lines:
        return []
    rows = []
    for row in csv.DictReader(io.StringIO("\n".join(lines))):
        def f(key):
            try:
                return float(row[key])
            except (KeyError, TypeError, ValueError):
                return None
        rows.append({
            "date": row.get("date"),
            "water_level_ft": f("water_level"),
            "reservoir_storage_acre_ft": f("reservoir_storage"),
            "conservation_storage_acre_ft": f("conservation_storage"),
            "percent_full": f("percent_full"),
            "conservation_capacity_acre_ft": f("conservation_capacity"),
        })
    return sorted(rows, key=lambda r: r["date"] or "")


def fetch_recent(cache_dir=None):
    payload = fetch_json(RECENT_URL, cache_dir, "twdb_recent_conditions.json")
    return payload, RECENT_URL


def fetch_history(slug: str, cache_dir=None):
    url = csv_url(slug)
    text = fetch_text(url, cache_dir, f"twdb_{slug}_30day.csv")
    return parse_history_csv(text), url


if __name__ == "__main__":
    payload, url = fetch_recent()
    print(url, len(payload), "reservoirs")
    print(json.dumps(parse_recent(payload, "Falcon"), indent=1))
