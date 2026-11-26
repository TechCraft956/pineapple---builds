# Sensor #104 — TREC broker & sales-agent license-holder registry

Public license records from the Texas Real Estate Commission (TREC),
published on the Texas Open Data Portal (Socrata). Same family as
sensor #101 (TEA educator certification): a public professional
register, not a people dossier.

## Source

- Endpoint: `https://data.texas.gov/resource/s7ft-44qi.json` (Socrata JSON, keyless — no app token)
- Dataset page: https://data.texas.gov/dataset/Broker-and-Sales-Agent-License-Holder-Information/s7ft-44qi/about_data (updated Nov 5, 2026)
- Fields kept: license_type, license_number, full_name, status, original_license_date, license_expiration_date, designated_supervisor_flag, county, related license (broker affiliation), agency_identifier, updated.

## How to run

    cd builds/regint-public-sector
    python3 trec_licenses.py --out evidence/trec_licenses_run_<date>.json

Options: `--counties` (default: Starr Hidalgo Cameron Willacy),
`--page-size` (Socrata `$limit`, default 1000), `--delay` (default
0.2s between pages), `--timeout` (default 30s). Refuses to overwrite
an existing output file. Exit 0 on a completed run; exit 2 only if no
output could be produced.

The collector pages through the endpoint (`$order=license_number`,
`$limit`/`$offset`) and aggregates by county × status × license type,
plus licenses expiring within 90 days of the run date. The output keeps
the full Starr County row set (home county) plus a 5-row sample per
other county, so the evidence file stays small while the counts stay
checkable against the live endpoint.

## Live evidence (2026-11-26, fetched 20:27:47 UTC)

5,406 RGV license holders, all VERIFIED — Hidalgo 3,495, Cameron
1,830, Starr 55, Willacy 26; 303 expiring within 90 days. Starr: 49
Sales Agent, 4 Broker Individual, 2 Broker Company; 34 Active, 10
Expired less than 6 months, 6 Inactive, 2 Probation - Active, 2
Expired more than 6 months, 1 Revoked. Full detail in
`evidence/trec_licenses_evidence.md`.

## Caveats

- The `county` field is mostly title case but has at least one
  uppercase variant (`HIDALGO`, 1 row). The query filters on
  `upper(county)` and the collector normalizes to title case, so the
  variant is counted, not dropped.
- Status values are TREC's own vocabulary (Active, Inactive,
  Probation - Active, Expired less/more than 6 months, Revoked,
  Deceased, Surrendered, Suspended, Closed - Upgraded, and others) —
  reported as-is, never remapped.
- Socrata's default result cap is 1,000 rows, so pagination is
  mandatory (6 pages for the RGV); the collector stops on a short
  page and caps at 50,000 rows as a safety valve.
- Scope: public license records only. No addresses, no personal-life
  material, no contact info, no dossiers.
