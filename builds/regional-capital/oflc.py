#!/usr/bin/env python3
"""DOL OFLC foreign-labor collector — Pineapple sensor #85 (regional capital).

Read-only collector for the U.S. Department of Labor, Office of Foreign
Labor Certification (OFLC) quarterly public disclosure files, filtered to
Texas worksites, with Starr County, TX (FIPS 48427) and the Rio Grande
Valley as the focus subset.

Primary leg — official DOL disclosure files (keyless .xlsx, $0)
----------------------------------------------------------------
    https://www.dol.gov/agencies/eta/foreign-labor/performance
Files live under:
    https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/
Latest release (confirmed 2026-11-26): FY2026 Q4, announced
2026-11-16, reporting period 2025-10-01 -> 2026-09-30, covering PERM,
LCA (H-1B, H-1B1, E-3), H-2A, H-2B, CW-1 and Prevailing Wage. This
collector fetches the three programs in sensor #85's scope:

    H-2A_Disclosure_Data_FY2026_Q4.xlsx          (agricultural)
    H-2B_Disclosure_Data_FY2026_Q4.xlsx          (non-agricultural)
    LCA_Disclosure_Data_FY2026_Q4.xlsx           (H-1B / H-1B1 / E-3)
    H-2A_Addendum_B_Employ_FY2026_Q4.xlsx        (H-2A worksite details)

File-name stems are confirmed from the FY2026 Q3 / FY2025 Q4 releases;
the FY2026 Q4 names follow the same pattern. Since FY2026 Q3 the files
sit in a per-quarter subfolder (``FY26Q3/`` for Q3 layouts), so each
file is tried under ``FY26Q4/`` first and then directly under ``pdfs/``;
every attempted URL and its outcome is recorded in the output.

.xlsx is a ZIP of XML, parsed here with stdlib ``zipfile`` +
``xml.etree`` — no dependency. Rows are streamed from the first
worksheet; only Texas worksite rows are kept.

Matching
--------
The main H-2A / H-2B / LCA files carry worksite city/state/postal but
NO worksite county. The H-2A Addendum B file DOES carry
PLACE_OF_EMPLOYMENT_COUNTY, so it is the authoritative county source.
Scope assignment:

* ``starr`` — worksite county == STARR, or worksite city is a known
  Starr County city (Rio Grande City, Roma, La Grulla, ...).
* ``rgv``   — worksite county in Hidalgo / Cameron / Willacy, or
  worksite city is a known RGV city (McAllen, Edinburg, Harlingen,
  Brownsville, ...).
* ``tx``    — any other Texas worksite row (kept: the sensor reports
  Texas totals, with Starr/RGV as the focus subset).

Labels
------
VERIFIED  row present in the official DOL file, worksite state TX, with
          a case number, a case status, and a worker count or wage.
REPORTED  row present in the official file but a key field above is
          missing/unparseable; or any row from the mirror leg (below).
          Missing values stay null, never zero-filled.
UNKNOWN   Texas row matched only via the worksite-city fallback when the
          worksite-state field itself is blank.
BLOCKED   a whole leg could not be fetched (recorded per file/leg with
          the exact error — a blocked leg is a finding, not a failure
          to hide).

Secondary leg — third-party mirror (REPORTED, never VERIFIED)
------------------------------------------------------------
DOL's files sit behind Akamai bot protection and answer HTTP 403 from
some networks (including this build environment — verified 2026-11-26
on the performance page, the confirmed Q4 layout PDF and all four
.xlsx URLs). Until the official files can be fetched from the run
host, the collector also pulls the MORVS mirror of the same DOL data
(CC0, source-linked to the DOL performance page, $0, keyless):

    https://api.morvs.ai/api/v1/oflc/recent?program=<H-2A|H-2B|LCA>&limit=200

The mirror's ``recent`` feed caps at 200 rows per program, carries no
worksite city/county (state only), and its newest decision date at
last check was 2026-03-31 (FY2026 Q2 vintage) — so mirror rows are a
partial, stale-window sample of Texas activity, labeled REPORTED.
Mirror rows whose case number already came from the official leg are
deduplicated and counted, not re-emitted. Disable with ``--no-mirror``.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

PERFORMANCE_PAGE_URL = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
FILE_BASE = "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
MIRROR_BASE = "https://api.morvs.ai/api/v1/oflc/recent"
MIRROR_PRIMARY_SOURCE = PERFORMANCE_PAGE_URL

# Latest release verified live 2026-11-26 (OFLC announcement 2026-11-16).
DEFAULT_FY = 2026
DEFAULT_QUARTER = "Q4"
DEFAULT_PERIOD = ("2025-10-01", "2026-09-30")

# (program, filename template) — {fy} / {q} substituted per run.
FILE_SPECS = [
    ("H-2A", "H-2A_Disclosure_Data_FY{fy}_{q}.xlsx"),
    ("H-2B", "H-2B_Disclosure_Data_FY{fy}_{q}.xlsx"),
    ("LCA", "LCA_Disclosure_Data_FY{fy}_{q}.xlsx"),
]
ADDENDUM_B_SPEC = ("H-2A-ADDENDUM-B",
                   "H-2A_Addendum_B_Employ_FY{fy}_{q}.xlsx")

PROGRAMS = ("H-2A", "H-2B", "LCA")

FIPS_STARR_COUNTY_TX = "48427"
RGV_COUNTIES = {"HIDALGO", "CAMERON", "WILLACY"}

# Starr County, TX incorporated places / communities. Used for the
# worksite-city match (main files carry no county) and the UNKNOWN
# fallback when the worksite-state field is blank.
STARR_CITIES = {
    "RIO GRANDE CITY", "ROMA", "LA GRULLA", "SULLIVAN CITY",
    "ESCOBARES", "LA ROSITA", "FALCON HEIGHTS", "GARCENO",
    "SAN ISIDRO", "EL SAUZ", "LA VICTORIA", "SANTA ELENA",
    "DELMITA", "GARCIASVILLE", "SALINEÑO", "FRONTON",
}

RGV_CITIES = {
    "MCALLEN", "EDINBURG", "PHARR", "MISSION", "WESLACO", "HARLINGEN",
    "BROWNSVILLE", "SAN JUAN", "ALAMO", "DONNA", "MERCEDES",
    "LA FERIA", "SAN BENITO", "RAYMONDVILLE", "LYFORD", "PORT ISABEL",
    "SOUTH PADRE ISLAND", "LOS FRESNOS", "RIO HONDO", "COMBES",
    "PRIMERA", "SANTA ROSA", "LA JOYA", "PALMVIEW", "PALMHURST",
    "ALTON", "HIDALGO", "PROGRESO", "EDCOUCH", "ELSA", "LA VILLA",
    "SAN CARLOS", "MILA DOCE", "MURILLO", "OLMITO", "RANCHO VIEJO",
}

# Candidate header names per logical field (layouts vary by program and
# by fiscal year; first present column wins). All matching is on the
# upper-cased, stripped header.
FIELD_CANDIDATES = {
    "case_number": ["CASE_NUMBER"],
    "case_status": ["CASE_STATUS"],
    "decision_date": ["DECISION_DATE", "DETERMINATION_DATE"],
    "received_date": ["RECEIVED_DATE", "DATE_RECEIVED"],
    "employer_name": ["EMPLOYER_NAME", "NAME_OF_AGRICULTURAL_BUSINESS",
                      "EMPLOYER_LEGAL_BUSINESS_NAME"],
    "employer_city": ["EMPLOYER_CITY"],
    "employer_state": ["EMPLOYER_STATE"],
    "worksite_city": ["WORKSITE_CITY", "PLACE_OF_EMPLOYMENT_CITY"],
    "worksite_state": ["WORKSITE_STATE", "PLACE_OF_EMPLOYMENT_STATE"],
    "worksite_county": ["WORKSITE_COUNTY", "PLACE_OF_EMPLOYMENT_COUNTY"],
    "worksite_postal": ["WORKSITE_POSTAL_CODE",
                        "PLACE_OF_EMPLOYMENT_POSTAL_CODE"],
    "job_title": ["JOB_TITLE"],
    "soc_code": ["SOC_CODE"],
    "soc_title": ["SOC_TITLE"],
    "wage_from": ["WAGE_RATE_OF_PAY_FROM", "WAGE_OFFER_FROM",
                  "BASIC_WAGE_RATE_FROM"],
    "wage_to": ["WAGE_RATE_OF_PAY_TO", "WAGE_OFFER_TO",
                "BASIC_WAGE_RATE_TO"],
    "wage_unit": ["WAGE_UNIT_OF_PAY", "WAGE_UNIT", "PER"],
    "workers_requested": ["TOTAL_WORKERS_REQUESTED",
                          "TOTAL_WORKERS_H-2A_REQUESTED",
                          "TOTAL_WORKERS_NEEDED",
                          "TOTAL_WORKERS", "NBR_WORKERS_REQUESTED"],
    "workers_certified": ["TOTAL_WORKERS_CERTIFIED",
                          "TOTAL_WORKERS_H-2A_CERTIFIED"],
    "period_start": ["PERIOD_OF_EMPLOYMENT_START", "REQUESTED_BEGIN_DATE",
                     "EMPLOYMENT_START_DATE"],
    "period_end": ["PERIOD_OF_EMPLOYMENT_END", "REQUESTED_END_DATE",
                   "EMPLOYMENT_END_DATE"],
}

# Mirror (MORVS) JSON field names.
MIRROR_FIELDS = ("case_number", "program", "case_status", "decision_date",
                 "employer_name", "employer_city", "employer_state",
                 "job_title", "soc_code", "soc_title", "total_workers",
                 "worksite_state", "wage_offer_from", "wage_unit",
                 "canonical_url")

USER_AGENT = ("Pineapple sensor 85 (DOL OFLC, regional capital) - "
              "read-only")  # ASCII only: urllib headers encode as latin-1

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value):
    """Strip whitespace; empty strings become None (never zero-filled)."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _to_float(value):
    try:
        return float(str(value).strip().replace(",", "").replace("$", ""))
    except (TypeError, ValueError, AttributeError):
        return None


