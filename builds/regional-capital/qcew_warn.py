#!/usr/bin/env python3
"""BLS QCEW county employment/wages + TWC WARN layoffs — Pineapple sensor #51.

Read-only collector for hiring and the labor market in Starr County, TX
(FIPS 48427) and the McAllen-Edinburg-Mission MSA, with nearby Rio Grande
Valley counties (Hidalgo, Cameron, Willacy) as the WARN scope.

Leg 1 — QCEW (BLS Quarterly Census of Employment and Wages)
------------------------------------------------------------
Source: BLS QCEW area CSV slices, keyless, no signup, $0::

    https://data.bls.gov/cew/data/api/{year}/{qtr}/area/{area}.csv

Areas: ``48427`` (Starr County) and ``C3258`` (McAllen-Edinburg-Mission
MSA — the QCEW area code for CBSA 32580). One file per quarter is
fetched; the collector probes recent quarters newest-first and keeps
the newest ``--quarters`` (default 5) that return data. QCEW lags
roughly two quarters: as of 2026-11-26 the latest published quarter is
2026 Q1 (2026 Q2 is HTTP 404 — not yet released).

Per quarter the collector emits observations for:

- county total, all ownership (industry ``10``, own ``0``);
- private total (industry ``10``, own ``5``);
- government totals (industry ``10``, own ``1`` federal, ``2`` state,
  ``3`` local);
- the top 5 private 2-digit NAICS sectors by month-3 employment
  (non-suppressed rows only);
- the MSA total, all ownership (industry ``10``, own ``0``).

QCEW suppresses small cells for confidentiality (``disclosure_code``
non-empty blanks the figures). Suppressed rows are never emitted as
numbers — a sector that is suppressed simply does not appear, and the
run records how many rows were suppressed. Missing values stay
``null`` — never zero-filled, never invented.

Leg 2 — WARN (Texas Workforce Commission layoff notices)
--------------------------------------------------------
Source: TWC WARN page (no signup, $0)::

    https://www.twc.texas.gov/data-reports/warn-notice

The page links one Excel workbook per year (``warn-act-listings-YYYY-
twc.xlsx``). The collector downloads the workbooks for
``--warn-years`` (default: current year + prior year) and parses them
with stdlib ``zipfile`` + ``xml.etree`` (no openpyxl). Each workbook
has one sheet with columns NOTICE_DATE, JOB_SITE_NAME, COUNTY_NAME,
WDA_NAME, TOTAL_LAYOFF_NUMBER, LayOff_Date, WFDD_RECEIVED_DATE,
CITY_NAME. Dates are Excel serial numbers and are converted to ISO
dates. Only notices in Starr, Hidalgo, Cameron, or Willacy County
are emitted as observations; statewide notice/worker totals are kept
in the summary for context. Zero Starr County notices in a year is a
real finding and is reported as such, not as a fetch failure.

Labels
------
VERIFIED  all key fields present in the source record (QCEW: month-3
          employment + average weekly wage + establishments, with an
          empty disclosure code; WARN: employer, county, notice date
          and layoff number all present).
REPORTED  record present but a key field is missing/unparseable. The
          gap is recorded as ``null``, never zero-filled.
UNKNOWN   record present but its geography cannot be keyed (WARN row
          with a blank county; QCEW rows are keyed by file, so this
          does not normally occur there).

Every observation records its source URL and UTC retrieval timestamp.

Known live quirks (verified 2026-11-26)
----------------------------------------
- ``www.bls.gov/cew`` bulk ZIP downloads answer HTTP 403 from here
  (Akamai bot block, "Access Denied"). The ``data.bls.gov`` CSV-slice
  API above answers HTTP 200 — that is the path this collector uses.
  The BLS public API v1 (``api.bls.gov``) also answers HTTP 200, but
  no series-ID path was needed once the CSV slices worked.
- The MSA area code is ``C3258``, not ``C32580`` (``C32580`` is
  HTTP 404); ``32580`` bare is also HTTP 404.
- BLS does **not** publish MSA ownership breakdowns in the area
  slice: the industry-``10`` rows for own ``1``/``2``/``3``/``5``
  carry placeholder 0s with disclosure code ``-``. The collector
  emits those as ``null`` + REPORTED, never as 0. The 2026Q1 MSA
  slice contains only the all-ownership total row (2 lines) — MSA
  detail lags the county file by a quarter.
- The 2025 WARN workbook has 754 physical sheet rows but only 289
  real notices: rows 291–754 are empty formatted ghost rows (styled
  cells with no values) from TWC's export template. The parser skips
  them; the statewide count is the real-notice count, not the
  physical row count.
- The TWC WARN page moved: the old ``/businesses/warn`` path is
  HTTP 404. The live page is ``/data-reports/warn-notice``.
- The 2025 WARN workbook contains ragged rows (trailing empty cells);
  the parser pads short rows instead of failing.

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
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

QCEW_BASE = "https://data.bls.gov/cew/data/api/{year}/{qtr}/area/{area}.csv"
WARN_PAGE_URL = "https://www.twc.texas.gov/data-reports/warn-notice"
WARN_XLSX_URL = ("https://www.twc.texas.gov/sites/default/files/oei/docs/"
                 "warn-act-listings-{year}-twc.xlsx")

FIPS_STARR_COUNTY_TX = "48427"
MSA_AREA_CODE = "C3258"  # QCEW area code for McAllen-Edinburg-Mission, CBSA 32580
MSA_NAME = "McAllen-Edinburg-Mission, TX"

# WARN scope: Starr + the other Rio Grande Valley counties.
RGV_COUNTIES = {"STARR", "HIDALGO", "CAMERON", "WILLACY"}

# 2-digit NAICS sector titles (only the codes QCEW publishes at county
# level are listed; the collector never invents a title for an unknown code).
NAICS_2DIGIT = {
    "11": "Agriculture, forestry, fishing and hunting",
    "21": "Mining, quarrying, and oil and gas extraction",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "42": "Wholesale trade",
    "44": "Retail trade",
    "48": "Transportation and warehousing",
    "51": "Information",
    "52": "Finance and insurance",
    "53": "Real estate and rental and leasing",
    "54": "Professional, scientific, and technical services",
    "55": "Management of companies and enterprises",
    "56": "Administrative and support and waste management",
    "61": "Educational services",
    "62": "Health care and social assistance",
    "71": "Arts, entertainment, and recreation",
    "72": "Accommodation and food services",
    "81": "Other services (except public administration)",
    "92": "Public administration",
}

OWNERSHIP_LABELS = {
    "0": "all ownership",
    "1": "federal government",
    "2": "state government",
    "3": "local government",
    "5": "private",
}

XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXCEL_EPOCH = date(1899, 12, 30)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value):
    """Strip whitespace; empty strings become None (never zero-filled)."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _to_int(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def _to_float(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def excel_serial_to_iso(value):
    """Convert an Excel serial date (days since 1899-12-30) to ISO date.

    Returns None for blank / non-numeric values. Serials are how TWC
    stores NOTICE_DATE, LayOff_Date and WFDD_RECEIVED_DATE.
    """
    try:
        if value is None or str(value).strip() == "":
            return None
        serial = int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None
    if serial <= 0:
        return None
    try:
        return (EXCEL_EPOCH + timedelta(days=serial)).isoformat()
    except (OverflowError, ValueError):
        return None


