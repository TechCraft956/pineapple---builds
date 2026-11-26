#!/usr/bin/env python3
"""Sensor #74 — NOAA weather & drought (Roma / Starr County, TX).

Read-only collector, standard library only. No accounts, no API keys, no
spending, no signups. Three legs:

1. NWS point + forecasts (VERIFIED, keyless, live) — the National Weather
   Service API (api.weather.gov) requires a custom User-Agent header and
   nothing else. The point lookup for Roma, TX (26.4073, -98.9751) resolves
   to NWS office BRO, gridpoint BRO/20,29, forecast zone TXZ252 and county
   zone TXC427. From there the collector pulls the 7-day forecast (14
   periods) and the hourly forecast (156 periods; the first 48 hours are
   kept in the output, the total count is recorded).

2. NWS active alerts (VERIFIED, keyless, live) — active alerts for the
   Starr County forecast zone TXZ252. Zero active alerts is a real result,
   not a failure. A Texas-wide active-alert count is recorded as context;
   only alerts whose affected zones include TXZ252/TXC427 (or whose UGC
   codes name Starr County) count as Starr County alerts.

3. U.S. Drought Monitor (VERIFIED, keyless, live) — the NDMC USDM web
   service (usdmdataservices.unl.edu, documented at
   droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx),
   CountyStatistics for FIPS 48427. Two statistic formats are fetched:
   categorical (statisticsType=2, exclusive D0-D4 areas — the headline)
   and traditional (statisticsType=1, cumulative areas — reference).
   The legacy ``droughtmonitor.unl.edu/data/json/<date>/tx_county.json``
   path no longer exists (HTTP 404 for every date pattern tried on
   2026-11-26, including ``current`` and ``20261124``); the web service
   above is the live path. Releases are weekly (data valid through
   Tuesday); the latest release at build time is map date 2026-11-24.

Every observation carries ``status`` (VERIFIED / REPORTED / UNKNOWN /
BLOCKED), ``source_url`` and ``retrieved_at_utc``. Missing values stay
``null`` — never zero-filled, never invented.

Usage:
    python3 nws_drought.py [--out FILE] [--cache-dir DIR] [--no-cache]

Exit code is 0 whenever an output document was written, even if a leg is
blocked or unknown — leg status is recorded in the document itself.
Exit code 2 only if no output could be produced at all.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SENSOR_ID = 74
SENSOR_NAME = "noaa-weather-drought"

USER_AGENT = "PineappleSensor74/1.0 (research; public NWS/USDM data, no key)"

LAT = 26.4073
LON = -98.9751
PLACE = "Roma, TX"
COUNTY = "Starr County"
COUNTY_FIPS = "48427"
STATE = "TX"

NWS_BASE = "https://api.weather.gov"
POINT_URL = f"{NWS_BASE}/points/{LAT},{LON}"
ALERTS_ZONE_URL = f"{NWS_BASE}/alerts/active"
ALERTS_TX_URL = f"{NWS_BASE}/alerts/active?area=TX"

USDM_BASE = "https://usdmdataservices.unl.edu/api/CountyStatistics"
USDM_DOC_URL = ("https://droughtmonitor.unl.edu/DmData/DataDownload/"
                "WebServiceInfo.aspx")
# Legacy USDM county-JSON path, verified dead 2026-11-26 (HTTP 404 for
# current/20261124/20261117/dated patterns). Kept for the record only.
USDM_LEGACY_URL = ("https://droughtmonitor.unl.edu/data/json/"
                   "20261124/tx_county.json")

DROUGHT_CATEGORIES = ("none", "d0", "d1", "d2", "d3", "d4")
HOURLY_KEEP = 48  # keep the first 48 hourly periods; record the total


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get(url: str, params: dict | None = None, timeout: int = 90,
              headers: dict | None = None) -> bytes:
    """GET a URL, returning raw bytes. Raises on HTTP/network error."""
    full = url
    if params:
        full = url + "?" + urllib.parse.urlencode(params)
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(full, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _zone_code(zone_url) -> str | None:
    """'https://api.weather.gov/zones/forecast/TXZ252' -> 'TXZ252'."""
    if not isinstance(zone_url, str) or not zone_url:
        return None
    return zone_url.rstrip("/").rsplit("/", 1)[-1] or None


def _nested_value(obj) -> float | int | None:
    """NWS quantitative value: {'unitCode': ..., 'value': 42} -> 42; None stays None."""
    if isinstance(obj, dict):
        return obj.get("value")
    return None


def _empty_to_none(value):
    """Empty strings in NWS payloads (e.g. windDirection '') mean 'not given'."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def parse_point(payload: dict, retrieved_at: str) -> dict:
    """NWS point response -> gridpoint / zone resolution observation."""
    props = payload.get("properties", {}) or {}
    forecast_zone = _zone_code(props.get("forecastZone"))
    county_zone = _zone_code(props.get("county"))
    rel = props.get("relativeLocation", {}) or {}
    rel_props = rel.get("properties", {}) or {}
    dist = rel_props.get("distance", {}) or {}
    return {
        "metric": "nws_point",
        "lat": LAT,
        "lon": LON,
        "place": PLACE,
        "county": COUNTY,
        "county_fips": COUNTY_FIPS,
        "state": STATE,
        "cwa": props.get("cwa"),
        "grid_id": props.get("gridId"),
        "grid_x": props.get("gridX"),
        "grid_y": props.get("gridY"),
        "forecast_url": props.get("forecast"),
        "forecast_hourly_url": props.get("forecastHourly"),
        "forecast_grid_data_url": props.get("forecastGridData"),
        "forecast_zone": forecast_zone,
        "forecast_zone_url": props.get("forecastZone"),
        "county_zone": county_zone,
        "county_zone_url": props.get("county"),
        "fire_weather_zone": _zone_code(props.get("fireWeatherZone")),
        "nearest_place": rel_props.get("city"),
        "nearest_place_state": rel_props.get("state"),
        "nearest_place_distance_m": _nested_value(dist),
        "status": ("VERIFIED" if props.get("forecast") and forecast_zone
                   else "UNKNOWN"),
        "source": "National Weather Service API — points",
        "source_url": POINT_URL,
        "retrieved_at_utc": retrieved_at,
    }