def _to_int(value):
    try:
        return int(float(str(value).strip().replace(",", "")))
    except (TypeError, ValueError, AttributeError):
        return None


def _excel_serial_to_date(value):
    """Convert an Excel serial day number to YYYY-MM-DD, else None."""
    try:
        serial = float(value)
    except (TypeError, ValueError):
        return None
    if serial < 20000 or serial > 80000:
        return None
    base = datetime(1899, 12, 30, tzinfo=timezone.utc)
    return (base + timedelta(days=int(serial))).strftime("%Y-%m-%d")


def _normalise_date(value):
    """Best-effort date normalisation; unknown shapes pass through cleaned."""
    value = _clean(value)
    if value is None:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return _excel_serial_to_date(value) or value


def file_url_candidates(filename: str, fy: int, quarter: str) -> list[str]:
    """Per-quarter subfolder first (layout since FY26Q3), then flat path."""
    sub = f"FY{str(fy)[2:]}{quarter}/"
    return [FILE_BASE + sub + filename, FILE_BASE + filename]


def match_scope(row: dict) -> tuple[str | None, bool]:
    """Return (scope, via_city_fallback) for a normalised row.

    Scope is 'starr', 'rgv', 'tx', or None (not a Texas worksite).
    via_city_fallback is True when the match rests on the worksite city
    alone because the worksite-state field was blank.
    """
    county = _clean(row.get("worksite_county"))
    state = _clean(row.get("worksite_state"))
    city = _clean(row.get("worksite_city"))
    if county and state and state.upper() == "TX":
        c = county.upper()
        if c == "STARR":
            return "starr", False
        if c in RGV_COUNTIES:
            return "rgv", False
        return "tx", False
    if state and state.upper() == "TX":
        if city:
            cu = city.upper()
            if cu in STARR_CITIES:
                return "starr", False
            if cu in RGV_CITIES:
                return "rgv", False
        return "tx", False
    # Worksite state blank: weak city fallback, Starr/RGV only.
    if city:
        cu = city.upper()
        if cu in STARR_CITIES:
            return "starr", True
        if cu in RGV_CITIES:
            return "rgv", True
    return None, False