def candidate_quarters(today: date | None = None) -> list[tuple[int, int]]:
    """Recent QCEW quarters newest-first, allowing for the ~2-quarter lag.

    Starts one quarter past the latest plausible release (so a fresh
    release is picked up automatically) and walks back 7 quarters.
    """
    today = today or date.today()
    q = (today.month - 1) // 3 + 1
    year = today.year
    # Latest plausible published quarter: two quarters ago.
    for _ in range(2):
        q -= 1
        if q == 0:
            q = 4
            year -= 1
    # One quarter newer than plausible, as a probe for a fresh release.
    probe_q, probe_y = q + 1, year
    if probe_q == 5:
        probe_q, probe_y = 1, year + 1
    out = [(probe_y, probe_q)]
    y, qq = year, q
    for _ in range(7):
        out.append((y, qq))
        qq -= 1
        if qq == 0:
            qq = 4
            y -= 1
    return out


def fetch_qcew_area(area: str, year: int, qtr: int,
                    opener=None) -> tuple[list[dict], str]:
    """Fetch one QCEW area CSV slice. Returns (rows, status).

    ``status`` is ``OK`` on a parsed file, otherwise ``HTTP_<code>`` or
    ``ERROR: <type>: <message>``. Rows are raw dicts from the CSV.
    """
    url = QCEW_BASE.format(year=year, qtr=qtr, area=area)
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(url, timeout=120) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status is not None:
            return [], f"HTTP_{status}"
        return [], f"ERROR: {type(exc).__name__}: {exc}"
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc:  # malformed CSV: recorded, not raised
        return [], f"ERROR: {type(exc).__name__}: {exc}"
    if not rows or "area_fips" not in (rows[0] or {}):
        return [], "ERROR: unexpected CSV content (no area_fips column)"
    return rows, "OK"


