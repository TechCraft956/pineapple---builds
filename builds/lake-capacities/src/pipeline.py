"""Pipeline: registry + clients -> lake records (live or from cache)."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import twdb_client
import usgs_client
from common import read_cache, read_cache_meta, utc_now_iso
from normalize import build_record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "lakes.json")
CACHE = os.path.join(ROOT, "cache")


def load_registry(path=REGISTRY):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["lakes"]


def _meta(cache_dir, name):
    m = read_cache_meta(cache_dir, name)
    return {"source_url": m.get("url"), "retrieved_at_utc": m.get("retrieved_at_utc")}


def collect(entries, cache_dir=CACHE, offline=False):
    """Fetch (or read from cache when offline=True) and build records."""
    site_ids = [e["usgs_site_id"] for e in entries if e.get("usgs_site_id")]
    if offline:
        iv = usgs_client.parse_iv(json.loads(read_cache(
            cache_dir, "usgs_iv_" + "_".join(site_ids) + ".json")))
        dv = usgs_client.parse_dv(json.loads(read_cache(
            cache_dir, "usgs_dv_" + "_".join(site_ids) + ".json")))
        recent_payload = json.loads(read_cache(
            cache_dir, "twdb_recent_conditions.json"))
        iv_url, dv_url = usgs_client.iv_url(site_ids), usgs_client.dv_url(site_ids)
        recent_url = twdb_client.RECENT_URL
    else:
        iv, iv_url = usgs_client.fetch_iv(site_ids, cache_dir)
        dv, dv_url = usgs_client.fetch_dv(site_ids, cache_dir)
        recent_payload, recent_url = twdb_client.fetch_recent(cache_dir)

    records = []
    for e in entries:
        slug = e["twdb_slug"]
        if offline:
            hist_text = read_cache(cache_dir, f"twdb_{slug}_30day.csv").decode()
            hist = twdb_client.parse_history_csv(hist_text)
            hist_url = twdb_client.csv_url(slug)
        else:
            hist, hist_url = twdb_client.fetch_history(slug, cache_dir)
        provenance = {
            "current": _meta(cache_dir, "twdb_recent_conditions.json")
            or {"source_url": recent_url, "retrieved_at_utc": utc_now_iso()},
            "usgs_iv": {"source_url": iv_url,
                        "retrieved_at_utc": _meta(
                            cache_dir, "usgs_iv_" + "_".join(site_ids)
                            + ".json").get("retrieved_at_utc")},
            "twdb_history": {"source_url": hist_url,
                             "retrieved_at_utc": _meta(
                                 cache_dir, f"twdb_{slug}_30day.csv").get(
                                 "retrieved_at_utc")},
        }
        # provenance.current must point at the actual source url used
        provenance["current"]["source_url"] = recent_url
        rec = build_record(
            e,
            iv.get(e["usgs_site_id"]) if e.get("usgs_site_id") else None,
            dv.get(e["usgs_site_id"]) if e.get("usgs_site_id") else None,
            twdb_client.parse_recent(recent_payload,
                                     e["twdb_condensed_name"]),
            hist,
            provenance,
        )
        rec["item"] = __import__("normalize").record_to_item(
            rec, url=twdb_client.page_url(slug))
        records.append(rec)
    return records