def label_official_row(obs: dict, via_city_fallback: bool) -> str:
    if via_city_fallback:
        return "UNKNOWN"
    has_key = obs.get("case_number") is not None \
        and obs.get("case_status") is not None
    has_measure = obs.get("workers_certified") is not None \
        or obs.get("workers_requested") is not None \
        or obs.get("wage_from") is not None
    if has_key and has_measure:
        return "VERIFIED"
    return "REPORTED"


def build_official_observation(row: dict, program: str, source_url: str,
                               retrieved_at: str, scope: str,
                               via_city_fallback: bool) -> dict:
    obs = {
        "program": program,
        "leg": "dol-official",
        "scope": scope,
        "case_number": _clean(row.get("case_number")),
        "case_status": _clean(row.get("case_status")),
        "decision_date": _normalise_date(row.get("decision_date")),
        "received_date": _normalise_date(row.get("received_date")),
        "employer_name": _clean(row.get("employer_name")),
        "employer_city": _clean(row.get("employer_city")),
        "employer_state": _clean(row.get("employer_state")),
        "worksite_city": _clean(row.get("worksite_city")),
        "worksite_state": _clean(row.get("worksite_state")),
        "worksite_county": _clean(row.get("worksite_county")),
        "worksite_postal": _clean(row.get("worksite_postal")),
        "county_fips": FIPS_STARR_COUNTY_TX if scope == "starr" else None,
        "job_title": _clean(row.get("job_title")),
        "soc_code": _clean(row.get("soc_code")),
        "soc_title": _clean(row.get("soc_title")),
        "wage_from": _to_float(row.get("wage_from")),
        "wage_to": _to_float(row.get("wage_to")),
        "wage_unit": _clean(row.get("wage_unit")),
        "workers_requested": _to_int(row.get("workers_requested")),
        "workers_certified": _to_int(row.get("workers_certified")),
        "period_start": _normalise_date(row.get("period_start")),
        "period_end": _normalise_date(row.get("period_end")),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs["label"] = label_official_row(obs, via_city_fallback)
    return obs


# ---------------------------------------------------------------- XLSX ---

def _cell_value(cell, shared_strings):
    """Resolve one <c> element to a plain string (or None)."""
    cell_type = cell.get("t")
    val_el = cell.find("m:v", NS)
    is_el = cell.find("m:is/m:t", NS)
    if is_el is not None:
        return is_el.text
    if val_el is None or val_el.text is None:
        return None
    raw = val_el.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return None
    return raw


def _iter_sheet_rows(xlsx_bytes: bytes):
    """Yield raw string rows (lists) from the first worksheet of an .xlsx."""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zf:
        names = zf.namelist()
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared_strings.append("".join(
                    t.text or "" for t in si.findall(".//m:t", NS)))
        sheet_name = next((n for n in names
                           if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                          None)
        if sheet_name is None:
            return
        root = ET.fromstring(zf.read(sheet_name))
        for row_el in root.findall(".//m:row", NS):
            cells = {}
            for cell in row_el.findall("m:c", NS):
                ref = cell.get("r") or ""
                col = re.match(r"[A-Z]+", ref)
                if col:
                    cells[col.group(0)] = _cell_value(cell, shared_strings)
            if not cells:
                continue
            # Rebuild the row in column order (A..Z, AA..AZ).
            max_idx = max(_col_to_index(c) for c in cells)
            row = [cells.get(_index_to_col(i)) for i in range(max_idx + 1)]
            yield row


def _col_to_index(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _index_to_col(idx: int) -> str:
    col = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        col = chr(ord("A") + rem) + col
    return col


def parse_xlsx_bytes(xlsx_bytes: bytes, program: str, source_url: str,
                     retrieved_at: str) -> tuple[list[dict], int, list[str]]:
    """Parse an OFLC .xlsx; return (observations, rows_scanned, headers).

    Only Texas worksite rows are returned as observations. The header
    row is the first non-empty row; unknown/missing columns stay None.
    """
    rows = list(_iter_sheet_rows(xlsx_bytes))
    if not rows:
        return [], 0, []
    header = [_clean(h).upper() if _clean(h) else "" for h in rows[0]]
    col_for: dict[str, int | None] = {}
    for field, candidates in FIELD_CANDIDATES.items():
        col_for[field] = next(
            (i for i, h in enumerate(header) if h in candidates), None)
    observations: list[dict] = []
    scanned = 0
    for raw in rows[1:]:
        if not any(_clean(v) for v in raw):
            continue
        scanned += 1
        row = {}
        for field, idx in col_for.items():
            row[field] = raw[idx] if idx is not None and idx < len(raw) \
                else None
        scope, via_fallback = match_scope(row)
        if scope is None:
            continue
        observations.append(build_official_observation(
            row, program, source_url, retrieved_at, scope, via_fallback))
    return observations, scanned, [h for h in header if h]


# ---------------------------------------------------------------- mirror ---

def fetch_mirror_observations(program: str, retrieved_at: str,
                              limit: int = 200,
                              opener=None) -> tuple[list[dict], dict]:
    """Fetch one program's recent rows from the MORVS mirror, TX only.

    Returns (observations, leg_report). Mirror rows are REPORTED, never
    VERIFIED: third-party copy, no worksite city/county, capped at 200
    rows per program, vintage lags the official release.
    """
    open_fn = opener or urllib.request.urlopen
    url = f"{MIRROR_BASE}?program={program}&limit={limit}"
    report: dict = {"leg": "morvs-mirror", "program": program, "url": url,
                    "status": None, "rows_scanned": 0, "rows_matched": 0,
                    "mirror_newest_decision_date": None,
                    "mirror_oldest_decision_date": None}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with open_fn(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # recorded, not raised
        report["status"] = f"ERROR: {type(exc).__name__}: {exc}"
        return [], report
    items = payload.get("items") or []
    report["rows_scanned"] = len(items)
    report["mirror_generated_at"] = payload.get("_source", {}).get(
        "generated_at") if isinstance(payload.get("_source"), dict) else None
    report["mirror_primary_source"] = MIRROR_PRIMARY_SOURCE
    dates = [i.get("decision_date") for i in items if i.get("decision_date")]
    if dates:
        report["mirror_oldest_decision_date"] = min(dates)
        report["mirror_newest_decision_date"] = max(dates)
    observations: list[dict] = []
    for item in items:
        if _clean(item.get("worksite_state")) != "TX":
            continue
        report["rows_matched"] += 1
        observations.append({
            "program": program,
            "leg": "morvs-mirror",
            "scope": "tx",  # mirror carries state only — no county/city
            "case_number": _clean(item.get("case_number")),
            "case_status": _clean(item.get("case_status")),
            "decision_date": _normalise_date(item.get("decision_date")),
            "received_date": None,
            "employer_name": _clean(item.get("employer_name")),
            "employer_city": _clean(item.get("employer_city")),
            "employer_state": _clean(item.get("employer_state")),
            "worksite_city": None,
            "worksite_state": "TX",
            "worksite_county": None,
            "worksite_postal": None,
            "county_fips": None,
            "job_title": _clean(item.get("job_title")),
            "soc_code": _clean(item.get("soc_code")),
            "soc_title": _clean(item.get("soc_title")),
            "wage_from": _to_float(item.get("wage_offer_from")),
            "wage_to": None,
            "wage_unit": _clean(item.get("wage_unit")),
            "workers_requested": _to_int(item.get("total_workers")),
            "workers_certified": None,
            "period_start": None,
            "period_end": None,
            "label": "REPORTED",
            "source_url": _clean(item.get("canonical_url")) or url,
            "mirror_url": url,
            "retrieved_at": retrieved_at,
        })
    report["status"] = "OK"
    return observations, report


# ------------------------------------------------------------------ run ---

def fetch_observations(fy: int = DEFAULT_FY, quarter: str = DEFAULT_QUARTER,
                       programs: tuple[str, ...] = PROGRAMS,
                       include_addendum_b: bool = True,
                       use_mirror: bool = True, mirror_limit: int = 200,
                       local_dir: str | None = None,
                       opener=None) -> dict:
    """Fetch the live OFLC files (+ mirror leg) and return the document."""
    retrieved_at = utcnow_iso()
    open_fn = opener or urllib.request.urlopen
    specs = [s for s in FILE_SPECS if s[0] in programs]
    if include_addendum_b and "H-2A" in programs:
        specs.append(ADDENDUM_B_SPEC)
    observations: list[dict] = []
    files: list[dict] = []
    seen_case_numbers: set[str] = set()
    for program, template in specs:
        fname = template.format(fy=fy, q=quarter)
        urls = file_url_candidates(fname, fy, quarter)
        local_path = None
        if local_dir:
            import os
            candidate = os.path.join(local_dir, fname)
            if os.path.exists(candidate):
                local_path = candidate
        status = None
        scanned = 0
        matched = 0
        used_url = None
        headers: list[str] = []
        if local_path:
            used_url = f"file://{local_path}"
            try:
                with open(local_path, "rb") as fh:
                    data = fh.read()
                obs, scanned, headers = parse_xlsx_bytes(
                    data, program, used_url, retrieved_at)
                observations.extend(obs)
                matched = len(obs)
                seen_case_numbers.update(o["case_number"] for o in obs
                                         if o["case_number"])
                status = "OK"
            except Exception as exc:
                status = f"ERROR: {type(exc).__name__}: {exc}"
            files.append({"program": program, "file": fname,
                          "url": used_url, "attempted_urls": urls,
                          "status": status, "rows_scanned": scanned,
                          "rows_matched": matched, "headers": headers})
            continue
        for url in urls:
            used_url = url
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT})
                with open_fn(req, timeout=300) as resp:
                    data = resp.read()
                obs, scanned, headers = parse_xlsx_bytes(
                    data, program, url, retrieved_at)
                observations.extend(obs)
                matched = len(obs)
                seen_case_numbers.update(o["case_number"] for o in obs
                                         if o["case_number"])
                status = "OK"
                break
            except Exception as exc:  # network/file errors: recorded
                status = f"ERROR: {type(exc).__name__}: {exc}"
                scanned, matched = 0, 0
        files.append({"program": program, "file": fname, "url": used_url,
                      "attempted_urls": urls, "status": status,
                      "rows_scanned": scanned, "rows_matched": matched,
                      "headers": headers})
    mirror_reports: list[dict] = []
    mirror_duplicates = 0
    if use_mirror:
        for program in programs:
            obs, report = fetch_mirror_observations(
                program, retrieved_at, limit=mirror_limit, opener=opener)
            for o in obs:
                if o["case_number"] and o["case_number"] in seen_case_numbers:
                    mirror_duplicates += 1
                    continue
                observations.append(o)
            mirror_reports.append(report)
    observations.sort(key=lambda o: (o["decision_date"] or "",
                                     o["program"],
                                     o["employer_name"] or ""))
    starr = [o for o in observations if o["scope"] == "starr"]
    rgv = [o for o in observations if o["scope"] == "rgv"]
    tx = [o for o in observations if o["scope"] == "tx"]

    def _top(counter_items, n=10):
        return [{"name": k, "cases": v[0], "workers_certified": v[1]}
                for k, v in counter_items[:n]]

    def _aggregate(rows):
        from collections import Counter
        emp: dict[str, list] = {}
        titles: dict[str, int] = Counter()
        for o in rows:
            key = o["employer_name"] or "UNKNOWN EMPLOYER"
            e = emp.setdefault(key, [0, None])
            e[0] += 1
            if o["workers_certified"] is not None:
                e[1] = (e[1] or 0) + o["workers_certified"]
            if o["job_title"]:
                titles[o["job_title"]] += 1
        ranked = sorted(emp.items(), key=lambda kv: (-kv[1][0], kv[0]))
        return {
            "top_employers": _top([(k, v) for k, v in ranked]),
            "top_job_titles": [{"job_title": k, "cases": v}
                               for k, v in titles.most_common(10)],
        }

    def _workers(rows):
        vals = [o["workers_certified"] for o in rows
                if o["workers_certified"] is not None]
        req = [o["workers_requested"] for o in rows
               if o["workers_requested"] is not None]
        return {
            "cases_with_certified_count": len(vals),
            "workers_certified_total": sum(vals) if vals else None,
            "cases_with_requested_count": len(req),
            "workers_requested_total": sum(req) if req else None,
        }

    return {
        "sensor": "oflc-85",
        "source": "U.S. Department of Labor, Office of Foreign Labor "
                  "Certification (OFLC) — public disclosure data",
        "performance_page": PERFORMANCE_PAGE_URL,
        "fiscal_year": fy,
        "quarter": quarter,
        "reporting_period": list(DEFAULT_PERIOD)
        if (fy, quarter) == (DEFAULT_FY, DEFAULT_QUARTER) else None,
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "include_rgv_secondary": True,
        "files": files,
        "mirror_legs": mirror_reports,
        "mirror_duplicates_skipped": mirror_duplicates,
        "summary": {
            "rows_scanned_official": sum(f["rows_scanned"] for f in files),
            "observations_total": len(observations),
            "texas_total": len(tx) + len(starr) + len(rgv),
            "starr_county": len(starr),
            "rgv_secondary": len(rgv),
            "texas_other": len(tx),
            "by_label": {lab: sum(1 for o in observations
                                  if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
            "by_program": {p: sum(1 for o in observations
                                  if o["program"] == p)
                           for p in set([s[0] for s in specs] +
                                        list(programs))},
            "by_leg": {leg: sum(1 for o in observations
                                if o["leg"] == leg)
                       for leg in ("dol-official", "morvs-mirror")},
            "by_scope": {"starr": len(starr), "rgv": len(rgv), "tx": len(tx)},
            "official_legs_blocked": sum(
                1 for f in files if not f["status"].startswith("OK")),
            "mirror_legs_ok": sum(
                1 for r in mirror_reports if r["status"] == "OK"),
            "workers": _workers(observations),
            "workers_starr": _workers(starr),
            "workers_rgv": _workers(rgv),
            "texas": _aggregate([o for o in observations]),
            "starr": _aggregate(starr),
            "rgv": _aggregate(rgv),
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch DOL OFLC foreign-labor disclosure data, "
                    "Texas worksites (Starr County / RGV focus).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--fy", type=int, default=DEFAULT_FY,
                    help="Fiscal year of the disclosure files (default 2026).")
    ap.add_argument("--quarter", default=DEFAULT_QUARTER,
                    choices=["Q1", "Q2", "Q3", "Q4"],
                    help="Fiscal quarter (default Q4).")
    ap.add_argument("--programs", nargs="+", default=list(PROGRAMS),
                    choices=list(PROGRAMS),
                    help="Programs to fetch (default: H-2A H-2B LCA).")
    ap.add_argument("--no-addendum-b", action="store_true",
                    help="Skip the H-2A Addendum B worksite file.")
    ap.add_argument("--no-mirror", action="store_true",
                    help="Skip the MORVS mirror leg (official files only).")
    ap.add_argument("--mirror-limit", type=int, default=200,
                    help="Rows per program requested from the mirror "
                         "(mirror caps at 200).")
    ap.add_argument("--local-dir", default=None,
                    help="Directory holding already-downloaded .xlsx files "
                         "to parse instead of fetching (offline / blocked "
                         "hosts).")
    args = ap.parse_args(argv)
    result = fetch_observations(
        fy=args.fy, quarter=args.quarter, programs=tuple(args.programs),
        include_addendum_b=not args.no_addendum_b,
        use_mirror=not args.no_mirror, mirror_limit=args.mirror_limit,
        local_dir=args.local_dir)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        s = result["summary"]
        print(f"wrote {args.out}: {s['observations_total']} observations "
              f"({s['starr_county']} Starr County, {s['rgv_secondary']} RGV, "
              f"{s['texas_other']} other TX) from "
              f"{s['rows_scanned_official']} official rows scanned; "
              f"official legs blocked: {s['official_legs_blocked']}, "
              f"mirror legs OK: {s['mirror_legs_ok']}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