def build_qcew_observations(rows: list[dict], area: str, year: int, qtr: int,
                            source_url: str, retrieved_at: str) -> list[dict]:
    """Project one quarter of one QCEW area file onto observations.

    Emits the county/MSA total, private + government totals, and the
    top 5 private 2-digit NAICS sectors by month-3 employment among
    non-suppressed rows. Suppressed rows are skipped (counted by the
    caller via ``disclosure_code``).
    """
    period = f"{year}Q{qtr}"
    scope = "starr" if area == FIPS_STARR_COUNTY_TX else "msa"
    obs: list[dict] = []

    def total_obs(own: str, kind: str):
        row = next((r for r in rows
                    if r.get("industry_code") == "10"
                    and r.get("own_code") == own), None)
        if row is None:
            return
        # A non-empty disclosure code means BLS withheld the cell: the
        # file carries placeholder 0s for the measures (MSA ownership
        # totals are published this way — disclosure '-'). Withheld
        # figures are emitted as null, never as the placeholder 0.
        suppressed = bool(_clean(row.get("disclosure_code")))
        o = {
            "leg": "qcew",
            "kind": kind,
            "scope": scope,
            "area": area,
            "county_fips": FIPS_STARR_COUNTY_TX if scope == "starr" else None,
            "area_name": ("Starr County, TX" if scope == "starr"
                          else MSA_NAME),
            "period": period,
            "year": year,
            "quarter": qtr,
            "industry_code": "10",
            "industry_title": "Total, all industries",
            "ownership_code": own,
            "ownership": OWNERSHIP_LABELS.get(own),
            "establishments": (None if suppressed
                               else _to_int(row.get("qtrly_estabs"))),
            "employment_month1": (None if suppressed
                                  else _to_int(row.get("month1_emplvl"))),
            "employment_month2": (None if suppressed
                                  else _to_int(row.get("month2_emplvl"))),
            "employment_month3": (None if suppressed
                                  else _to_int(row.get("month3_emplvl"))),
            "total_quarterly_wages": (None if suppressed
                                      else _to_int(
                                          row.get("total_qtrly_wages"))),
            "avg_weekly_wage": (None if suppressed
                                else _to_int(row.get("avg_wkly_wage"))),
            "disclosure_suppressed": suppressed,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        }
        o["label"] = ("VERIFIED"
                      if o["employment_month3"] is not None
                      and o["avg_weekly_wage"] is not None
                      and o["establishments"] is not None
                      and not o["disclosure_suppressed"]
                      else "REPORTED")
        obs.append(o)

    total_obs("0", "area_total")
    total_obs("5", "private_total")
    for own, kind in (("1", "federal_total"), ("2", "state_total"),
                      ("3", "local_total")):
        total_obs(own, kind)

    sectors = [r for r in rows
               if len(_clean(r.get("industry_code")) or "") == 2
               and _clean(r.get("industry_code")) != "10"
               and _clean(r.get("own_code")) == "5"
               and not _clean(r.get("disclosure_code"))]
    sectors.sort(key=lambda r: _to_int(r.get("month3_emplvl")) or 0,
                 reverse=True)
    for row in sectors[:5]:
        code = _clean(row.get("industry_code"))
        o = {
            "leg": "qcew",
            "kind": "sector",
            "scope": scope,
            "area": area,
            "county_fips": (FIPS_STARR_COUNTY_TX if scope == "starr"
                            else None),
            "area_name": ("Starr County, TX" if scope == "starr"
                          else MSA_NAME),
            "period": period,
            "year": year,
            "quarter": qtr,
            "industry_code": code,
            "industry_title": NAICS_2DIGIT.get(code),
            "ownership_code": "5",
            "ownership": "private",
            "establishments": _to_int(row.get("qtrly_estabs")),
            "employment_month1": _to_int(row.get("month1_emplvl")),
            "employment_month2": _to_int(row.get("month2_emplvl")),
            "employment_month3": _to_int(row.get("month3_emplvl")),
            "total_quarterly_wages": _to_int(row.get("total_qtrly_wages")),
            "avg_weekly_wage": _to_int(row.get("avg_wkly_wage")),
            "disclosure_suppressed": False,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
        }
        o["label"] = ("VERIFIED"
                      if o["employment_month3"] is not None
                      and o["avg_weekly_wage"] is not None
                      and o["establishments"] is not None
                      else "REPORTED")
        obs.append(o)
    return obs