def parse_forecast_period(period: dict, retrieved_at: str,
                          kind: str = "forecast_7day") -> dict:
    """One NWS forecast period -> one observation. Missing stays None."""
    return {
        "metric": kind,
        "number": period.get("number"),
        "name": period.get("name"),
        "start_time": period.get("startTime"),
        "end_time": period.get("endTime"),
        "is_daytime": period.get("isDaytime"),
        "temperature": period.get("temperature"),
        "temperature_unit": period.get("temperatureUnit"),
        "temperature_trend": period.get("temperatureTrend"),
        "relative_humidity_percent": _nested_value(
            period.get("relativeHumidity")),
        "dewpoint_c": _nested_value(period.get("dewpoint")),
        "wind_speed": period.get("windSpeed"),
        "wind_direction": _empty_to_none(period.get("windDirection")),
        "short_forecast": period.get("shortForecast"),
        "detailed_forecast": period.get("detailedForecast"),
        "precipitation_probability_percent": _nested_value(
            period.get("probabilityOfPrecipitation")),
        "unit": "period",
        "status": "VERIFIED" if period.get("temperature") is not None else "UNKNOWN",
        "source": "National Weather Service API — gridpoints forecast",
        "retrieved_at_utc": retrieved_at,
    }


def parse_alert(feature: dict, retrieved_at: str) -> dict:
    """One NWS alert feature -> one observation (VERIFIED)."""
    props = feature.get("properties", {}) or {}
    geocode = props.get("geocode", {}) or {}
    affected = props.get("affectedZones", []) or []
    return {
        "metric": "nws_alert",
        "alert_id": feature.get("id"),
        "event": props.get("event"),
        "severity": props.get("severity"),
        "certainty": props.get("certainty"),
        "urgency": props.get("urgency"),
        "status_alert": props.get("status"),
        "message_type": props.get("messageType"),
        "category": props.get("category"),
        "headline": props.get("headline"),
        "area_desc": props.get("areaDesc"),
        "sender_name": props.get("senderName"),
        "sent_at": props.get("sent"),
        "effective_at": props.get("effective"),
        "onset_at": props.get("onset"),
        "expires_at": props.get("expires"),
        "ends_at": props.get("ends"),
        "affected_zones": [_zone_code(z) for z in affected],
        "ugc_codes": geocode.get("UGC"),
        "same_codes": geocode.get("SAME"),
        "unit": "alert",
        "status": "VERIFIED",
        "source": "National Weather Service API — alerts",
        "source_url": ALERTS_ZONE_URL,
        "retrieved_at_utc": retrieved_at,
    }


