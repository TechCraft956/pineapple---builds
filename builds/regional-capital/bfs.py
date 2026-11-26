#!/usr/bin/env python3
"""Census Business Formation Statistics (BFS) collector — Pineapple
sensor #55 (regional capital).

Read-only collector for the U.S. Census Bureau's Business Formation
Statistics, filtered to Starr County, TX (FIPS 48427), with nearby Rio
Grande Valley counties available as a secondary set.

Key finding (verified 2026-11-26): the BFS *API* is key-blocked —
``api.census.gov`` answers the BFS endpoint with a "Missing Key" page
since the May 2026 Census API key mandate. The bulk downloads on
census.gov are NOT key-gated, so the county leg is built on them:

Leg 1 — Annual county workbook (PRIMARY, county-level):
    https://www.census.gov/econ/bfs/xlsx/bfs_county_apps_annual.xlsx
    One row per county, columns BA2005..BA2025 (business applications
    = EIN requests per year). Released annually, ~6 months after year's
    end. Parsed with stdlib zipfile + xml.etree (no dependency).
Leg 2 — Weekly state CSV (SECONDARY, Texas-level recency):
    https://www.census.gov/econ/bfs/csv/bfs_state_apps_weekly_nsa.csv
    Columns Year,Week,State,BA_NSA,HBA_NSA,WBA_NSA,CBA_NSA (+ YY_*
    year-over-year). No county split exists at weekly frequency, so
    this leg is Texas-state context only, never presented as county
    data.
Leg 3 — BFS API (BLOCKED-needs-owner):
    https://api.census.gov/data/timeseries/bfs — monthly county-level
    series need a free Census API key (owner step:
    https://api.census.gov/data/key_signup.html). Recorded as BLOCKED,
    never worked around.

Disclosure note: the June 2026 county release applies differentially
private geometric noise to county counts (Census DRB approval
CBDRB-FY26-0109, noted in the workbook itself). County figures are
therefore noisy estimates, not exact counts — small differences are
not meaningful. The workbook header says so; this collector repeats
it in every output document.

Labels
------
VERIFIED  value present in the source file and parseable as an integer.
REPORTED  row present but the value cell is empty/unparseable. The row
          is real; the gap is recorded, never zero-filled.
UNKNOWN   not used by the county/state legs (both are keyed by FIPS or
          state code); reserved for any future fallback match.
BLOCKED   the API leg only (see Leg 3).

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

COUNTY_XLSX_URL = ("https://www.census.gov/econ/bfs/xlsx/"
                   "bfs_county_apps_annual.xlsx")
STATE_WEEKLY_CSV_URL = ("https://www.census.gov/econ/bfs/csv/"
                        "bfs_state_apps_weekly_nsa.csv")
BFS_DATA_PAGE = "https://www.census.gov/econ/bfs/data.html"
BFS_API_URL = "https://api.census.gov/data/timeseries/bfs"
CENSUS_KEY_SIGNUP = "https://api.census.gov/data/key_signup.html"

FIPS_STARR_COUNTY_TX = "48427"

# census.gov rejects requests with urllib's default User-Agent (HTTP
# 403); a plain identifying UA is accepted (verified 2026-11-26).
USER_AGENT = "Pineapple-Sensor-BFS/1.0 (public-data research collector)"


def _open(url: str, timeout: int, opener=None):
    """Open a URL with an identifying User-Agent header."""
    open_fn = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return open_fn(req, timeout=timeout)

# Secondary Rio Grande Valley counties (optional, --include-rgv).
RGV_COUNTIES = {"HIDALGO": "48215", "CAMERON": "48061", "WILLACY": "48489"}

XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_MAIN = f"{{{XLSX_NS}}}"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def _col_index(ref: str) -> int:
    """Column letters (A, B, …, AA) of a cell ref like 'C5' → 0-based index."""
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return -1
    idx = 0
    for ch in letters.group(1):
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def parse_county_xlsx(data: bytes) -> list[dict]:
    """Parse the BFS annual county workbook into raw row dicts.

    Returns one dict per county row: state, county, county_fips and
    BA<year> ints (or None when the cell is empty/unparseable).
    Cells are placed by their ``r`` attribute (column letters), not
    by position — sparse rows omit empty cells entirely.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        try:
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or ""
                               for t in si.iter(f"{XLSX_MAIN}t"))
                       for si in ss_root]
        except KeyError:
            strings = []
        ws_root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows: list[dict] = []
    header: list[str] | None = None
    for row_el in ws_root.iter(f"{XLSX_MAIN}row"):
        cells: list = []
        for c in row_el.findall(f"{XLSX_MAIN}c"):
            idx = _col_index(c.get("r"))
            if idx < 0:
                continue
            while len(cells) <= idx:
                cells.append(None)
            v_el = c.find(f"{XLSX_MAIN}v")
            if v_el is None or v_el.text is None:
                continue
            if c.get("t") == "s":
                s_idx = int(v_el.text)
                cells[idx] = strings[s_idx] if s_idx < len(strings) else None
            else:
                cells[idx] = v_el.text
        if not cells or all(v is None for v in cells):
            continue
        if header is None:
            if cells[0] == "State" and cells[1] == "County":
                header = [str(v) if v is not None else "" for v in cells]
            continue
        row = dict(zip(header, cells))
        if not row.get("County Code"):
            continue
        rows.append(row)
    return rows