def parse_warn_xlsx(data: bytes) -> tuple[list[dict], list[str]]:
    """Parse a TWC WARN workbook (bytes) into raw row dicts.

    Returns (rows, header). Only stdlib zipfile + ElementTree; the
    workbook is a single sheet with a shared-strings table. Short
    (ragged) rows are padded with None instead of failing.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{{{XLSX_NS}}}si"):
                shared.append("".join(
                    t.text or "" for t in si.iter(f"{{{XLSX_NS}}}t")))
        sheet_name = next((n for n in names
                           if n.startswith("xl/worksheets/sheet")
                           and n.endswith(".xml")), None)
        if sheet_name is None:
            return [], []
        sheet = ET.fromstring(zf.read(sheet_name))
    grid: list[list[str | None]] = []
    for row_el in sheet.findall(f".//{{{XLSX_NS}}}row"):
        cells: list[str | None] = []
        for c in row_el.findall(f"{{{XLSX_NS}}}c"):
            v_el = c.find(f"{{{XLSX_NS}}}v")
            val = v_el.text if v_el is not None else None
            if c.get("t") == "s" and val is not None:
                try:
                    val = shared[int(val)]
                except (ValueError, IndexError):
                    val = None
            cells.append(val)
        grid.append(cells)
    if not grid:
        return [], []
    header = [_clean(c) or "" for c in grid[0]]
    rows: list[dict] = []
    for cells in grid[1:]:
        if all(c is None or str(c).strip() == "" for c in cells):
            continue
        padded = list(cells) + [None] * (len(header) - len(cells))
        rows.append({h: padded[i] for i, h in enumerate(header) if h})
    return rows, header


def build_warn_observation(row: dict, source_url: str,
                           retrieved_at: str) -> dict | None:
    """Project one WARN row onto the observation schema.

    Returns None when the row's county is outside the RGV scope; the
    caller counts those as out-of-scope, not as missing data.
    """
    county = _clean(row.get("COUNTY_NAME"))
    county_key = county.upper() if county else None
    if county_key not in RGV_COUNTIES:
        return None
    notice_date = excel_serial_to_iso(row.get("NOTICE_DATE"))
    layoff_date = excel_serial_to_iso(row.get("LayOff_Date"))
    received_date = excel_serial_to_iso(row.get("WFDD_RECEIVED_DATE"))
    workers = _to_int(row.get("TOTAL_LAYOFF_NUMBER"))
    obs = {
        "leg": "warn",
        "kind": "layoff_notice",
        "scope": "starr" if county_key == "STARR" else "rgv",
        "county": county,
        "county_fips": (FIPS_STARR_COUNTY_TX if county_key == "STARR"
                        else None),
        "city": _clean(row.get("CITY_NAME")),
        "employer": _clean(row.get("JOB_SITE_NAME")),
        "workforce_area": _clean(row.get("WDA_NAME")),
        "workers_affected": workers,
        "notice_date": notice_date,
        "layoff_date": layoff_date,
        "received_date": received_date,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    if county_key is None:
        obs["label"] = "UNKNOWN"
    elif (obs["employer"] is not None and notice_date is not None
            and workers is not None):
        obs["label"] = "VERIFIED"
    else:
        obs["label"] = "REPORTED"
    return obs


def fetch_warn_year(year: int, opener=None) -> tuple[bytes | None, str, str]:
    """Download one TWC WARN workbook. Returns (bytes, status, url)."""
    url = WARN_XLSX_URL.format(year=year)
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(url, timeout=120) as resp:
            return resp.read(), "OK", url
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status is not None:
            return None, f"HTTP_{status}", url
        return None, f"ERROR: {type(exc).__name__}: {exc}", url


def fetch_warn_page(opener=None) -> tuple[str, str]:
    """Fetch the TWC WARN landing page (REPORTED evidence of the list).

    Returns (status, note): ``status`` is ``OK`` when the page was
    read; ``note`` records the year links found on the page, or the
    error. The page itself is not parsed for notices — the workbooks
    are the data.
    """
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(WARN_PAGE_URL, timeout=60) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        status = getattr(exc, "code", None)
        if status is not None:
            return f"HTTP_{status}", f"page fetch failed: HTTP {status}"
        return f"ERROR: {type(exc).__name__}: {exc}", f"page fetch failed: {exc}"
    import re
    years = sorted(set(re.findall(r"warn-act-listings-(20\d\d)-twc\.xlsx",
                                  html)))
    return "OK", ("WARN page lists Excel workbooks for years: "
                  + (", ".join(years) if years else "none found in page"))


def fetch_observations(quarters: int = 5,
                       warn_years: list[int] | None = None,
                       opener=None) -> dict:
    """Fetch QCEW + WARN live and return the full result document."""
    retrieved_at = utcnow_iso()
    today = date.today()
    if warn_years is None:
        warn_years = [today.year, today.year - 1]
    observations: list[dict] = []
    files: list[dict] = []
    legs: dict[str, dict] = {}

    # ---- Leg 1: QCEW ----
    good_quarters: list[tuple[int, int]] = []
    for year, qtr in candidate_quarters(today):
        if len(good_quarters) >= quarters:
            break
        rows, status = fetch_qcew_area(FIPS_STARR_COUNTY_TX, year, qtr,
                                       opener=opener)
        url = QCEW_BASE.format(year=year, qtr=qtr,
                               area=FIPS_STARR_COUNTY_TX)
        files.append({"leg": "qcew", "area": FIPS_STARR_COUNTY_TX,
                      "year": year, "quarter": qtr, "url": url,
                      "status": status,
                      "rows": len(rows) if status == "OK" else 0,
                      "suppressed_rows": sum(
                          1 for r in rows if _clean(r.get("disclosure_code")))
                      if status == "OK" else 0})
        if status == "OK" and rows:
            good_quarters.append((year, qtr))
            observations.extend(build_qcew_observations(
                rows, FIPS_STARR_COUNTY_TX, year, qtr, url, retrieved_at))
            msa_rows, msa_status = fetch_qcew_area(
                MSA_AREA_CODE, year, qtr, opener=opener)
            msa_url = QCEW_BASE.format(year=year, qtr=qtr,
                                       area=MSA_AREA_CODE)
            files.append({"leg": "qcew", "area": MSA_AREA_CODE,
                          "year": year, "quarter": qtr, "url": msa_url,
                          "status": msa_status,
                          "rows": len(msa_rows) if msa_status == "OK" else 0,
                          "suppressed_rows": sum(
                              1 for r in msa_rows
                              if _clean(r.get("disclosure_code")))
                          if msa_status == "OK" else 0})
            if msa_status == "OK" and msa_rows:
                observations.extend(build_qcew_observations(
                    msa_rows, MSA_AREA_CODE, year, qtr, msa_url,
                    retrieved_at))
    legs["qcew"] = {
        "status": ("OK" if good_quarters else "BLOCKED-no-data"),
        "latest_period": (f"{good_quarters[0][0]}Q{good_quarters[0][1]}"
                          if good_quarters else None),
        "quarters_covered": [f"{y}Q{q}" for y, q in good_quarters],
        "note": ("QCEW lags ~2 quarters; newest file that returns data "
                 "is the latest published quarter."),
    }

    # ---- Leg 2: WARN ----
    page_status, page_note = fetch_warn_page(opener=opener)
    warn_files: list[dict] = []
    statewide_notices = 0
    statewide_workers = 0
    for year in warn_years:
        data, status, url = fetch_warn_year(year, opener=opener)
        entry: dict = {"leg": "warn", "year": year, "url": url,
                       "status": status, "notices_statewide": 0,
                       "notices_rgv": 0, "workers_rgv": 0}
        if status == "OK" and data:
            try:
                rows, _header = parse_warn_xlsx(data)
            except Exception as exc:
                entry["status"] = (f"ERROR: {type(exc).__name__}: {exc}")
                rows = []
            entry["notices_statewide"] = len(rows)
            statewide_notices += len(rows)
            statewide_workers += sum(
                _to_int(r.get("TOTAL_LAYOFF_NUMBER")) or 0 for r in rows)
            for row in rows:
                obs = build_warn_observation(row, url, retrieved_at)
                if obs is None:
                    continue
                entry["notices_rgv"] += 1
                if obs["workers_affected"] is not None:
                    entry["workers_rgv"] += obs["workers_affected"]
                observations.append(obs)
        warn_files.append(entry)
    files.extend(warn_files)
    legs["warn"] = {
        "status": ("OK" if any(f["status"] == "OK" for f in warn_files)
                   else "BLOCKED-no-data"),
        "page_status": page_status,
        "page_note": page_note,
        "page_url": WARN_PAGE_URL,
        "years": warn_years,
    }

    qcew_obs = [o for o in observations if o["leg"] == "qcew"]
    warn_obs = [o for o in observations if o["leg"] == "warn"]
    starr_q = [o for o in qcew_obs
               if o["scope"] == "starr" and o["kind"] == "area_total"]
    starr_latest = starr_q[0] if starr_q else None
    msa_q = [o for o in qcew_obs
             if o["scope"] == "msa" and o["kind"] == "area_total"]
    msa_latest = msa_q[0] if msa_q else None
    return {
        "sensor": "qcew-warn-51",
        "source": ("BLS Quarterly Census of Employment and Wages (QCEW) + "
                   "Texas Workforce Commission WARN layoff notices"),
        "qcew_source": "https://www.bls.gov/cew/",
        "warn_source_page": WARN_PAGE_URL,
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "msa": MSA_NAME,
        "msa_area_code": MSA_AREA_CODE,
        "warn_scope_counties": sorted(RGV_COUNTIES),
        "legs": legs,
        "files": files,
        "summary": {
            "observations_total": len(observations),
            "qcew_observations": len(qcew_obs),
            "warn_observations": len(warn_obs),
            "by_label": {lab: sum(1 for o in observations
                                  if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
            "qcew_quarters": legs["qcew"]["quarters_covered"],
            "qcew_latest_period": legs["qcew"]["latest_period"],
            "starr_latest": {
                "period": starr_latest["period"] if starr_latest else None,
                "establishments": (starr_latest["establishments"]
                                   if starr_latest else None),
                "employment_month3": (starr_latest["employment_month3"]
                                      if starr_latest else None),
                "avg_weekly_wage": (starr_latest["avg_weekly_wage"]
                                     if starr_latest else None),
                "total_quarterly_wages": (starr_latest["total_quarterly_wages"]
                                          if starr_latest else None),
            },
            "msa_latest": {
                "period": msa_latest["period"] if msa_latest else None,
                "establishments": (msa_latest["establishments"]
                                   if msa_latest else None),
                "employment_month3": (msa_latest["employment_month3"]
                                      if msa_latest else None),
                "avg_weekly_wage": (msa_latest["avg_weekly_wage"]
                                     if msa_latest else None),
                "total_quarterly_wages": (msa_latest["total_quarterly_wages"]
                                          if msa_latest else None),
            },
            "warn_statewide_notices": statewide_notices,
            "warn_statewide_workers": statewide_workers,
            "warn_rgv_notices": len(warn_obs),
            "warn_rgv_workers": sum(o["workers_affected"] or 0
                                    for o in warn_obs),
            "warn_starr_notices": sum(
                1 for o in warn_obs if o["scope"] == "starr"),
            "warn_by_county": {c: sum(1 for o in warn_obs
                                      if (o.get("county") or "").upper() == c)
                               for c in sorted(RGV_COUNTIES)},
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch BLS QCEW county/MSA employment & wages and "
                    "TWC WARN layoff notices for Starr County / RGV.")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--quarters", type=int, default=5,
                    help="Trailing QCEW quarters to collect (default: 5).")
    ap.add_argument("--warn-years", type=int, nargs="+", default=None,
                    help="WARN workbook years (default: current + prior).")
    args = ap.parse_args(argv)
    result = fetch_observations(quarters=args.quarters,
                                warn_years=args.warn_years)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['summary']['qcew_observations']} QCEW, "
              f"{result['summary']['warn_observations']} WARN) "
              f"latest QCEW {result['summary']['qcew_latest_period']}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
