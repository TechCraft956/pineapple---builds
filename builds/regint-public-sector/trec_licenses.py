#!/usr/bin/env python3
"""Pineapple sensor — TREC broker & sales-agent license-holder registry.

Read-only collector for the Texas Real Estate Commission's Broker and
Sales Agent License Holder Information dataset, published on the Texas
Open Data Portal (Socrata). Standard library only. $0 recurring cost.
No signup, no API key, no app token, no account, no payment.

What it does
------------
Queries the Socrata JSON endpoint for the four Rio Grande Valley
counties (Starr, Hidalgo, Cameron, Willacy) and aggregates the public
license records: license type (Broker Individual, Broker Company, Sales
Agent), license number, full name, status (Active, Inactive, Probation -
Active, Expired less than/more than 6 months, Revoked), original license
date, expiration date, designated-supervisor flag, affiliated broker
(related license), county and the TREC agency identifier. The dataset is
refreshed daily by TREC (dataset page notes an update of Nov 5, 2026;
row ``updated`` stamps run 2026-11-26).

Every row fetched live is VERIFIED. Aggregates are computed from those
live rows at fetch time. The output keeps the full Starr County row set
(55 rows — the home county) plus a 5-row sample per other county, so the
evidence file stays small while the counts stay checkable against the
live endpoint. Nothing is invented: a failed fetch is recorded UNKNOWN
with the error, never zero-filled.

County quirk (verified live 2026-11-26): the ``county`` field is mostly
title case (``Starr``) but at least one Hidalgo row is stored as
``HIDALGO``. The query filters with ``upper(county)`` and the collector
normalizes county names to title case for grouping, so the variant is
counted, not dropped.

Scope rule: PUBLIC LICENSE RECORDS ONLY. License holders are named
individuals and companies, but this is the public professional register
— the same family as sensor #101 (TEA educator certification). No
addresses, no personal-life material, no dossiers, no contact info.

How to run
----------
    cd builds/regint-public-sector
    python3 trec_licenses.py --out evidence/trec_licenses_run_<date>.json

Options: ``--counties`` (default: Starr Hidalgo Cameron Willacy),
``--page-size`` (Socrata $limit, default 1000), ``--delay SECONDS``
(politeness delay between pages, default 0.2), ``--timeout SECONDS``
(default 30). Refuses to overwrite an existing output file. Exit code
0 on a completed run (even with zero rows for a county); exit code 2
only if no output could be produced.

Live evidence (2026-11-26): 5,406 RGV license holders — Hidalgo 3,495
(incl. 1 ``HIDALGO``-cased row), Cameron 1,830, Starr 55, Willacy 26.
Starr: 49 Sales Agent, 4 Broker Individual, 2 Broker Company; 34
Active, 10 Expired less than 6 months, 6 Inactive, 2 Probation -
Active, 2 Expired more than 6 months, 1 Revoked. See
``evidence/trec_licenses_evidence.md``.
"""
import argparse
import datetime as dt
import json
import pathlib
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://data.texas.gov/resource/s7ft-44qi.json"
DATASET_URL = "https://data.texas.gov/dataset/Broker-and-Sales-Agent-License-Holder-Information/s7ft-44qi/about_data"
USER_AGENT = "Pineapple public-record research/1.0"

DEFAULT_COUNTIES = ["Starr", "Hidalgo", "Cameron", "Willacy"]
DEFAULT_PAGE_SIZE = 1000
DEFAULT_DELAY = 0.2
DEFAULT_TIMEOUT = 30
MAX_TOTAL_ROWS = 50000
SAMPLE_PER_COUNTY = 5
EXPIRING_SOON_DAYS = 90

# Fields kept from each Socrata row (public license record only).
ROW_FIELDS = [
    "license_type", "license_number", "full_name", "status",
    "original_license_date", "license_expiration_date",
    "designated_supervisor_flag", "county",
    "related_license_type", "related_license_number",
    "related_license_full_name", "agency_identifier", "updated",
]


def now():
    return dt.datetime.now(dt.timezone.utc)


def parse_us_date(text):
    """Parse an MM/DD/YYYY date; return a date or None."""
    if not text:
        return None
    try:
        return dt.datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def normalize_county(raw):
    """Title-case the county so the HIDALGO-cased variant groups with Hidalgo."""
    if not raw:
        return "UNKNOWN"
    return raw.strip().title()


