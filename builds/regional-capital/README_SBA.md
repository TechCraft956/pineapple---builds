# SBA 7(a) / 504 Loans — Starr County, TX (sensor #72)

Read-only collector for the U.S. Small Business Administration's FOIA
loan-level data, filtered to Starr County, TX (FIPS 48427).

## What it does

` sba_loans.py` downloads SBA's public quarterly FOIA CSVs for the 7(a)
and 504 loan programs, streams them (no full-file load), and emits one
JSON observation per loan whose project county is Starr County, TX.
Each observation carries a label:

- **VERIFIED** — row present in the SBA file with a parseable gross
  approval amount, approval date, and loan status.
- **REPORTED** — row present but a key field is missing/unparseable
  (recorded as missing, never zero-filled).
- **UNKNOWN** — matched only via the borrower-city fallback (county
  field blank but borrower city is a known Starr County city).

Every observation records its source URL and retrieval timestamp.
Nearby Rio Grande Valley counties (Hidalgo, Cameron, Willacy) can be
collected as a secondary set with `--include-rgv`.

## Source

- Dataset page: https://data.sba.gov/dataset/7a-504-foia
- Publisher: U.S. Small Business Administration (U.S. Government Works).
- Updated quarterly, ~1 month after quarter-end. The collector scrapes
  the dataset page for the current `asof_YYMMDD` stamp on every run, so
  it follows new releases automatically; it falls back to the last known
  stamp (`260930`, as of 2026-09-30) only if the page cannot be read.
- **$0 cost. No signup, no API key, no account.**

## How to run

```bash
cd builds/regional-capital
python3 sba_loans.py --out evidence/sba_loans_<date>.json
```

Options:

| Flag | Effect |
|---|---|
| `--program 7a\|504\|both` | Limit to one program (default: both). |
| `--include-rgv` | Also collect Hidalgo / Cameron / Willacy as secondary. |
| `--all-decades` | Also fetch the pre-2010/2020 decade files. |
| `--out <path>` | Write result JSON (default: stdout). |

Stdlib Python only; no dependencies. A run streams ~250 MB and takes
~30 seconds on a normal connection.

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

15 tests, all passing (2026-11-26). Tests are offline fixtures — no
network calls.

## Suggested activation cadence

**Weekly.** The source updates only quarterly, so a weekly run is
plenty: it re-discovers the current release stamp and picks up a new
quarter within a week of publication, while staying cheap on bandwidth
(~250 MB/run, streamed and discarded except the Starr County rows).

## Privacy note

Many 7(a)/504 borrowers are sole proprietors. Street-address columns
(`BorrStreet`, `BankStreet`, `CDC_Street`, `ThirdPartyLender_Street`)
are dropped at ingest and never appear in any output.

## Limitations

- The FOIA files carry no FIPS code; the county match is by county/state
  name (`ProjectCounty == "STARR"`, `ProjectState == "TX"`).
- `LoanStatus` values (`EXEMPT`, `P I F`, `CANCLD`, `CHGOFF`, …) are
  reproduced exactly as SBA publishes them, without interpretation.
- Default run covers the current decade files only (7(a) FY2020–present,
  504 FY2010–present). Older decades need `--all-decades`.
