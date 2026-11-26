#!/usr/bin/env python3
"""Insider buying / 13F / SEC filings collector — Pineapple sensor #18
(Wave 5, market/macro).

Two legs, both keyless and read-only via the shared EDGAR client
(`edgar.py`):

1. Market-wide leg — the SEC daily master index for each of the last
   N days. Every Form 4 (insider trades), 13F-HR (institutional
   holdings) and 13D/G (beneficial ownership) filing is counted, and
   up to ``--max-form4`` Form 4 filings get their ownership-document
   XML parsed into transactions (owner, buy/sell code, shares, price).
   The index lists filings; it does not carry transaction detail, so
   detail only exists for the parsed subset — the rest are counted,
   never invented.
2. Watchlist leg — submissions JSON for a seed list of large-cap
   CIKs (documented below; a seed, not exhaustive coverage). Recent
   Form 4 and 13F-HR filings per name, with filing date and accession.

Form 4 transaction codes: P = open-market purchase, S = open-market
sale, A = grant/award, M = option exercise, G = gift, others as
filed. Only P/S with a parsed price are treated as market trades;
everything else is listed with its code as filed.

Labels
------
VERIFIED  filing/transaction fetched live with all key fields parsed.
REPORTED  filing exists but detail is missing (e.g. Form 4 XML not
          parsed because the per-run cap was hit, or a field failed
          to parse). The filing is real; the gap is recorded.
UNKNOWN   a day with no master index (weekend/holiday) or a watchlist
          CIK with no filings of the requested form.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import edgar

# Seed watchlist: large-cap CIKs (10-digit, zero-padded in code).
# A seed for detail coverage — the market-wide leg is the master index.
WATCHLIST = {
    "0000320193": "Apple Inc.",
    "0000789019": "Microsoft Corp.",
    "0001045810": "NVIDIA Corp.",
    "0001018724": "Amazon.com Inc.",
    "0001652044": "Alphabet Inc.",
    "0001326801": "Meta Platforms Inc.",
    "0001318605": "Tesla Inc.",
    "0000019617": "JPMorgan Chase & Co.",
    "0000034088": "Exxon Mobil Corp.",
    "0000104169": "Walmart Inc.",
    "0001067983": "Berkshire Hathaway Inc.",
    "0000731766": "UnitedHealth Group Inc.",
}

FORM4 = {"4", "4/A"}
F13 = {"13F-HR", "13F-HR/A"}
F13DG = {"13D", "13D/A", "13G", "13G/A"}


def _index_json_url(cik: str, accession: str) -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{edgar.accession_path(accession)}/index.json"
    )


def _form4_xml_document(index_doc: dict | None) -> str | None:
    if not index_doc:
        return None
    items = index_doc.get("directory", {}).get("item", [])
    for item in items:
        name = item.get("name", "")
        if name.lower().endswith(".xml"):
            return name
    return None


def collect(days: int = 5, max_form4: int = 25,
            watchlist: dict | None = None) -> dict:
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    observations: list[dict] = []
    day_status: list[dict] = []
    parsed_form4 = 0
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
        f4 = [r for r in rows if r.get("form") in FORM4]
        f13 = [r for r in rows if r.get("form") in F13]
        f13dg = [r for r in rows if r.get("form") in F13DG]
        day_status.append({"date": day.isoformat(), "status": "OK",
                           "label": "VERIFIED",
                           "form4_count": len(f4),
                           "form13f_count": len(f13),
                           "form13dg_count": len(f13dg),
                           "total_filings": len(rows)})
        for row in f4:
            obs = {"date": day.isoformat(), "kind": "form4_filing",
                   "cik": row["cik"], "company": row["company"],
                   "form": row["form"], "filed": row["filed"],
                   "filename": row["filename"], "label": "REPORTED",
                   "note": "counted from master index; transaction "
                           "detail not parsed"}
            observations.append(obs)
            if parsed_form4 >= max_form4:
                continue
            accession = row["filename"].split("/")[-1].rsplit(".", 1)[0]
            idx, _ = edgar.fetch_json(
                _index_json_url(row["cik"], accession))
            doc = _form4_xml_document(idx)
            if not doc:
                obs["note"] = ("counted from master index; no XML "
                               "document found in filing index")
                continue
            url = edgar.filing_doc_url(row["cik"], accession, doc)
            body, fstatus = edgar.fetch_text(url)
            if body is None:
                obs["note"] = (f"counted from master index; XML fetch "
                               f"failed ({fstatus})")
                continue
            txns = edgar.parse_form4_xml(body)
            if not txns:
                obs["note"] = ("counted from master index; XML parsed "
                               "but no non-derivative transactions found")
                continue
            parsed_form4 += 1
            obs["label"] = "VERIFIED"
            obs["note"] = f"{len(txns)} non-derivative transaction(s) parsed"
            obs["transactions"] = txns
            for txn in txns:
                observations.append({
                    "date": txn.get("date") or day.isoformat(),
                    "kind": "insider_transaction",
                    "cik": row["cik"], "company": row["company"],
                    "owner": txn.get("owner"), "title": txn.get("title"),
                    "code": txn.get("code"),
                    "acquiredDisposed": txn.get("acquiredDisposed"),
                    "shares": txn.get("shares"), "price": txn.get("price"),
                    "label": txn.get("label", "REPORTED"),
                    "accession": accession,
                })

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
        got = edgar.recent_filings(subs, FORM4 | F13, limit=10)
        if not got:
            watchlist_obs.append({"cik": cik, "company": name,
                                  "label": "UNKNOWN",
                                  "note": "no recent Form 4 / 13F-HR "
                                          "filings"})
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
    reported = sum(1 for o in observations if o.get("label") == "REPORTED")
    buys = [o for o in observations
            if o.get("kind") == "insider_transaction"
            and o.get("code") == "P" and o.get("label") == "VERIFIED"]
    sells = [o for o in observations
             if o.get("kind") == "insider_transaction"
             and o.get("code") == "S" and o.get("label") == "VERIFIED"]
    return {
        "sensor": "18",
        "name": "Insider buying, 13F, SEC filings",
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
            "reported": reported,
            "form4_filings_total": sum(
                d.get("form4_count", 0) for d in day_status),
            "form13f_filings_total": sum(
                d.get("form13f_count", 0) for d in day_status),
            "form13dg_filings_total": sum(
                d.get("form13dg_count", 0) for d in day_status),
            "form4_transactions_parsed": parsed_form4,
            "insider_buys_P_verified": len(buys),
            "insider_sells_S_verified": len(sells),
            "watchlist_filings": len(
                [w for w in watchlist_obs if w.get("label") == "VERIFIED"]),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Collect SEC insider / 13F filings (sensor #18).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--days", type=int, default=5,
                    help="Days of master index to scan (default 5).")
    ap.add_argument("--max-form4", type=int, default=25,
                    help="Max Form 4 XMLs to parse per run (default 25).")
    args = ap.parse_args(argv)
    result = collect(days=args.days, max_form4=args.max_form4)
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
