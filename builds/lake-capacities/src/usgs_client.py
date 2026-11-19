"""USGS NWIS Water Services client (stdlib, keyless JSON).

Endpoints (verified live 2026-11-17/18):
  IV: https://waterservices.usgs.gov/nwis/iv/?format=json&sites=...&parameterCd=62614,62615,00054
  DV: https://waterservices.usgs.gov/nwis/dv/?format=json&sites=...&parameterCd=...&period=P35D
Parameters: 62614 elevation NGVD29 (ft), 62615 elevation NAVD88 (ft),
00054 reservoir storage (acre-ft).

Known behaviour (see BUILD_REPORT.md): the Falcon (08461200) and Amistad
(USIBW 08450700) reservoir sites exist in the NWIS site file but return
zero time series from IV/DV, with or without agencyCd — those lakes are
NOT WIRED on USGS and are served by TWDB (whose source there is IBWC).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from common import fetch_json

BASE = "https://waterservices.usgs.gov/nwis"
PARAMS = "62614,62615,00054"
ELEV_PARAMS = ("62614", "62615")
STORAGE_PARAM = "00054"


def iv_url(site_ids: list[str]) -> str:
    return (f"{BASE}/iv/?format=json&sites={','.join(site_ids)}"
            f"&parameterCd={PARAMS}")


def dv_url(site_ids: list[str], period: str = "P35D") -> str:
    return (f"{BASE}/dv/?format=json&sites={','.join(site_ids)}"
            f"&parameterCd={PARAMS}&period={period}")


def _to_utc_iso(dt_str: str) -> str | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(raw):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= -999990:  # NWIS no-data sentinel family
        return None
    return v


def parse_iv(payload: dict) -> dict:
    """-> {site_id: {param_cd: {"value": float, "observed_at_utc": str}}}"""
    out: dict = {}
    for ts in payload.get("value", {}).get("timeSeries", []):
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        param = ts["variable"]["variableCode"][0]["value"]
        values = ts.get("values", [{}])[0].get("value", [])
        if not values:
            continue
        last = values[-1]
        val = _num(last.get("value"))
        if val is None:
            continue
        out.setdefault(site, {})[param] = {
            "value": val,
            "observed_at_utc": _to_utc_iso(last.get("dateTime", "")),
        }
    return out


def parse_dv(payload: dict) -> dict:
    """-> {site_id: {param_cd: [(date_str, value), ...] sorted}}"""
    out: dict = {}
    for ts in payload.get("value", {}).get("timeSeries", []):
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        param = ts["variable"]["variableCode"][0]["value"]
        series = []
        for v in ts.get("values", [{}])[0].get("value", []):
            val = _num(v.get("value"))
            if val is None:
                continue
            series.append(((v.get("dateTime") or "")[:10], val))
        if series:
            out.setdefault(site, {})[param] = sorted(series)
    return out


def fetch_iv(site_ids, cache_dir=None):
    url = iv_url(site_ids)
    payload = fetch_json(url, cache_dir,
                         "usgs_iv_" + "_".join(site_ids) + ".json")
    return parse_iv(payload), url


def fetch_dv(site_ids, cache_dir=None):
    url = dv_url(site_ids)
    payload = fetch_json(url, cache_dir,
                         "usgs_dv_" + "_".join(site_ids) + ".json")
    return parse_dv(payload), url


def split_current(parsed_site: dict) -> tuple:
    """(storage_acre_ft, elevation_ft, observed_at_utc) from parse_iv site."""
    storage = parsed_site.get(STORAGE_PARAM, {}).get("value")
    elev = None
    obs = None
    for p in ELEV_PARAMS:
        if p in parsed_site:
            elev = parsed_site[p]["value"]
            obs = parsed_site[p]["observed_at_utc"]
            break
    if storage is not None:
        obs = parsed_site[STORAGE_PARAM]["observed_at_utc"] or obs
    elif obs is None and parsed_site:
        obs = next(iter(parsed_site.values()))["observed_at_utc"]
    return storage, elev, obs


if __name__ == "__main__":  # tiny manual check
    data, url = fetch_iv(["08025350"])
    print(url)
    print(json.dumps(data, indent=1))
