#!/usr/bin/env python3
"""SBA 7(a) / 504 loan collector — Pineapple sensor #72 (regional capital).

Read-only collector for the U.S. Small Business Administration's FOIA
loan-level data, filtered to Starr County, TX (FIPS 48427), with nearby
Rio Grande Valley counties available as a secondary set.

Source
------
SBA open-data dataset page (no signup, no API key, no cost):
    https://data.sba.gov/dataset/7a-504-foia
Direct CSVs live under:
    https://data.sba.gov/sites/default/files/uploaded_resources/
The dataset page is scraped for the current quarterly ``asof_YYMMDD``
stamp so the collector keeps working when SBA publishes a new release
(quarterly, ~1 month after quarter-end). If discovery fails, it falls
back to the last known stamp and records that in the output.

Files fetched (default run):
    FOIA_7a_FY2020_Present_asof_<stamp>.csv   (~188 MB)
    FOIA_504_FY2010_Present_asof_<stamp>.csv  (~60 MB)
Older decades exist on the same page and can be added with
``--all-decades``.

Matching
--------
The FOIA files carry no FIPS code, so the county match is by name:
ProjectCounty == "STARR" and ProjectState == "TX". Rows whose
ProjectCounty is blank but whose borrower city is a known Starr County
city (and BorrState == "TX") are kept with label UNKNOWN — the match is
weaker and must not be presented as county-verified.

Labels
------
VERIFIED  row present in the SBA file with a parseable gross approval
          amount, a non-empty approval date, and a non-empty loan status.
REPORTED  row present in the SBA file but one of those key fields is
          missing/unparseable. The row is real; the gap is recorded,
          never zero-filled.
UNKNOWN   row matched only via the borrower-city fallback above.

Privacy
-------
Many 7(a)/504 borrowers are sole proprietors (individual humans).
Street-address columns (BorrStreet, BankStreet, CDC_Street,
ThirdPartyLender_Street) are dropped at ingest and never appear in any
output file. Only borrower name, city, county, state and loan terms
are emitted.

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
from datetime import datetime, timezone

DATASET_PAGE_URL = "https://data.sba.gov/dataset/7a-504-foia"
RESOURCE_BASE = "https://data.sba.gov/sites/default/files/uploaded_resources/"

# Last verified release stamp; used only if live discovery of the
# dataset page fails. Update when a newer release is confirmed.
FALLBACK_ASOF = "260930"  # as of 2026-09-30, verified 2026-11-26

# (program, filename template) for the default run.
FILE_SPECS = [
    ("7a", "FOIA_7a_FY2020_Present_asof_{stamp}.csv"),
    ("504", "FOIA_504_FY2010_Present_asof_{stamp}.csv"),
]

# Older decades, same naming scheme, fetched only with --all-decades.
OLDER_FILE_SPECS = [
    ("7a", "FOIA_7a_FY1991_FY1999_asof_{stamp}.csv"),
    ("7a", "FOIA_7a_FY2000_FY2009_asof_{stamp}.csv"),
    ("7a", "FOIA_7a_FY2010_FY2019_asof_{stamp}.csv"),
    ("504", "FOIA_504_FY1991_FY2009_asof_{stamp}.csv"),
]

FIPS_STARR_COUNTY_TX = "48427"

# Secondary Rio Grande Valley counties (optional, --include-rgv).
RGV_COUNTIES = {"HIDALGO", "CAMERON", "WILLACY"}

# Starr County, TX incorporated places / communities, used ONLY for the
# UNKNOWN city-fallback match when ProjectCounty is blank.
STARR_CITIES = {
    "RIO GRANDE CITY", "ROMA", "LA GRULLA", "SULLIVAN CITY",
    "ESCOBARES", "LA ROSITA", "FALCON HEIGHTS", "GARCENO",
    "SAN ISIDRO", "EL SAUZ", "LA VICTORIA", "SANTA ELENA",
    "DELMITA", "GARCIASVILLE", "SALINEÑO", "FRONTON",
}

# Street-address columns: dropped at ingest, never emitted.
STREET_COLUMNS = {"BorrStreet", "BankStreet", "CDC_Street",
                  "ThirdPartyLender_Street"}

FILENAME_RE = re.compile(r"FOIA_(7a|504)_[A-Za-z0-9_]*_asof_(\d{6})\.csv")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover_file_urls(page_url: str = DATASET_PAGE_URL,
                       opener=None) -> tuple[dict[str, str], str, bool]:
    """Scrape the SBA dataset page for the current quarterly CSV URLs.

    Returns (urls, asof_stamp, discovered). ``urls`` maps a filename
    template key to its full URL. When discovery fails, returns the
    fallback-stamp URLs with discovered=False.
    """
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(page_url, timeout=60) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return _fallback_urls(), FALLBACK_ASOF, False
    found: dict[str, str] = {}
    stamps: set[str] = set()
    for m in FILENAME_RE.finditer(html):
        fname = m.group(0)
        stamps.add(m.group(2))
        found[fname] = RESOURCE_BASE + fname
    if not found or not stamps:
        return _fallback_urls(), FALLBACK_ASOF, False
    # SBA publishes one stamp per release; take the newest if several.
    stamp = sorted(stamps)[-1]
    urls = {fname: url for fname, url in found.items()
            if fname.endswith(f"_asof_{stamp}.csv")}
    return urls, stamp, True


def _fallback_urls() -> dict[str, str]:
    return {spec.format(stamp=FALLBACK_ASOF): RESOURCE_BASE + spec.format(stamp=FALLBACK_ASOF)
            for _, spec in FILE_SPECS + OLDER_FILE_SPECS}


def _clean(value):
    """Strip whitespace; empty strings become None (never zero-filled)."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _to_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def match_county(row: dict, include_rgv: bool = False) -> str | None:
    """Return 'starr', 'rgv', or None for a raw CSV row.

    Primary match is authoritative: ProjectCounty + ProjectState.
    City fallback returns 'starr' only when the county field is blank;
    the caller downgrades such rows to UNKNOWN.
    """
    county = _clean(row.get("ProjectCounty"))
    state = _clean(row.get("ProjectState"))
    if county and state:
        c = county.upper()
        if state.upper() == "TX" and c == "STARR":
            return "starr"
        if include_rgv and state.upper() == "TX" and c in RGV_COUNTIES:
            return "rgv"
        return None
    # County blank: weak city fallback, Starr only.
    city = _clean(row.get("BorrCity"))
    bstate = _clean(row.get("BorrState"))
    if city and bstate and bstate.upper() == "TX" \
            and city.upper() in STARR_CITIES:
        return "starr"
    return None