def parse_usdm_row(row: dict, retrieved_at: str,
                   statistic_format: str) -> dict:
    """One USDM CountyStatistics row -> one weekly drought observation.

    ``statistic_format`` is 'categorical' (exclusive D0-D4 areas, the
    headline) or 'traditional' (cumulative areas). Areas are square miles
    of the county in each category; percentages are computed against the
    county total (sum of none + D0-D4 in the same row).
    """
    areas = {}
    for cat in DROUGHT_CATEGORIES:
        val = row.get(cat)
        areas[cat] = val if isinstance(val, (int, float)) else None
    total = None
    if all(v is not None for v in areas.values()):
        total = sum(areas.values())
    percents = {}
    for cat in DROUGHT_CATEGORIES:
        if areas[cat] is not None and total:
            percents[cat] = round(100.0 * areas[cat] / total, 2)
        else:
            percents[cat] = None
    return {
        "metric": "usdm_county_drought",
        "statistic_format": statistic_format,
        "map_date": (row.get("mapDate") or "")[:10] or None,
        "valid_start": (row.get("validStart") or "")[:10] or None,
        "valid_end": (row.get("validEnd") or "")[:10] or None,
        "fips": row.get("fips"),
        "county": row.get("county"),
        "state": row.get("state"),
        "area_sq_mi": areas,
        "area_percent": percents,
        "county_total_sq_mi": total,
        "unit": "sq mi / percent of county",
        "status": "VERIFIED" if row.get("fips") == COUNTY_FIPS else "UNKNOWN",
        "source": "U.S. Drought Monitor web service — CountyStatistics",
        "source_url": USDM_BASE,
        "retrieved_at_utc": retrieved_at,
    }


