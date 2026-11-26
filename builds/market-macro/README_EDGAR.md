# Shared EDGAR client (`edgar.py`)

Read-only, stdlib-only client for SEC EDGAR's public endpoints, used
by sensors #18, #60 and #62. No signup, no key, no cost.

## Endpoints

- Daily master index (all filings for one day):
  `https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/master.YYYYMMDD.idx`
  Rows: `CIK|Company Name|Form Type|Date Filed|File Name`.
- Per-company submissions JSON:
  `https://data.sec.gov/submissions/CIK##########.json`
- Filing documents under:
  `https://www.sec.gov/Archives/edgar/data/<cik>/<accession-nodashes>/<doc>`

## Rules enforced

- Descriptive User-Agent (`Pineapple Research research@example.com`)
  on every request — SEC blocks requests without one ("Your Request
  Originates from an Undeclared Automated Tool", HTTP 403).
- Minimum 0.15 s between requests (SEC fair-access limit is 10/s).
- Retries on 429/5xx (2 attempts, backoff). 404/403 are returned as
  status, not retried forever.

## Functions

- `fetch_text(url)` / `fetch_json(url)` → `(body, status)`.
- `parse_master_index(text)` → rows; malformed rows are returned
  with label REPORTED, never silently dropped.
- `fetch_master_index(y, m, d)`, `fetch_submissions(cik)`,
  `recent_filings(submissions, forms, limit)`.
- `filing_doc_url(cik, accession, document)`.
- `parse_8k_items(text)` — Item numbers from filing text; searches
  up to 250k chars and normalises `&nbsp;` (HTML/CSS boilerplate
  buries the headings; a 6k window found zero items in testing).
- `parse_form4_xml(text)` — non-derivative transactions from a Form 4
  ownership document: owner, code, shares, price, date.

## Tests

`tests/test_edgar.py` — master-index parsing (incl. the malformed-row
case), submissions filtering, Form 4 XML, 8-K items (incl. the
`&nbsp;` / deep-heading case). Offline fixtures only.