def build_county_observations(rows: list[dict], source_url: str,
                              retrieved_at: str,
                              include_rgv: bool = False) -> list[dict]:
    """Emit one observation per year for Starr (and optional RGV)."""
    wanted = {"STARR": FIPS_STARR_COUNTY_TX}
    if include_rgv:
        wanted.update({k.title(): v for k, v in RGV_COUNTIES.items()})
    observations: list[dict] = []
    for row in rows:
        county_name = (row.get("County") or "").strip()
        fips = (row.get("County Code") or "").strip()
        scope = None
        for name, want_fips in wanted.items():
            if fips == want_fips:
                scope = "starr" if name == "STARR" else "rgv"
                break
        if scope is None:
            continue
        for key in sorted(row):
            if not key.startswith("BA") or len(key) != 6 \
                    or not key[2:].isdigit():
                continue
            year = int(key[2:])
            value = _to_int(row.get(key))
            observations.append({
                "series": "business_applications_annual_county",
                "scope": scope,
                "state": (row.get("State") or "").strip() or None,
                "county": county_name or None,
                "county_fips": fips,
                "year": year,
                "business_applications": value,
                "label": "VERIFIED" if value is not None else "REPORTED",
                "source_url": source_url,
                "retrieved_at": retrieved_at,
            })
    observations.sort(key=lambda o: (o["county_fips"], o["year"]))
    return observations


def build_state_weekly_observations(text: str, source_url: str,
                                    retrieved_at: str,
                                    weeks: int = 13) -> list[dict]:
    """Emit the most recent ``weeks`` Texas rows from the weekly CSV."""
    reader = csv.DictReader(io.StringIO(text))
    tx_rows = [r for r in reader if (r.get("State") or "").strip() == "TX"]
    tx_rows.sort(key=lambda r: (int(r.get("Year") or 0),
                                int(r.get("Week") or 0)))
    observations: list[dict] = []
    for r in tx_rows[-weeks:] if weeks > 0 else []:
        ba = _to_int(r.get("BA_NSA"))
        observations.append({
            "series": "business_applications_weekly_state",
            "scope": "texas_state_context",
            "state": "TX",
            "county": None,
            "county_fips": None,
            "year": _to_int(r.get("Year")),
            "week": _to_int(r.get("Week")),
            "business_applications": ba,
            "high_propensity_applications": _to_int(r.get("HBA_NSA")),
            "applications_with_planned_wages": _to_int(r.get("WBA_NSA")),
            "applications_from_corporations": _to_int(r.get("CBA_NSA")),
            "label": "VERIFIED" if ba is not None else "REPORTED",
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        })
    return observations


