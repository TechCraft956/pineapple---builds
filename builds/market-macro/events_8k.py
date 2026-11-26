#!/usr/bin/env python3
"""Corporate events & 8-K calendar collector — Pineapple sensor #60
(Wave 5, market/macro).

Keyless, read-only, via the shared EDGAR client (`edgar.py`):

1. Market-wide leg — the SEC daily master index for each of the last
   N days, filtered to 8-K / 8-K/A filings. Every 8-K is listed with
   company, CIK, filing date and accession.
2. Item leg — up to ``--max-items`` 8-K filing texts are fetched and
   their Item numbers extracted from the head of the filing (Item
   1.01 entry into a material agreement, 2.01 completion of an
   acquisition, 2.04 triggering events, 5.02 executive changes,
   8.01 other events, etc.). Items are taken from the filing text
   as filed; the collector does not interpret them.
3. Watchlist leg — submissions JSON for the same seed large-cap
   list as #18, recent 8-K filings per name.

Item numbers are NOT in the master index or the submissions JSON, so
an 8-K whose text was not fetched (cap hit or fetch failure) is
listed with label REPORTED and items UNKNOWN — never guessed.

Labels
------
VERIFIED  8-K fetched live; items parsed from its text (possibly an
          empty list, which is itself a real outcome).
REPORTED  8-K counted from the index but items not parsed.
UNKNOWN   a day with no master index (weekend/holiday) or a watchlist
          CIK with no recent 8-K filings.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import edgar
from insider import WATCHLIST

FORMS_8K = {"8-K", "8-K/A"}


def collect(days: int = 5, max_items: int = 20,
            watchlist: dict | None = None) -> dict:
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    observations: list[dict] = []
    day_status: list[dict] = []
    parsed = 0
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
        k8 = [r for r in rows if r.get("form") in FORMS_8K]
        day_status.append({"date": day.isoformat(), "status": "OK",
                           "label": "VERIFIED", "count_8k": len(k8),
                           "total_filings": len(rows)})
        for row in k8:
            accession = row["filename"].split("/")[-1].rsplit(".", 1)[0]
            obs = {"date": day.isoformat(), "kind": "8k_filing",
                   "cik": row["cik"], "company": row["company"],
                   "form": row["form"], "filed": row["filed"],
                   "accession": accession, "items": None,
                   "label": "REPORTED",
                   "note": "counted from master index; items not parsed"}
            observations.append(obs)
            if parsed >= max_items:
                continue
            url = edgar.filing_doc_url(row["cik"], accession,
                                       row["filename"].split("/")[-1])
            body, fstatus = edgar.fetch_text(url)
            if body is None:
                obs["note"] = (f"counted from master index; filing text "
                               f"fetch failed ({fstatus})")
                continue
            items = edgar.parse_8k_items(body)
            parsed += 1
            obs["items"] = items
            obs["label"] = "VERIFIED"
            obs["note"] = (f"{len(items)} item(s) parsed from filing text"
                           if items else "no Item numbers found in filing "
                                        "head (amendment/attachment)")

    wl = watchlist if watchlist is not None else WATCHLIST
    watchlist_obs: list[dict] = []
    for cik, name in wl.items():
        subs, status = edgar.fetch_submissions(cik)
        if subs is None:
            watchlist_obs.append({"cik": cik, "company": name,
                                  "label": "UNKNOWN",
                                  "note": f"submissions fetch failed "
                                          f"({status})"})
            continue
        got = edgar.recent_filings(subs, FORMS_8K, limit=5)
        if not got:
            watchlist_obs.append({"cik": cik, "company": name,
                                  "label": "UNKNOWN",
                                  "note": "no recent 8-K filings"})
            continue
        for filing in got:
            watchlist_obs.append({
                "cik": cik, "company": subs.get("name", name),
                "form": filing["form"],
                "filingDate": filing["filingDate"],
                "reportDate": filing["reportDate"],
                "accessionNumber": filing["accessionNumber"],
                "primaryDocument": filing["primaryDocument"],
                "label": "VERIFIED",
            })

    verified = sum(1 for o in observations if o.get("label") == "VERIFIED")
    item_counts: dict[str, int] = {}
    for o in observations:
        for item in o.get("items") or []:
            item_counts[item] = item_counts.get(item, 0) + 1
    return {
        "sensor": "60",
        "name": "Corporate events & 8-K calendar",
        "run_utc": run_utc,
        "source": "SEC EDGAR daily master index + submissions JSON",
        "fetch_status": "OK",
        "days_scanned": days,
        "day_status": day_status,
        "watchlist": watchlist_obs,
        "observations": observations,
        "summary": {
            "observations_total": len(observations),
            "verified": verified,
            "reported": len(observations) - verified,
            "filings_with_items_parsed": parsed,
            "top_items": dict(sorted(item_counts.items(),
                                     key=lambda kv: -kv[1])[:10]),
            "watchlist_filings": len(
                [w for w in watchlist_obs if w.get("label") == "VERIFIED"]),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Collect SEC 8-K filings (sensor #60).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--days", type=int, default=5,
                    help="Days of master index to scan (default 5).")
    ap.add_argument("--max-items", type=int, default=20,
                    help="Max 8-K texts to parse per run (default 20).")
    args = ap.parse_args(argv)
    result = collect(days=args.days, max_items=args.max_items)
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
