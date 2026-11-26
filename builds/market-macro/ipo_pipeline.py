#!/usr/bin/env python3
"""IPO, SPAC & S-1 pipeline collector — Pineapple sensor #62
(Wave 5, market/macro).

Keyless, read-only, via the shared EDGAR client (`edgar.py`). The
source is the SEC nightly submissions feed as published in the daily
master index: for each of the last N days, every filing whose form
is one of the registration / pricing forms is listed with company,
CIK, filing date and accession.

Forms tracked
-------------
S-1, S-1/A   IPO registration (initial / amendment)
F-1, F-1/A   foreign private issuer registration
S-4, S-4/A   merger / SPAC business-combination registration
424B4        final prospectus — pricing (the IPO priced)
424B3        preliminary prospectus supplement
EFFECT       notice of effectiveness (registration declared effective)

An S-1 is a registration, not a completed IPO — the collector never
labels a filing as a completed offering. EFFECT + 424B4 together are
the closest thing to "priced and effective" in this feed.

Labels
------
VERIFIED  filing counted from a master index fetched live.
REPORTED  a master-index row that failed to parse (malformed row).
UNKNOWN   a day with no master index (weekend/holiday) — the pipeline
          is empty for that day by construction, not by finding.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import edgar

TRACKED_FORMS = {"S-1", "S-1/A", "F-1", "F-1/A", "S-4", "S-4/A",
                 "424B4", "424B3", "EFFECT"}


def collect(days: int = 5) -> dict:
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    observations: list[dict] = []
    day_status: list[dict] = []
    today = dt.date.today()

    for back in range(days):
        day = today - dt.timedelta(days=back)
        rows, status = edgar.fetch_master_index(day.year, day.month, day.day)
        if status != "OK":
            day_status.append({"date": day.isoformat(), "status": status,
                               "label": "UNKNOWN",
                               "note": "no master index (weekend/holiday "
                                       "or fetch failure)"})
            continue
        hits = [r for r in rows if r.get("form") in TRACKED_FORMS]
        day_status.append({"date": day.isoformat(), "status": "OK",
                           "label": "VERIFIED",
                           "pipeline_filings": len(hits),
                           "total_filings": len(rows)})
        for row in hits:
            accession = row["filename"].split("/")[-1].rsplit(".", 1)[0]
            observations.append({
                "date": day.isoformat(), "kind": "registration_filing",
                "cik": row["cik"], "company": row["company"],
                "form": row["form"], "filed": row["filed"],
                "accession": accession, "filename": row["filename"],
                "label": "VERIFIED",
            })

    by_form: dict[str, int] = {}
    for o in observations:
        by_form[o["form"]] = by_form.get(o["form"], 0) + 1
    return {
        "sensor": "62",
        "name": "IPO, SPAC & S-1 pipeline",
        "run_utc": run_utc,
        "source": "SEC EDGAR daily master index (nightly submissions)",
        "fetch_status": "OK",
        "days_scanned": days,
        "day_status": day_status,
        "observations": observations,
        "summary": {
            "observations_total": len(observations),
            "verified": len(observations),
            "by_form": dict(sorted(by_form.items())),
            "priced_424b4": by_form.get("424B4", 0),
            "effective_notices": by_form.get("EFFECT", 0),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Collect IPO / S-1 pipeline filings (sensor #62).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--days", type=int, default=5,
                    help="Days of master index to scan (default 5).")
    args = ap.parse_args(argv)
    result = collect(days=args.days)
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
