#!/usr/bin/env python3
"""BLS Local Area Unemployment Statistics (LAUS) collector — Pineapple
sensor #101 (regional labor; Wave 4 deficit sweep, 2026-11-26).

Read-only collector for monthly unemployment / labor-force estimates
for Starr County, TX (FIPS 48427), the McAllen-Edinburg-Mission MSA
(CBSA 32580), and Texas statewide context.

Why this sensor exists: Wave 4's #51 (QCEW + WARN) covers jobs and
layoffs but the inventory had NO county unemployment-rate sensor at
all — the most basic labor-market gauge was missing. LAUS is the
monthly, not-seasonally-adjusted series for it.

Source
------
BLS public API v1 (keyless, no signup, $0):
    POST https://api.bls.gov/publicAPI/v1/timeseries/data/<ids>
    {"startyear": YYYY, "endyear": YYYY}
v1 allows 25 queries/day without a key and 10 years per query — the
default 2-year window uses one query per run. A v2 key would raise
the limits but is not needed at this cadence (monthly).

Series IDs (LAUS format: LAU + area type + area code + measure):
    Starr County  LAUCN4842700000000<mm>   (CN = county, FIPS 48427)
    McAllen MSA   LAUMT4832580000000<mm>   (MT = metro, CBSA 32580)
    Texas         LAUST4800000000000<mm>   (ST = state, FIPS 48)
Measures: 03 unemployment rate (%), 04 unemployed (persons),
05 employed (persons), 06 civilian labor force (persons).
County/MSA series are NOT seasonally adjusted; the national
comparison is therefore the NSA CPS rate, not the headline SA rate.

Labels
------
VERIFIED  value present in the API response and parseable as a number.
REPORTED  month present but the value is missing/unparseable. The
          row is real; the gap is recorded, never zero-filled.
UNKNOWN   not used (every series is keyed by area + measure).

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

BLS_API_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

FIPS_STARR_COUNTY_TX = "48427"
MSA_CBSA_MCALLEN = "32580"

# RGV counties for the optional secondary set (county FIPS).
RGV_COUNTIES = {"HIDALGO": "48215", "CAMERON": "48061", "WILLACY": "48489"}

MEASURES = {
    "03": "unemployment_rate",
    "04": "unemployed",
    "05": "employed",
    "06": "labor_force",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def series_id(area_type: str, area_code: str, measure: str) -> str:
    """Build a LAUS series ID: LAU + type + code + zeros + measure."""
    if area_type == "CN":
        core = f"{area_code}00000000"
    elif area_type == "MT":
        core = f"48{area_code}000000"
    elif area_type == "ST":
        core = f"{area_code}00000000000"
    else:  # pragma: no cover - guarded by callers
        raise ValueError(f"unknown area type {area_type}")
    return f"LAU{area_type}{core}{measure}"


def build_series_list(include_rgv: bool = False) -> list[dict]:
    """Series to fetch: (series_id, area, measure) triples."""
    areas = [
        ("CN", FIPS_STARR_COUNTY_TX, "starr", "Starr County, TX"),
        ("MT", MSA_CBSA_MCALLEN, "msa",
         "McAllen-Edinburg-Mission, TX MSA"),
        ("ST", "48", "texas", "Texas"),
    ]
    if include_rgv:
        for name, fips in sorted(RGV_COUNTIES.items()):
            areas.append(("CN", fips, "rgv", f"{name.title()} County, TX"))
    out = []
    for area_type, code, scope, label in areas:
        for measure, measure_name in MEASURES.items():
            out.append({
                "series_id": series_id(area_type, code, measure),
                "area": label,
                "scope": scope,
                "measure": measure_name,
            })
    return out


def _to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def parse_series_payload(payload: dict, meta_by_id: dict,
                         retrieved_at: str) -> list[dict]:
    """Project a BLS v1 response onto observations."""
    observations: list[dict] = []
    for series in payload.get("Results", {}).get("series", []):
        meta = meta_by_id.get(series.get("seriesID"))
        if meta is None:
            continue
        for item in series.get("data", []):
            value = _to_float(item.get("value"))
            footnotes = item.get("footnotes") or []
            observations.append({
                "series_id": series.get("seriesID"),
                "area": meta["area"],
                "scope": meta["scope"],
                "measure": meta["measure"],
                "year": int(item["year"]) if item.get("year") else None,
                "month": item.get("period"),
                "month_name": item.get("periodName"),
                "value": value,
                "preliminary": any(
                    (f.get("code") == "P") for f in footnotes),
                "label": "VERIFIED" if value is not None else "REPORTED",
                "source_url": BLS_API_URL + series.get("seriesID", ""),
                "retrieved_at": retrieved_at,
            })
    observations.sort(key=lambda o: (o["scope"], o["measure"],
                                     o["year"] or 0, o["month"] or ""))
    return observations


def fetch_observations(start_year: int = 2025, end_year: int = 2026,
                       include_rgv: bool = False,
                       opener=None, pause: float = 0.5) -> dict:
    """Fetch the live LAUS series and return the full result document.

    One POST per series: multi-series v1 requests answer HTTP 503 /
    BLS's "website is busy" page from this environment, while
    single-series requests succeed (verified 2026-11-26). Twelve
    queries per run (24 with --include-rgv) stays inside the keyless
    v1 limit of 25/day at a monthly cadence; a 0.5 s pause between
    requests keeps the pace polite.
    """
    retrieved_at = utcnow_iso()
    wanted = build_series_list(include_rgv=include_rgv)
    meta_by_id = {w["series_id"]: w for w in wanted}
    open_fn = opener or urllib.request.urlopen
    observations: list[dict] = []
    failures: list[str] = []
    for w in wanted:
        try:
            req = urllib.request.Request(
                BLS_API_URL + w["series_id"],
                data=json.dumps({"startyear": str(start_year),
                                 "endyear": str(end_year)}).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         # api.bls.gov answers 503 to urllib's default UA.
                         "User-Agent": "Pineapple-Sensor-LAUS/1.0 "
                                       "(public-data research collector)"},
                method="POST")
            with open_fn(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            if not isinstance(payload, dict) or \
                    payload.get("status") != "REQUEST_SUCCEEDED":
                failures.append(
                    f"{w['series_id']}: BLS status "
                    f"{payload.get('status') if isinstance(payload, dict) else 'non-JSON'}")
                continue
            observations.extend(parse_series_payload(payload, meta_by_id,
                                                     retrieved_at))
        except Exception as exc:  # network/API errors: recorded, not raised
            failures.append(
                f"{w['series_id']}: {type(exc).__name__}: {exc}")
        time.sleep(pause)
    status = ("OK" if not failures
              else f"{len(wanted) - len(failures)}/{len(wanted)} series OK; "
                   f"failures: {'; '.join(failures)}")
    observations.sort(key=lambda o: (o["scope"], o["measure"],
                                     o["year"] or 0, o["month"] or ""))

    starr_rate = [o for o in observations
                  if o["scope"] == "starr"
                  and o["measure"] == "unemployment_rate"]
    latest_rate = starr_rate[-1] if starr_rate else None
    return {
        "sensor": "bls-laus-101",
        "source": "U.S. Bureau of Labor Statistics, "
                  "Local Area Unemployment Statistics (LAUS)",
        "api": BLS_API_URL,
        "api_keyless_v1_limits": "25 queries/day, 10 years/query, "
                                 "50 series/query",
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "start_year": start_year,
        "end_year": end_year,
        "include_rgv_secondary": include_rgv,
        "fetch_status": status,
        "summary": {
            "observations_total": len(observations),
            "by_label": {lab: sum(1 for o in observations
                                  if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
            "series_requested": len(wanted),
            "starr_latest_rate": latest_rate,
            "starr_latest_rate_value": (latest_rate["value"]
                                        if latest_rate else None),
            "starr_latest_rate_month": (
                f"{latest_rate['year']}-{latest_rate['month']}"
                if latest_rate else None),
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch BLS LAUS unemployment data, Starr County, TX.")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--start-year", type=int, default=2025)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--include-rgv", action="store_true",
                    help="Also collect Hidalgo/Cameron/Willacy as secondary.")
    args = ap.parse_args(argv)
    result = fetch_observations(start_year=args.start_year,
                                end_year=args.end_year,
                                include_rgv=args.include_rgv)
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