def fetch_observations(include_rgv: bool = False, state_weeks: int = 13,
                       opener=None) -> dict:
    """Fetch the live BFS bulk files and return the full result document."""
    retrieved_at = utcnow_iso()
    open_fn = (lambda url, timeout=None: _open(url, timeout, opener))
    legs: list[dict] = []
    observations: list[dict] = []

    # Leg 1 — annual county workbook.
    try:
        with open_fn(COUNTY_XLSX_URL, timeout=120) as resp:
            county_data = resp.read()
        rows = parse_county_xlsx(county_data)
        county_obs = build_county_observations(rows, COUNTY_XLSX_URL,
                                               retrieved_at,
                                               include_rgv=include_rgv)
        observations.extend(county_obs)
        legs.append({"leg": "county_annual_workbook", "url": COUNTY_XLSX_URL,
                     "status": "OK", "rows_in_file": len(rows),
                     "observations": len(county_obs)})
    except Exception as exc:  # network/file errors: recorded, not raised
        legs.append({"leg": "county_annual_workbook", "url": COUNTY_XLSX_URL,
                     "status": f"ERROR: {type(exc).__name__}: {exc}",
                     "rows_in_file": 0, "observations": 0})

    # Leg 2 — weekly state CSV (Texas context).
    if state_weeks > 0:
        try:
            with open_fn(STATE_WEEKLY_CSV_URL, timeout=120) as resp:
                csv_text = resp.read().decode("utf-8", "replace")
            state_obs = build_state_weekly_observations(
                csv_text, STATE_WEEKLY_CSV_URL, retrieved_at,
                weeks=state_weeks)
            observations.extend(state_obs)
            legs.append({"leg": "state_weekly_csv",
                         "url": STATE_WEEKLY_CSV_URL, "status": "OK",
                         "rows_in_file": csv_text.count("\n"),
                         "observations": len(state_obs)})
        except Exception as exc:
            legs.append({"leg": "state_weekly_csv",
                         "url": STATE_WEEKLY_CSV_URL,
                         "status": f"ERROR: {type(exc).__name__}: {exc}",
                         "rows_in_file": 0, "observations": 0})

    # Leg 3 — BFS API: key-blocked, recorded, never worked around.
    legs.append({
        "leg": "bfs_api_monthly_county",
        "url": BFS_API_URL,
        "status": "BLOCKED-needs-owner",
        "reason": "api.census.gov answers the BFS endpoint with a "
                  "'Missing Key' page without an API key (Census API "
                  "key mandate, May 2026; verified 2026-11-26). "
                  "Monthly county-level series need a free Census API "
                  "key.",
        "owner_step": f"Create a free Census API key at {CENSUS_KEY_SIGNUP} "
                      "and re-run with the key.",
        "rows_in_file": 0,
        "observations": 0,
    })

    starr = [o for o in observations if o["scope"] == "starr"]
    starr_years = {o["year"]: o["business_applications"] for o in starr}
    return {
        "sensor": "census-bfs-55",
        "source": "U.S. Census Bureau, Business Formation Statistics",
        "data_page": BFS_DATA_PAGE,
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "include_rgv_secondary": include_rgv,
        "disclosure_note": "The June 2026 county release applies "
                           "differentially private geometric noise to "
                           "county counts (Census DRB approval "
                           "CBDRB-FY26-0109). County figures are noisy "
                           "estimates, not exact counts; small "
                           "differences are not meaningful.",
        "legs": legs,
        "summary": {
            "observations_total": len(observations),
            "starr_county_years": len(starr),
            "by_label": {lab: sum(1 for o in observations
                                  if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN",
                                     "BLOCKED")},
            "starr_latest_year": max(starr_years) if starr_years else None,
            "starr_latest_value": (starr_years[max(starr_years)]
                                   if starr_years else None),
            "starr_earliest_year": min(starr_years) if starr_years else None,
            "starr_earliest_value": (starr_years[min(starr_years)]
                                     if starr_years else None),
            "starr_change_since_2019": (
                starr_years[max(starr_years)] - starr_years[2019]
                if starr_years and 2019 in starr_years
                and max(starr_years) in starr_years
                and starr_years[max(starr_years)] is not None
                and starr_years[2019] is not None else None),
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch Census BFS business applications, Starr County, TX.")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--include-rgv", action="store_true",
                    help="Also collect Hidalgo/Cameron/Willacy as secondary.")
    ap.add_argument("--state-weeks", type=int, default=13,
                    help="Recent Texas weekly rows to include (0 to skip).")
    args = ap.parse_args(argv)
    result = fetch_observations(include_rgv=args.include_rgv,
                                state_weeks=args.state_weeks)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['summary']['starr_county_years']} Starr County "
              f"years)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
