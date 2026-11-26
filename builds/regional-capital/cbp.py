#!/usr/bin/env python3
"""County Business Patterns (CBP) collector — Pineapple sensor #55
(second leg; Wave 4 deficit sweep, 2026-11-26).

Read-only collector for the U.S. Census Bureau's County Business
Patterns: establishment counts, employment and payroll by county and
NAICS, for Starr County, TX (FIPS 48427), with nearby Rio Grande
Valley counties available as a secondary set.

Why this leg exists: #55's own definition names "BFS … and CBP", but
the Wave 4 BFS collector covered only the Business Formation
Statistics bulk files. CBP is the other half — the stock of existing
businesses (BFS counts new EIN applications; CBP counts the
establishments that actually exist, by industry).

Source
------
Census CBP county ZIP (keyless, no signup, $0), one file per year:
    https://www2.census.gov/programs-surveys/cbp/datasets/{YYYY}/
        cbp{YY}co.zip
    e.g. https://www2.census.gov/programs-surveys/cbp/datasets/2023/
        cbp23co.zip
The ZIP holds one CSV (cbp{YY}co.txt, ~1.1M rows, all counties).
Columns used: fipstate, fipscty, naics, emp_nf, emp, qp1_nf, qp1,
ap_nf, ap, est, n<5 … n1000_4 (establishments by employment size
class). emp = paid employees (mid-March week); qp1 = first-quarter
payroll ($1,000); ap = annual payroll ($1,000); est = establishments.
Released annually, ~2 years after the reference year (2023 is the
latest verified 2026-11-26; bump --year when a new release lands).

Disclosure note: CBP applies noise to published values (the *_nf
flags). Values are published as-is with their flags carried in the
observation — small differences are not meaningful.

Labels
------
VERIFIED  row present with a parseable employee count.
REPORTED  row present but the employee count is empty/unparseable.
          The row is real; the gap is recorded, never zero-filled.
UNKNOWN   not used (every row is keyed by FIPS + NAICS).

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

CBP_BASE = "https://www2.census.gov/programs-surveys/cbp/datasets"
CBP_DATA_PAGE = "https://www.census.gov/programs-surveys/cbp/data/datasets.html"

# Latest CBP year verified live; bump when a new release is confirmed.
LATEST_YEAR = 2023

FIPS_STARR_COUNTY_TX = "48427"

# Secondary Rio Grande Valley counties (optional, --include-rgv).
RGV_COUNTIES = {"HIDALGO": "48215", "CAMERON": "48061", "WILLACY": "48489"}

# census.gov rejects requests with urllib's default User-Agent (HTTP
# 403); a plain identifying UA is accepted (verified 2026-11-26).
USER_AGENT = "Pineapple-Sensor-CBP/1.0 (public-data research collector)"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def cbp_zip_url(year: int) -> str:
    return f"{CBP_BASE}/{year}/cbp{str(year)[2:]}co.zip"


SIZE_CLASSES = ["n<5", "n5_9", "n10_19", "n20_49", "n50_99", "n100_249",
                "n250_499", "n500_999", "n1000", "n1000_1", "n1000_2",
                "n1000_3", "n1000_4"]


def naics_level(naics: str | None) -> str | None:
    """total (------) / sector (XX----) / subsector / industry."""
    if naics is None:
        return None
    if naics == "------":
        return "total"
    digits = sum(1 for ch in naics if ch.isdigit())
    if digits == 2:
        return "sector"
    if digits == 3:
        return "subsector"
    return "industry"


def build_observation(row: dict, source_url: str, retrieved_at: str,
                      scope: str) -> dict:
    naics = _clean(row.get("naics"))
    emp = _to_int(row.get("emp"))
    state_fips = _clean(row.get("fipstate"))
    county_code = _clean(row.get("fipscty"))
    county_fips = (state_fips + county_code
                   if state_fips and county_code else None)
    return {
        "series": "county_business_patterns",
        "scope": scope,
        "state": "TX",
        "county_fips": county_fips,
        "naics": naics,
        "naics_level": naics_level(naics),
        "employees": emp,
        "employees_noise_flag": _clean(row.get("emp_nf")),
        "payroll_q1_usd_1000": _to_int(row.get("qp1")),
        "payroll_q1_noise_flag": _clean(row.get("qp1_nf")),
        "annual_payroll_usd_1000": _to_int(row.get("ap")),
        "annual_payroll_noise_flag": _clean(row.get("ap_nf")),
        "establishments": _to_int(row.get("est")),
        "establishments_by_size": {
            cls: _to_int(row.get(cls)) for cls in SIZE_CLASSES
        },
        "label": "VERIFIED" if emp is not None else "REPORTED",
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }


def fetch_observations(year: int = LATEST_YEAR,
                       include_rgv: bool = False,
                       opener=None) -> dict:
    """Fetch the live CBP county file and return the result document."""
    retrieved_at = utcnow_iso()
    url = cbp_zip_url(year)
    open_fn = opener or urllib.request.urlopen
    observations: list[dict] = []
    status = "OK"
    rows_scanned = 0
    wanted_fips = {FIPS_STARR_COUNTY_TX[2:]}
    if include_rgv:
        wanted_fips.update(v[2:] for v in RGV_COUNTIES.values())
    try:
        req = urllib.request.Request(url,
                                     headers={"User-Agent": USER_AGENT})
        with open_fn(req, timeout=300) as resp:
            payload = resp.read()
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            member = [n for n in zf.namelist()
                      if n.endswith("co.txt")][0]
            with zf.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8",
                                        errors="replace", newline="")
                reader = csv.DictReader(text)
                for row in reader:
                    rows_scanned += 1
                    if (row.get("fipstate") or "").strip() != "48":
                        continue
                    fipscty = (row.get("fipscty") or "").strip()
                    if fipscty not in wanted_fips:
                        continue
                    scope = ("starr" if fipscty == "427" else "rgv")
                    observations.append(build_observation(
                        row, url, retrieved_at, scope))
    except Exception as exc:  # network/file errors: recorded, not raised
        status = f"ERROR: {type(exc).__name__}: {exc}"
    observations.sort(key=lambda o: (o["scope"], o["naics"] or ""))
    starr = [o for o in observations if o["scope"] == "starr"]
    total = next((o for o in starr if o["naics_level"] == "total"), None)
    sectors = sorted(
        (o for o in starr if o["naics_level"] == "sector"),
        key=lambda o: -(o["employees"] or 0))[:5]
    return {
        "sensor": "census-cbp-55",
        "source": "U.S. Census Bureau, County Business Patterns",
        "data_page": CBP_DATA_PAGE,
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "year": year,
        "file_url": url,
        "include_rgv_secondary": include_rgv,
        "disclosure_note": "CBP applies noise to published values "
                           "(the *_nf flags). Values are published "
                           "as-is with their flags; small differences "
                           "are not meaningful.",
        "fetch_status": status,
        "summary": {
            "rows_scanned": rows_scanned,
            "observations_total": len(observations),
            "starr_rows": len(starr),
            "by_label": {lab: sum(1 for o in observations
                                  if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
            "starr_total": total,
            "starr_top_sectors_by_employment": [
                {"naics": s["naics"], "employees": s["employees"],
                 "establishments": s["establishments"]} for s in sectors],
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch Census CBP county data, Starr County, TX.")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--year", type=int, default=LATEST_YEAR,
                    help="CBP reference year (default: latest verified).")
    ap.add_argument("--include-rgv", action="store_true",
                    help="Also collect Hidalgo/Cameron/Willacy as secondary.")
    args = ap.parse_args(argv)
    result = fetch_observations(year=args.year,
                                include_rgv=args.include_rgv)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['summary']['starr_rows']} Starr County rows, "
              f"{result['fetch_status']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
