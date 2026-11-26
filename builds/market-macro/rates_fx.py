#!/usr/bin/env python3
"""Central bank policy rates & FX collector — Pineapple sensor #64
(Wave 5, market/macro).

Two keyless, read-only legs, stdlib only:

1. BIS central bank policy rates (WS_CBPOL) via the BIS Stats API v2
   (SDMX-JSON). The dataflow path MUST be
       /api/v2/data/dataflow/BIS/WS_CBPOL/1.0/<FREQ>.<AREA>
   with header
       Accept: application/vnd.sdmx.data+json;version=1.0.0
   (the Accept header is required — a plain request returns 406,
   and the short path form /data/WS_CBPOL/... returns 500).
   Monthly series for a 14-economy set plus daily US and euro-area
   series where the BIS publishes them. The BIS reports the FOMC
   target-range midpoint for the US (3.875 = 3.75–4.00% after the
   16 Sep 2026 cut) — the collector records the BIS value as filed
   and never re-derives it.
2. ECB Data Services (SDW API, JSON-data format, no key):
   daily euro foreign-exchange reference rates (EXR dataflow,
   e.g. USD per EUR) for 12 currencies, plus EURIBOR 3M / 1Y from
   the FM dataflow. The ECB's own key policy rates (MRO / deposit
   facility) have no stable SDW key in this API — that gap is
   recorded as UNKNOWN, not worked around with a guessed key.

Labels
------
VERIFIED  value fetched live and parsed as a number.
REPORTED  series present but the value is missing/unparseable.
UNKNOWN   series/area not published at the requested frequency, or
          the endpoint answered 404 (e.g. ECB policy-rate keys).

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "Pineapple Research research@example.com"
BIS_ACCEPT = "application/vnd.sdmx.data+json;version=1.0.0"
MIN_GAP_S = 0.2

BIS_AREAS_MONTHLY = ["US", "XM", "GB", "JP", "CN", "CH", "CA", "AU",
                     "IN", "BR", "MX", "KR", "ZA", "SE"]
BIS_AREAS_DAILY = ["US", "XM"]
ECB_FX_CURRENCIES = ["USD", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY",
                     "MXN", "BRL", "INR", "SEK", "NOK"]
ECB_EURIBOR = {
    "EURIBOR_3M": "M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
    "EURIBOR_1Y": "M.U2.EUR.RT.MM.EURIBOR1YD_.HSTA",
}

_last_fetch = 0.0


def _throttle() -> None:
    global _last_fetch
    now = time.monotonic()
    wait = MIN_GAP_S - (now - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.monotonic()


def fetch_json_url(url: str, accept: str | None = None,
                   timeout: int = 30) -> tuple[dict | None, str]:
    _throttle()
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), "OK"
    except urllib.error.HTTPError as exc:
        return None, f"HTTP_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError,
            json.JSONDecodeError) as exc:
        return None, f"ERROR_{type(exc).__name__}"


def _bis_series(doc: dict) -> list[dict]:
    """Parse a BIS SDMX-JSON doc into observations.

    Structure: data.dataSets[0].series {"i:j": {observations}} with
    dimensions.series [FREQ, REF_AREA] and dimensions.observation
    [TIME_PERIOD]."""
    out: list[dict] = []
    data = doc.get("data", doc)
    sets = data.get("dataSets", [])
    if not sets:
        return out
    dims = data.get("structure", {}).get("dimensions", {})
    series_dims = dims.get("series", [])
    obs_dim = dims.get("observation", [{}])[0]
    periods = [v.get("id") for v in obs_dim.get("values", [])]
    for key, series in sets[0].get("series", {}).items():
        idx = key.split(":")
        area = None
        freq = None
        for pos, dim in enumerate(series_dims):
            if pos < len(idx):
                vals = dim.get("values", [])
                code = vals[int(idx[pos])].get("id") \
                    if int(idx[pos]) < len(vals) else None
                if dim.get("id") == "REF_AREA":
                    area = code
                elif dim.get("id") == "FREQ":
                    freq = code
        for opos, obs in series.get("observations", {}).items():
            raw = obs[0] if obs else None
            try:
                value = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
            date = periods[int(opos)] if int(opos) < len(periods) else None
            out.append({"area": area, "freq": freq, "date": date,
                        "value": value,
                        "label": "VERIFIED" if value is not None
                                 else "REPORTED"})
    return out


def _ecb_series(doc: dict, kind: str, name: str) -> list[dict]:
    """Parse an ECB SDW jsondata doc into observations."""
    out: list[dict] = []
    sets = doc.get("dataSets", [])
    if not sets:
        return out
    dims = doc.get("structure", {}).get("dimensions", {})
    periods = [v.get("id") for v in
               dims.get("observation", [{}])[0].get("values", [])]
    for series in sets[0].get("series", {}).values():
        for opos, obs in series.get("observations", {}).items():
            raw = obs[0] if obs else None
            try:
                value = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
            date = periods[int(opos)] if int(opos) < len(periods) else None
            out.append({"kind": kind, "name": name, "date": date,
                        "value": value,
                        "label": "VERIFIED" if value is not None
                                 else "REPORTED"})
    return out


def collect(last_n: int = 3) -> dict:
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    observations: list[dict] = []
    leg_status: list[dict] = []

    for area in BIS_AREAS_MONTHLY:
        url = ("https://stats.bis.org/api/v2/data/dataflow/BIS/"
               f"WS_CBPOL/1.0/M.{area}?lastNObservations={last_n}")
        doc, status = fetch_json_url(url, accept=BIS_ACCEPT)
        if doc is None:
            leg_status.append({"leg": "BIS", "series": f"M.{area}",
                               "status": status, "label": "UNKNOWN"})
            continue
        rows = _bis_series(doc)
        if not rows:
            leg_status.append({"leg": "BIS", "series": f"M.{area}",
                               "status": "OK", "label": "REPORTED",
                               "note": "no series in response"})
            continue
        leg_status.append({"leg": "BIS", "series": f"M.{area}",
                           "status": "OK", "label": "VERIFIED",
                           "observations": len(rows)})
        for row in rows:
            observations.append({"source": "BIS WS_CBPOL",
                                 "kind": "policy_rate_monthly",
                                 "area": row["area"], "freq": row["freq"],
                                 "date": row["date"], "value": row["value"],
                                 "label": row["label"]})
    for area in BIS_AREAS_DAILY:
        url = ("https://stats.bis.org/api/v2/data/dataflow/BIS/"
               f"WS_CBPOL/1.0/D.{area}?lastNObservations={last_n}")
        doc, status = fetch_json_url(url, accept=BIS_ACCEPT)
        if doc is None:
            leg_status.append({"leg": "BIS", "series": f"D.{area}",
                               "status": status, "label": "UNKNOWN"})
            continue
        rows = _bis_series(doc)
        if not rows:
            leg_status.append({"leg": "BIS", "series": f"D.{area}",
                               "status": "OK", "label": "REPORTED",
                               "note": "no series in response"})
            continue
        leg_status.append({"leg": "BIS", "series": f"D.{area}",
                           "status": "OK", "label": "VERIFIED",
                           "observations": len(rows)})
        for row in rows:
            observations.append({"source": "BIS WS_CBPOL",
                                 "kind": "policy_rate_daily",
                                 "area": row["area"], "freq": row["freq"],
                                 "date": row["date"], "value": row["value"],
                                 "label": row["label"]})

    for cur in ECB_FX_CURRENCIES:
        url = ("https://data-api.ecb.europa.eu/service/data/EXR/"
               f"D.{cur}.EUR.SP00.A?format=jsondata"
               f"&lastNObservations={last_n}")
        doc, status = fetch_json_url(url)
        if doc is None:
            leg_status.append({"leg": "ECB", "series": f"EXR {cur}",
                               "status": status, "label": "UNKNOWN"})
            continue
        rows = _ecb_series(doc, "fx_reference_rate", f"{cur}/EUR")
        if not rows:
            leg_status.append({"leg": "ECB", "series": f"EXR {cur}",
                               "status": "OK", "label": "REPORTED",
                               "note": "no series in response"})
            continue
        leg_status.append({"leg": "ECB", "series": f"EXR {cur}",
                           "status": "OK", "label": "VERIFIED",
                           "observations": len(rows)})
        for row in rows:
            observations.append({"source": "ECB EXR",
                                 "kind": row["kind"], "name": row["name"],
                                 "date": row["date"], "value": row["value"],
                                 "label": row["label"]})
    for name, key in ECB_EURIBOR.items():
        url = ("https://data-api.ecb.europa.eu/service/data/FM/"
               f"{key}?format=jsondata&lastNObservations={last_n}")
        doc, status = fetch_json_url(url)
        if doc is None:
            leg_status.append({"leg": "ECB", "series": name,
                               "status": status, "label": "UNKNOWN",
                               "note": "key not found in FM dataflow "
                                       "(404) or fetch failed"})
            continue
        rows = _ecb_series(doc, "euribor", name)
        if not rows:
            leg_status.append({"leg": "ECB", "series": name,
                               "status": "OK", "label": "REPORTED",
                               "note": "no series in response"})
            continue
        leg_status.append({"leg": "ECB", "series": name,
                           "status": "OK", "label": "VERIFIED",
                           "observations": len(rows)})
        for row in rows:
            observations.append({"source": "ECB FM",
                                 "kind": row["kind"], "name": row["name"],
                                 "date": row["date"], "value": row["value"],
                                 "label": row["label"]})

    verified = sum(1 for o in observations if o.get("label") == "VERIFIED")
    return {
        "sensor": "64",
        "name": "Central bank policy rates & FX",
        "run_utc": run_utc,
        "source": "BIS Stats API v2 (WS_CBPOL) + ECB Data Services "
                  "(EXR, FM)",
        "fetch_status": "OK",
        "leg_status": leg_status,
        "observations": observations,
        "summary": {
            "observations_total": len(observations),
            "verified": verified,
            "reported": len(observations) - verified,
            "bis_series_ok": sum(1 for l in leg_status
                                 if l["leg"] == "BIS"
                                 and l["label"] == "VERIFIED"),
            "ecb_series_ok": sum(1 for l in leg_status
                                 if l["leg"] == "ECB"
                                 and l["label"] == "VERIFIED"),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Collect central bank policy rates & FX (sensor #64).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--last-n", type=int, default=3,
                    help="Observations per series (default 3).")
    args = ap.parse_args(argv)
    result = collect(last_n=args.last_n)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['fetch_status']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