def label_row(obs: dict, via_city_fallback: bool) -> str:
    if via_city_fallback:
        return "UNKNOWN"
    if obs.get("gross_approval") is not None \
            and obs.get("approval_date") is not None \
            and obs.get("loan_status") is not None:
        return "VERIFIED"
    return "REPORTED"


def build_observation(row: dict, program: str, source_url: str,
                      retrieved_at: str, scope: str,
                      via_city_fallback: bool) -> dict:
    """Project one raw FOIA row onto the emitted observation schema.

    Street addresses are never read into the observation. Missing
    numeric/date fields stay None.
    """
    lender = _clean(row.get("BankName"))
    if program == "504":
        cdc = _clean(row.get("CDC_Name"))
        third = _clean(row.get("ThirdPartyLender_Name"))
        lender = " / ".join(p for p in (cdc, third) if p) or None
    obs = {
        "program": program,
        "scope": scope,  # "starr" or "rgv"
        "borrower_name": _clean(row.get("BorrName")),
        "borrower_city": _clean(row.get("BorrCity")),
        "borrower_state": _clean(row.get("BorrState")),
        "borrower_zip": _clean(row.get("BorrZip")),
        "project_county": _clean(row.get("ProjectCounty")),
        "project_state": _clean(row.get("ProjectState")),
        "county_fips": FIPS_STARR_COUNTY_TX if scope == "starr" else None,
        "lender": lender,
        "gross_approval": _to_float(row.get("GrossApproval")),
        "sba_guaranteed_approval": _to_float(row.get("SBAGuaranteedApproval")),
        "third_party_dollars": _to_float(row.get("ThirdPartyDollars")),
        "approval_date": _clean(row.get("ApprovalDate")),
        "approval_fy": _to_int(row.get("ApprovalFY")),
        "first_disbursement_date": _clean(row.get("FirstDisbursementDate")),
        "loan_status": _clean(row.get("LoanStatus")),
        "naics_code": _clean(row.get("NaicsCode")),
        "naics_description": _clean(row.get("NaicsDescription")),
        "business_type": _clean(row.get("BusinessType")),
        "business_age": _clean(row.get("BusinessAge")),
        "term_months": _to_float(row.get("TermInMonths")),
        "jobs_supported": _to_float(row.get("JobsSupported")),
        "gross_charge_off_amount": _to_float(row.get("GrossChargeOffAmount")),
        "charge_off_date": _clean(row.get("ChargeOffDate")),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs["label"] = label_row(obs, via_city_fallback)
    return obs


def iter_matching_rows(text_stream, program: str, source_url: str,
                      retrieved_at: str, include_rgv: bool = False):
    """Yield observations for matching rows from a text CSV stream."""
    reader = csv.DictReader(text_stream)
    for raw in reader:
        scope = match_county(raw, include_rgv=include_rgv)
        if scope is None:
            continue
        county = _clean(raw.get("ProjectCounty"))
        via_fallback = county is None
        yield build_observation(raw, program, source_url, retrieved_at,
                                scope, via_fallback)


def fetch_observations(program_filter: str = "both",
                       include_rgv: bool = False,
                       all_decades: bool = False,
                       opener=None,
                       url_opener=None) -> dict:
    """Fetch the live SBA files and return the full result document."""
    retrieved_at = utcnow_iso()
    urls, stamp, discovered = discover_file_urls(opener=opener)
    specs = list(FILE_SPECS)
    if all_decades:
        specs += OLDER_FILE_SPECS
    open_fn = url_opener or urllib.request.urlopen
    observations: list[dict] = []
    files: list[dict] = []
    for program, template in specs:
        if program_filter != "both" and program_filter != program:
            continue
        fname = template.format(stamp=stamp)
        url = urls.get(fname)
        if url is None:
            files.append({"program": program, "file": fname,
                          "url": None, "status": "NOT_FOUND_IN_DISCOVERY",
                          "rows_scanned": 0, "rows_matched": 0})
            continue
        scanned = 0
        matched = 0
        try:
            with open_fn(url, timeout=300) as resp:
                text = io.TextIOWrapper(resp, encoding="utf-8",
                                        errors="replace", newline="")
                reader = csv.DictReader(text)
                for raw in reader:
                    scanned += 1
                    scope = match_county(raw, include_rgv=include_rgv)
                    if scope is None:
                        continue
                    matched += 1
                    county = _clean(raw.get("ProjectCounty"))
                    observations.append(build_observation(
                        raw, program, url, retrieved_at, scope,
                        via_city_fallback=(county is None)))
            status = "OK"
        except Exception as exc:  # network/file errors: recorded, not raised
            status = f"ERROR: {type(exc).__name__}: {exc}"
        files.append({"program": program, "file": fname, "url": url,
                      "status": status, "rows_scanned": scanned,
                      "rows_matched": matched})
    observations.sort(key=lambda o: (o["approval_date"] or "",
                                     o["program"], o["borrower_name"] or ""))
    starr = [o for o in observations if o["scope"] == "starr"]
    rgv = [o for o in observations if o["scope"] == "rgv"]
    return {
        "sensor": "sba-loans-72",
        "source": "U.S. Small Business Administration, 7(a) & 504 FOIA data",
        "dataset_page": DATASET_PAGE_URL,
        "asof_stamp": stamp,
        "asof_discovered_live": discovered,
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "include_rgv_secondary": include_rgv,
        "all_decades": all_decades,
        "files": files,
        "summary": {
            "rows_scanned": sum(f["rows_scanned"] for f in files),
            "observations_total": len(observations),
            "starr_county": len(starr),
            "rgv_secondary": len(rgv),
            "by_label": {lab: sum(1 for o in observations if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
            "by_program": {p: sum(1 for o in observations if o["program"] == p)
                           for p in ("7a", "504")},
            "starr_gross_approval_total": sum(
                o["gross_approval"] for o in starr
                if o["gross_approval"] is not None),
            "starr_approval_date_range": [
                min((o["approval_date"] for o in starr
                     if o["approval_date"]), default=None),
                max((o["approval_date"] for o in starr
                     if o["approval_date"]), default=None),
            ],
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch SBA 7(a)/504 FOIA loan data, Starr County, TX.")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--program", choices=["7a", "504", "both"],
                    default="both")
    ap.add_argument("--include-rgv", action="store_true",
                    help="Also collect Hidalgo/Cameron/Willacy as secondary.")
    ap.add_argument("--all-decades", action="store_true",
                    help="Also fetch the pre-2010/2020 decade files.")
    args = ap.parse_args(argv)
    result = fetch_observations(program_filter=args.program,
                                include_rgv=args.include_rgv,
                                all_decades=args.all_decades)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['summary']['starr_county']} Starr County) "
              f"from {result['summary']['rows_scanned']} rows scanned")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
