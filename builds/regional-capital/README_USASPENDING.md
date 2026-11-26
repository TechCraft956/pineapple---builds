# Sensor #31 — Government contracts and grants (USAspending), Starr County

Read-only collector over the USAspending API v2 (keyless, no signup, $0)
that fetches federal contracts and grants whose **recipient** is located
in Starr County, Texas (FIPS 48427).

## What it does

`usaspending.py` POSTs to
`https://api.usaspending.gov/api/v2/search/spending_by_award/`
(plus the `_count` endpoint for totals) and emits one observation per
award, labeled **VERIFIED** / **REPORTED** / **UNKNOWN**:

- **VERIFIED** — Award ID, Recipient Name, Award Amount and Start Date
  all present in the API record.
- **REPORTED** — Award ID present, but Award Amount or Start Date missing.
  The amount stays `null`, never zero-filled.
- **UNKNOWN** — Award ID present, but Recipient Name *and* Award Amount
  both missing.
- Rows with no Award ID cannot be keyed; they are skipped and counted in
  `skipped_no_award_id`.

Each observation carries the public award-page URL (built from the API's
`generated_internal_id`) and a UTC retrieval timestamp.

Two award groups are fetched in **separate** requests, because the API
rejects mixed groups with HTTP 422:

| Group | Codes | Meaning |
|---|---|---|
| contracts | A, B, C, D | BPA Call, Purchase Order, Delivery Order, Definitive Contract |
| grants | 02, 03, 04, 05 | Block, Formula, Project Grant, Cooperative Agreement |

Loans, IDVs, direct payments and other assistance types are out of scope
for #31.

## How to run

```bash
cd builds/regional-capital
# Trailing 365 days (default), JSON report on stdout:
python3 usaspending.py

# Explicit window, saved to a file:
python3 usaspending.py --start 2025-01-01 --end 2026-11-26 \
    --out evidence/usaspending_run_20261126.json
```

Options: `--start` / `--end` (YYYY-MM-DD), `--out FILE`,
`--limit N` (records per page, default 100), `--max-pages N`
(page cap per group, default 20).

Exit code 0 on a completed run (even with zero awards). Non-zero with a
`BLOCKED-needs-feed` report if the API is unreachable or returns an
HTTP/auth error — no workaround is attempted; report the block with the
exact error.

Tests (stdlib only, offline fixtures — no live calls):

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

## Suggested activation cadence

**Weekly.** Federal award data updates daily but Starr County volume is
small (142 awards in the 2025-01-01..2026-11-26 window; 942 all-time),
so a weekly pull with a trailing-12-month window catches new awards
without noise. Each run is a fresh snapshot; compare `award_id` sets
against the previous run to surface new awards.

## Pagination limitation (honest, not silent)

The API's `hasNext` flag is reported unreliable past ~10,000 results.
The collector pages until `hasNext` is false **or** until the cap
(`--max-pages` × `--limit`, default 20 × 100 = 2,000 records per group)
is hit. If the cap stops the walk while `hasNext` is still true, the run
is flagged `truncated: true` (per group and in `summary.truncated_any_group`).
Starr County volume is far below the cap, so truncation is not expected
here — but if it ever fires, treat the run as partial, not complete.

## Relationship to sensor #7

Sensor #7 (`builds/regint-econ/.../contracts_feed.py`) already wires
USAspending, but **contracts-only, place-of-performance filter, single
page, no grants**. #31 is not a duplicate: it adds the grants group
(816 of 942 all-time Starr County awards), switches the filter to
**recipient location**, and paginates with an explicit cap. The request
shape and the 3-digit county code were reused from #7's verified-live
adapter; nothing else is shared. Awards *performed* in Starr County but
paid to a recipient elsewhere are #7's angle, not #31's.

## Verified API quirks (found live 2026-11-26)

- County code must be exactly 3 digits: `"427"` with `"state": "TX"`;
  `"48427"` → HTTP 422.
- `award_type_codes` must come from one group per request; mixing
  contracts and grants → HTTP 422.
- `time_period` does not strictly bound award Start Date: the
  2025-01-01..2026-11-26 window returned awards starting as early as
  2020-06-02 (the API filters on action-date semantics). Start dates are
  reported as returned.
- `"Award Type"` and `"recipient_location"` fields return null from this
  endpoint; not requested or relied on.
- 116 of 139 grants in the evidence window list Recipient Name
  `"REDACTED DUE TO PII"` (USDA individual housing-repair awards). Kept
  verbatim, flagged `recipient_redacted: true`; not treated as missing.

## Evidence

- [evidence/usaspending_evidence.md](evidence/usaspending_evidence.md) —
  live fetch 2026-11-26T18:47:34Z: 142 awards (3 contracts, 139 grants),
  all VERIFIED, $73,587.90 contracts + $15,423,655.00 grants.
- [evidence/usaspending_run_20261126.json](evidence/usaspending_run_20261126.json) —
  full raw run output (142 observations).

## Guardrails

$0 recurring cost. No signup, no API key, no spending, no account
creation, no contacting anyone. Read-only public API. No secrets or
live private data in any file.
