#!/usr/bin/env python3
"""Shared SEC EDGAR client — Pineapple Wave 5 (market/macro), sensors
#18 (insider / 13F), #60 (8-K calendar), #62 (IPO / S-1 pipeline).

Read-only, stdlib-only access to EDGAR's public endpoints. No signup,
no key, no cost. SEC fair-access rules: max 10 requests/second and a
descriptive User-Agent identifying the operator — both are enforced
here (0.15 s minimum gap between requests, one shared UA).

Endpoints used
--------------
* Daily master index (all filings for one day):
      https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/master.YYYYMMDD.idx
  Rows: CIK|Company Name|Form Type|Date Filed|File Name. The index is
  the only market-wide "what filed today" feed EDGAR publishes.
* Per-company submissions JSON:
      https://data.sec.gov/submissions/CIK##########.json
  Recent filings (form, filingDate, accessionNumber, primaryDocument,
  reportDate) plus older filings in a separate file. No holdings detail.
* Filing documents (Form 4 XML, 8-K text) under:
      https://www.sec.gov/Archives/edgar/data/<cik>/<accession-nodashes>/<doc>

Labels
------
VERIFIED  row/file fetched live and parsed (all key fields present).
REPORTED  row/file exists but a key field is missing or unparseable.
          The row is real; the gap is recorded, never zero-filled.
UNKNOWN   a lookup returned nothing (e.g. CIK with no filings of the
          requested form) — not a failure, recorded as no data.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Pineapple Research research@example.com"
MIN_GAP_S = 0.15
MAX_RETRIES = 2

_last_fetch = 0.0


def _throttle() -> None:
    global _last_fetch
    now = time.monotonic()
    wait = MIN_GAP_S - (now - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.monotonic()


def fetch_text(url: str, timeout: int = 30) -> tuple[str | None, str]:
    """GET a URL as text. Returns (body, status) where status is
    'OK', 'HTTP_<code>' or 'ERROR_<reason>'. Retries 429/5xx twice."""
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace"), "OK"
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
            return None, f"HTTP_{exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
            return None, f"ERROR_{type(exc).__name__}"
    return None, "ERROR_RETRIES"


def fetch_json(url: str, timeout: int = 30) -> tuple[dict | None, str]:
    body, status = fetch_text(url, timeout=timeout)
    if body is None:
        return None, status
    try:
        return json.loads(body), "OK"
    except json.JSONDecodeError:
        return None, "ERROR_BAD_JSON"


def quarter_for(month: int) -> int:
    return (month - 1) // 3 + 1


def master_index_url(year: int, month: int, day: int) -> str:
    q = quarter_for(month)
    return (
        "https://www.sec.gov/Archives/edgar/daily-index/"
        f"{year}/QTR{q}/master.{year}{month:02d}{day:02d}.idx"
    )


def parse_master_index(text: str) -> list[dict]:
    """Parse a daily master index into rows.

    Each row: {cik, company, form, filed, filename}. Lines before the
    dashed separator and blank lines are skipped; malformed rows are
    returned with label REPORTED rather than dropped silently.
    """
    rows: list[dict] = []
    started = False
    for line in text.splitlines():
        if not started:
            if line.startswith("---"):
                started = True
            continue
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 5:
            rows.append({"raw": line, "label": "REPORTED",
                         "note": "malformed master-index row"})
            continue
        cik, company, form, filed, filename = (p.strip() for p in parts)
        rows.append({"cik": cik, "company": company, "form": form,
                     "filed": filed, "filename": filename,
                     "label": "VERIFIED"})
    return rows


def fetch_master_index(year: int, month: int, day: int) -> tuple[list[dict], str]:
    url = master_index_url(year, month, day)
    body, status = fetch_text(url)
    if body is None:
        return [], status
    return parse_master_index(body), "OK"


def submissions_url(cik: str) -> str:
    cik10 = str(cik).zfill(10)
    return f"https://data.sec.gov/submissions/CIK{cik10}.json"


def fetch_submissions(cik: str) -> tuple[dict | None, str]:
    return fetch_json(submissions_url(cik))


def recent_filings(submissions: dict, forms: set[str],
                   limit: int = 20) -> list[dict]:
    """Pull recent filings of the given forms from a submissions doc.

    Returns [{form, filingDate, reportDate, accessionNumber,
    primaryDocument, primaryDocDescription, label}]."""
    out: list[dict] = []
    recent = (submissions or {}).get("filings", {}).get("recent", {})
    n = len(recent.get("form", []))
    for i in range(n):
        form = recent["form"][i]
        if form not in forms:
            continue
        out.append({
            "form": form,
            "filingDate": recent.get("filingDate", [None] * n)[i],
            "reportDate": recent.get("reportDate", [None] * n)[i],
            "accessionNumber": recent.get("accessionNumber", [None] * n)[i],
            "primaryDocument": recent.get("primaryDocument", [None] * n)[i],
            "primaryDocDescription": recent.get(
                "primaryDocDescription", [None] * n)[i],
            "label": "VERIFIED",
        })
        if len(out) >= limit:
            break
    return out


def accession_path(accession: str) -> str:
    return accession.replace("-", "")


def filing_doc_url(cik: str, accession: str, document: str) -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{accession_path(accession)}/{document}"
    )


_ITEM_RE = re.compile(r"Item\s+(\d+\.\d+)", re.IGNORECASE)


def parse_8k_items(text: str, head_chars: int = 250000) -> list[str]:
    """Extract the Item numbers (e.g. 1.01, 5.02) from an 8-K filing
    text, de-duplicated in order of appearance.

    The complete-submission .txt is mostly HTML/CSS boilerplate, so
    the window is large (250k chars) and ``&nbsp;`` entities are
    normalised first — item headings otherwise sit past a small
    window or behind a non-breaking space."""
    clean = (text.replace("&nbsp;", " ").replace("&#160;", " ")
             .replace("&#xA0;", " "))
    seen: list[str] = []
    for match in _ITEM_RE.finditer(clean[:head_chars]):
        item = match.group(1)
        if item not in seen:
            seen.append(item)
    return seen


def _elem_text(elem: ET.Element | None) -> str | None:
    if elem is None or elem.text is None:
        return None
    return elem.text.strip() or None


def parse_form4_xml(text: str) -> list[dict]:
    """Parse a Form 4 ownership document (XML) into transactions.

    Each transaction: {owner, title, date, code, acquiredDisposed,
    shares, price, label}. Only non-derivative transactions are
    returned; derivative tables are out of scope and noted by the
    caller via the transaction count.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    owner = None
    rpt = root.find("reportingOwner/reportingOwnerId/rptOwnerName")
    owner = _elem_text(rpt)
    out: list[dict] = []
    table = root.find("nonDerivativeTable")
    if table is None:
        return out
    for txn in table.findall("nonDerivativeTransaction"):
        title = _elem_text(txn.find("securityTitle/value"))
        date = _elem_text(txn.find("transactionDate/value"))
        amounts = txn.find("transactionAmounts")
        shares = _elem_text(amounts.find("transactionShares/value")) \
            if amounts is not None else None
        price = _elem_text(amounts.find("transactionPricePerShare/value")) \
            if amounts is not None else None
        code = _elem_text(txn.find("transactionCoding/transactionCode"))
        acq = _elem_text(
            txn.find("transactionCoding/transactionAcquiredDisposedCode/value"))
        try:
            shares_f = float(shares) if shares is not None else None
        except ValueError:
            shares_f = None
        try:
            price_f = float(price) if price is not None else None
        except ValueError:
            price_f = None
        label = "VERIFIED" if (date and code and shares_f is not None
                               and price_f is not None) else "REPORTED"
        out.append({
            "owner": owner, "title": title, "date": date, "code": code,
            "acquiredDisposed": acq, "shares": shares_f,
            "price": price_f, "label": label,
        })
    return out


if __name__ == "__main__":
    print("edgar.py is a shared client library; run insider.py, "
          "events_8k.py or ipo_pipeline.py instead.", file=sys.stderr)
    sys.exit(2)