def _usdm_window() -> tuple[str, str]:
    """Last 5 weeks as M/D/YYYY (the format the USDM service expects)."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=35)
    return (f"{start.month}/{start.day}/{start.year}",
            f"{end.month}/{end.day}/{end.year}")


def fetch_nws_point(retrieved_at: str, fetcher=_http_get) -> dict:
    """Resolve the NWS point. Returns leg dict."""
    leg = {"name": "nws_point", "status": "VERIFIED",
           "source_url": POINT_URL, "retrieved_at_utc": retrieved_at,
           "point": None, "error": None}
    try:
        payload = json.loads(fetcher(POINT_URL, None, 90).decode("utf-8"))
        point = parse_point(payload, retrieved_at)
        leg["point"] = point
        leg["status"] = point["status"]
        if leg["status"] != "VERIFIED":
            leg["error"] = ("Point response did not include a forecast URL "
                            "or forecast zone.")
    except Exception as exc:  # noqa: BLE001 — record, don't crash the run
        leg["status"] = "UNKNOWN"
        leg["error"] = f"NWS point fetch failed: {exc}"
    return leg


def fetch_forecast(point: dict | None, retrieved_at: str, cache: dict | None = None,
                   fetcher=_http_get) -> dict:
    """7-day forecast for the resolved gridpoint. Returns leg dict."""
    url = (point or {}).get("forecast_url")
    leg = {"name": "nws_forecast_7day", "status": "VERIFIED",
           "source_url": url, "retrieved_at_utc": retrieved_at,
           "periods": [], "period_count": 0, "generated_at": None,
           "update_time": None, "error": None}
    if not url:
        leg["status"] = "UNKNOWN"
        leg["error"] = "No forecast URL resolved from the NWS point lookup."
        return leg
    try:
        payload = json.loads(fetcher(url, None, 90).decode("utf-8"))
        props = payload.get("properties", {}) or {}
        if cache is not None:
            cache["nws_forecast_raw.json"] = json.dumps(payload).encode("utf-8")
        leg["generated_at"] = props.get("generatedAt")
        leg["update_time"] = props.get("updateTime")
        leg["periods"] = [parse_forecast_period(p, retrieved_at)
                          for p in props.get("periods", [])]
        leg["period_count"] = len(leg["periods"])
        if not leg["periods"]:
            leg["status"] = "UNKNOWN"
            leg["error"] = "Forecast response contained zero periods."
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"NWS forecast fetch failed: {exc}"
    return leg


def fetch_hourly(point: dict | None, retrieved_at: str, cache: dict | None = None,
                 fetcher=_http_get) -> dict:
    """Hourly forecast for the resolved gridpoint. Returns leg dict."""
    url = (point or {}).get("forecast_hourly_url")
    leg = {"name": "nws_forecast_hourly", "status": "VERIFIED",
           "source_url": url, "retrieved_at_utc": retrieved_at,
           "periods": [], "period_count_total": 0, "period_count_kept": 0,
           "generated_at": None, "error": None}
    if not url:
        leg["status"] = "UNKNOWN"
        leg["error"] = "No hourly forecast URL resolved from the NWS point lookup."
        return leg
    try:
        payload = json.loads(fetcher(url, None, 90).decode("utf-8"))
        props = payload.get("properties", {}) or {}
        if cache is not None:
            cache["nws_hourly_raw.json"] = json.dumps(payload).encode("utf-8")
        leg["generated_at"] = props.get("generatedAt")
        all_periods = props.get("periods", [])
        leg["period_count_total"] = len(all_periods)
        leg["periods"] = [parse_forecast_period(p, retrieved_at,
                                                kind="forecast_hourly")
                          for p in all_periods[:HOURLY_KEEP]]
        leg["period_count_kept"] = len(leg["periods"])
        if not leg["periods"]:
            leg["status"] = "UNKNOWN"
            leg["error"] = "Hourly forecast response contained zero periods."
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"NWS hourly forecast fetch failed: {exc}"
    return leg


def fetch_alerts(point: dict | None, retrieved_at: str, cache: dict | None = None,
                 fetcher=_http_get) -> dict:
    """Active NWS alerts for the Starr County forecast zone. Returns leg dict."""
    zone = (point or {}).get("forecast_zone")
    county_zone = (point or {}).get("county_zone")
    leg = {"name": "nws_alerts", "status": "VERIFIED",
           "source_url": ALERTS_ZONE_URL, "retrieved_at_utc": retrieved_at,
           "forecast_zone": zone, "county_zone": county_zone,
           "alerts": [], "alert_count": 0, "tx_active_count": None,
           "error": None}
    if not zone:
        leg["status"] = "UNKNOWN"
        leg["error"] = "No forecast zone resolved from the NWS point lookup."
        return leg
    try:
        params = {"zone": zone}
        payload = json.loads(
            fetcher(ALERTS_ZONE_URL, params, 90).decode("utf-8"))
        if cache is not None:
            cache["nws_alerts_raw.json"] = json.dumps(payload).encode("utf-8")
        leg["alerts"] = [parse_alert(f, retrieved_at)
                         for f in payload.get("features", [])]
        leg["alert_count"] = len(leg["alerts"])
        if not leg["alerts"]:
            leg["note"] = ("No active alerts for forecast zone "
                           f"{zone} at retrieval time (zero is a real "
                           "result, not a failure).")
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"NWS alerts fetch failed: {exc}"
        return leg
    # Context only: how many alerts are active anywhere in Texas right now.
    try:
        tx_payload = json.loads(fetcher(ALERTS_TX_URL, None, 90).decode("utf-8"))
        leg["tx_active_count"] = len(tx_payload.get("features", []))
    except Exception:  # noqa: BLE001 — context only; never fails the leg
        leg["tx_active_count"] = None
    return leg


def fetch_usdm(retrieved_at: str, cache: dict | None = None,
               fetcher=_http_get) -> dict:
    """USDM weekly drought categories for Starr County (FIPS 48427).

    Fetches both statistic formats over the last 5 weeks: categorical
    (exclusive areas) and traditional (cumulative areas).
    """
    start, end = _usdm_window()
    leg = {"name": "usdm_drought", "status": "VERIFIED",
           "source_url": USDM_BASE, "retrieved_at_utc": retrieved_at,
           "aoi_fips": COUNTY_FIPS, "window_start": start, "window_end": end,
           "latest": None, "latest_categorical": None,
           "latest_traditional": None,
           "weeks_categorical": [], "weeks_traditional": [],
           "week_count": 0, "error": None,
           "legacy_path_note": ("The legacy USDM county-JSON path "
                                "droughtmonitor.unl.edu/data/json/<date>/"
                                "tx_county.json returns HTTP 404 for every "
                                "date pattern tried 2026-11-26 (current, "
                                "20261124, 20261117); the web service used "
                                "here is the live path."),
           "legacy_path_url": USDM_LEGACY_URL,
           "documentation_url": USDM_DOC_URL}
    for fmt, key, label in ((2, "categorical", "categorical"),
                            (1, "traditional", "traditional")):
        try:
            params = {"aoi": COUNTY_FIPS, "startdate": start,
                      "enddate": end, "statisticsType": fmt}
            raw = fetcher(USDM_BASE + "/GetDroughtSeverityStatisticsByArea",
                          params, 90, headers={"Accept": "application/json"})
            rows = json.loads(raw.decode("utf-8"))
            if not isinstance(rows, list):
                raise RuntimeError(f"USDM {label} response was not a JSON list")
            if cache is not None:
                cache[f"usdm_{key}_raw.json"] = json.dumps(rows).encode("utf-8")
            parsed = [parse_usdm_row(r, retrieved_at, label) for r in rows]
            leg[f"weeks_{key}"] = parsed
            if parsed:
                leg[f"latest_{key}"] = parsed[0]
        except Exception as exc:  # noqa: BLE001
            leg["status"] = "UNKNOWN"
            leg["error"] = (leg["error"] or "") + f"USDM {label} fetch failed: {exc}; "
    cat = leg["weeks_categorical"]
    if cat:
        leg["latest"] = cat[0]
        leg["week_count"] = len(cat)
    elif leg["weeks_traditional"]:
        leg["latest"] = leg["weeks_traditional"][0]
        leg["week_count"] = len(leg["weeks_traditional"])
    if leg["latest"] is None:
        leg["status"] = "UNKNOWN"
        leg["error"] = (leg["error"] or "") + "USDM returned no weekly rows."
    return leg


def collect(fetcher=_http_get, cache: dict | None = None) -> dict:
    """Run all legs and assemble the sensor document."""
    retrieved_at = utc_now_iso()
    point_leg = fetch_nws_point(retrieved_at, fetcher=fetcher)
    point = point_leg["point"]
    forecast = fetch_forecast(point, retrieved_at, cache=cache, fetcher=fetcher)
    hourly = fetch_hourly(point, retrieved_at, cache=cache, fetcher=fetcher)
    alerts = fetch_alerts(point, retrieved_at, cache=cache, fetcher=fetcher)
    usdm = fetch_usdm(retrieved_at, cache=cache, fetcher=fetcher)

    observations = []
    if point:
        observations.append(point)
    observations.extend(forecast["periods"])
    observations.extend(hourly["periods"])
    observations.extend(alerts["alerts"])
    if usdm["latest_categorical"]:
        observations.append(usdm["latest_categorical"])
    if usdm["latest_traditional"]:
        observations.append(usdm["latest_traditional"])

    latest = usdm["latest"]
    return {
        "sensor_id": SENSOR_ID,
        "sensor": SENSOR_NAME,
        "area": "Roma / Starr County, Texas",
        "lat": LAT,
        "lon": LON,
        "county_fips": COUNTY_FIPS,
        "retrieved_at_utc": retrieved_at,
        "legs": {
            "nws_point": {k: v for k, v in point_leg.items() if k != "point"},
            "nws_forecast_7day": {k: v for k, v in forecast.items()
                                  if k != "periods"},
            "nws_forecast_hourly": {k: v for k, v in hourly.items()
                                    if k != "periods"},
            "nws_alerts": {k: v for k, v in alerts.items() if k != "alerts"},
            "usdm_drought": {k: v for k, v in usdm.items()
                             if k not in ("weeks_categorical",
                                          "weeks_traditional")},
        },
        "summary": {
            "nws_cwa": (point or {}).get("cwa"),
            "nws_grid": (f"{(point or {}).get('grid_id')}/"
                         f"{(point or {}).get('grid_x')},"
                         f"{(point or {}).get('grid_y')}"
                         if point else None),
            "nws_forecast_zone": (point or {}).get("forecast_zone"),
            "nws_forecast_periods": forecast["period_count"],
            "nws_forecast_status": forecast["status"],
            "nws_hourly_periods_total": hourly["period_count_total"],
            "nws_hourly_periods_kept": hourly["period_count_kept"],
            "nws_hourly_status": hourly["status"],
            "nws_active_alerts_starr_zone": alerts["alert_count"],
            "nws_active_alerts_tx": alerts["tx_active_count"],
            "nws_alerts_status": alerts["status"],
            "nws_alert_events": [a["event"] for a in alerts["alerts"]],
            "usdm_latest_map_date": (latest or {}).get("map_date"),
            "usdm_latest_valid_end": (latest or {}).get("valid_end"),
            "usdm_status": usdm["status"],
            "usdm_week_count": usdm["week_count"],
            "usdm_starr_drought_categorical_sq_mi": (
                (usdm["latest_categorical"] or {}).get("area_sq_mi")),
            "usdm_starr_drought_categorical_percent": (
                (usdm["latest_categorical"] or {}).get("area_percent")),
            "usdm_starr_drought_traditional_sq_mi": (
                (usdm["latest_traditional"] or {}).get("area_sq_mi")),
        },
        "forecast_7day": forecast["periods"],
        "forecast_hourly": hourly["periods"],
        "alerts": alerts["alerts"],
        "drought_weeks_categorical": usdm["weeks_categorical"],
        "drought_weeks_traditional": usdm["weeks_traditional"],
        "observations": observations,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None,
                        help="Write the JSON document to this file as well as stdout.")
    parser.add_argument("--cache-dir", default=None,
                        help="Directory for raw-response caches (+ .meta.json sidecars).")
    parser.add_argument("--no-cache", action="store_true",
                        help="Do not write raw-response caches.")
    args = parser.parse_args(argv)

    cache: dict | None = None if args.no_cache else {}
    doc = collect(cache=cache)

    if cache is not None and args.cache_dir:
        os.makedirs(args.cache_dir, exist_ok=True)
        for name, payload in cache.items():
            with open(os.path.join(args.cache_dir, name), "wb") as fh:
                fh.write(payload)
            meta = {"retrieved_at_utc": doc["retrieved_at_utc"],
                    "bytes": len(payload)}
            with open(os.path.join(args.cache_dir, name + ".meta.json"),
                      "w", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=1)

    text = json.dumps(doc, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    sys.stderr.write(
        f"[sensor #{SENSOR_ID}] NWS zone={doc['summary']['nws_forecast_zone']} "
        f"forecast_periods={doc['summary']['nws_forecast_periods']} "
        f"hourly_total={doc['summary']['nws_hourly_periods_total']} "
        f"alerts_starr={doc['summary']['nws_active_alerts_starr_zone']} "
        f"(TX {doc['summary']['nws_active_alerts_tx']}) | "
        f"USDM latest={doc['summary']['usdm_latest_map_date']} "
        f"D0={((doc['summary']['usdm_starr_drought_categorical_percent'] or {}).get('d0'))}% "
        f"D1-D4={[(c, ((doc['summary']['usdm_starr_drought_categorical_percent'] or {}).get(c))) for c in ('d1','d2','d3','d4')]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