def build_query_url(counties, limit, offset):
    """Socrata SoQL URL: case-insensitive county filter, stable order."""
    where = "upper(county) IN (%s)" % ",".join(
        "'%s'" % c.upper() for c in counties
    )
    params = {
        "$where": where,
        "$order": "license_number",
        "$limit": str(limit),
        "$offset": str(offset),
    }
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def fetch_page(url, timeout=DEFAULT_TIMEOUT):
    """GET one Socrata page; returns the decoded JSON list."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if isinstance(data, dict):
        # Socrata error payloads are objects, not arrays.
        raise ValueError("Socrata error: %s" % data.get("message", data))
    if not isinstance(data, list):
        raise ValueError("unexpected Socrata response type: %s" % type(data))
    return data


def normalize_row(raw):
    """Keep the public license fields; normalize county; parse dates."""
    row = {f: (raw.get(f) or "") for f in ROW_FIELDS}
    row["county"] = normalize_county(raw.get("county"))
    row["original_license_date_parsed"] = (
        parse_us_date(raw.get("original_license_date") or "").isoformat()
        if parse_us_date(raw.get("original_license_date") or "")
        else ""
    )
    row["license_expiration_date_parsed"] = (
        parse_us_date(raw.get("license_expiration_date") or "").isoformat()
        if parse_us_date(raw.get("license_expiration_date") or "")
        else ""
    )
    return row


def aggregate(rows, run_date):
    """Counts by county, status and license type, plus expiring-soon."""
    by_county = {}
    total = 0
    expiring_soon = 0
    for row in rows:
        total += 1
        county = row["county"]
        bucket = by_county.setdefault(county, {
            "total": 0, "by_status": {}, "by_license_type": {},
            "expiring_soon_90d": 0,
        })
        bucket["total"] += 1
        status = row["status"] or "UNKNOWN"
        bucket["by_status"][status] = bucket["by_status"].get(status, 0) + 1
        ltype = row["license_type"] or "UNKNOWN"
        bucket["by_license_type"][ltype] = bucket["by_license_type"].get(ltype, 0) + 1
        exp = parse_us_date(row["license_expiration_date"])
        if exp and 0 <= (exp - run_date).days <= EXPIRING_SOON_DAYS:
            bucket["expiring_soon_90d"] += 1
            expiring_soon += 1
    return {
        "total_rows": total,
        "expiring_soon_90d": expiring_soon,
        "by_county": by_county,
    }


def collect(counties, fetch=fetch_page, page_size=DEFAULT_PAGE_SIZE,
            delay=DEFAULT_DELAY, timeout=DEFAULT_TIMEOUT):
    """Fetch all pages for the counties; returns (rows, fetch_notes)."""
    rows = []
    notes = []
    offset = 0
    while True:
        url = build_query_url(counties, page_size, offset)
        try:
            page = fetch(url, timeout=timeout)
        except Exception as exc:  # network or Socrata error — record, don't invent
            notes.append({"url": url, "error": str(exc), "verification": "UNKNOWN"})
            break
        if not page:
            break
        rows.extend(normalize_row(r) for r in page)
        if len(page) < page_size:
            break
        offset += page_size
        if len(rows) >= MAX_TOTAL_ROWS:
            notes.append({"warning": "row cap reached", "cap": MAX_TOTAL_ROWS})
            break
        if delay:
            time.sleep(delay)
    return rows, notes


def run(counties=None, fetch=fetch_page, page_size=DEFAULT_PAGE_SIZE,
        delay=DEFAULT_DELAY, timeout=DEFAULT_TIMEOUT):
    """One full collection; returns the output document."""
    counties = counties or list(DEFAULT_COUNTIES)
    fetched_at = now()
    rows, notes = collect(counties, fetch=fetch, page_size=page_size,
                          delay=delay, timeout=timeout)
    run_date = fetched_at.date()
    totals = aggregate(rows, run_date)
    # Evidence rows: full Starr set (home county) + sample per other county.
    starr_rows = [r for r in rows if r["county"] == "Starr"]
    samples = {}
    for county in sorted(totals["by_county"]):
        if county == "Starr":
            continue
        samples[county] = [r for r in rows if r["county"] == county][:SAMPLE_PER_COUNTY]
    verified = not notes or all("error" not in n for n in notes)
    return {
        "sensor": 104,
        "name": "TREC broker & sales-agent license-holder registry",
        "source": {
            "endpoint": BASE_URL,
            "dataset": DATASET_URL,
            "counties": counties,
        },
        "fetched_at_utc": fetched_at.isoformat(),
        "verification": "VERIFIED" if verified and rows else "UNKNOWN",
        "fetch_notes": notes,
        "totals": totals,
        "starr_rows": starr_rows,
        "county_samples": samples,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="TREC broker & sales-agent license registry (sensor #104)")
    parser.add_argument("--out", default=None,
                        help="output JSON path (default: evidence/trec_licenses_run_<date>.json)")
    parser.add_argument("--counties", nargs="+", default=list(DEFAULT_COUNTIES))
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    out = pathlib.Path(args.out) if args.out else (
        pathlib.Path(__file__).resolve().parent / "evidence" /
        ("trec_licenses_run_%s.json" % now().strftime("%Y%m%d"))
    )
    if out.exists():
        print("refusing to overwrite existing %s" % out)
        return 2
    doc = run(counties=args.counties, page_size=args.page_size,
              delay=args.delay, timeout=args.timeout)
    if doc["verification"] == "UNKNOWN" and not doc["totals"]["total_rows"]:
        print("no output could be produced: %s" % doc["fetch_notes"])
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print("wrote %s (%d rows, %s)"
          % (out, doc["totals"]["total_rows"], doc["verification"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
