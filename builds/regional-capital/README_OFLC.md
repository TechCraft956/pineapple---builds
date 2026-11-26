# DOL foreign labor — H-2A / H-2B / H-1B (LCA) — Starr County / RGV (sensor #85)

Read-only collector for the U.S. Department of Labor, Office of Foreign
Labor Certification (OFLC) quarterly public disclosure files, filtered
to Texas worksites, with Starr County, TX (FIPS 48427) and the Rio
Grande Valley as the focus subset.

## What it does

`oflc.py` has two legs:

**Primary leg — official DOL .xlsx files (keyless, $0).** The latest
release is **FY2026 Q4** (announced 2026-11-16, reporting period
2025-10-01 → 2026-09-30), covering PERM, LCA (H-1B, H-1B1, E-3),
H-2A, H-2B, CW-1 and Prevailing Wage. This collector fetches the three
programs in scope plus the H-2A worksite-detail file:

| Program | File |
|---|---|
| H-2A | `H-2A_Disclosure_Data_FY2026_Q4.xlsx` |
| H-2B | `H-2B_Disclosure_Data_FY2026_Q4.xlsx` |
| LCA (H-1B/H-1B1/E-3) | `LCA_Disclosure_Data_FY2026_Q4.xlsx` |
| H-2A Addendum B (worksite details) | `H-2A_Addendum_B_Employ_FY2026_Q4.xlsx` |

Files live under
`https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/` — since FY2026 Q3
in a per-quarter subfolder (`FY26Q3/`, `FY26Q4/`), so each file is tried
under `FY26Q4/` first and then directly under `pdfs/`; every attempted
URL and its outcome is recorded. `.xlsx` is a ZIP of XML, parsed with
stdlib `zipfile` + `xml.etree` — no dependency. Only Texas worksite
rows are kept.

The main H-2A / H-2B / LCA files carry worksite city/state/postal but
**no worksite county**; the Addendum B file DOES carry
`PLACE_OF_EMPLOYMENT_COUNTY`, so it is the authoritative county source.
Scope: `starr` (county STARR, or a known Starr city), `rgv` (Hidalgo /
Cameron / Willacy county, or a known RGV city), `tx` (any other Texas
worksite).

**Secondary leg — MORVS mirror (REPORTED, never VERIFIED).** DOL's
files sit behind Akamai bot protection and answer HTTP 403 from some
networks (see Live evidence). Until the official files can be fetched
from the run host, the collector also pulls the MORVS mirror of the
same DOL data (CC0, source-linked to the DOL performance page, $0,
keyless) at `https://api.morvs.ai/api/v1/oflc/recent`. Mirror rows carry
no worksite city/county (state only), cap at 200 rows per program, and
lag the official release — they are a partial, stale-window Texas
sample, labeled REPORTED. Mirror rows whose case number already came
from the official leg are deduplicated, not re-emitted.

Each observation carries a label:

- **VERIFIED** — row present in the official DOL file, Texas worksite,
  with a case number, a case status, and a worker count or wage.
- **REPORTED** — row present in the official file but a key field is
  missing; or any mirror-leg row. Missing values stay `null`, never
  zero-filled.
- **UNKNOWN** — Texas row matched only via the worksite-city fallback
  when the worksite-state field itself is blank.
- **BLOCKED** — a whole leg could not be fetched, recorded per file/leg
  with the exact error.

Every observation records its source URL and UTC retrieval timestamp.

## How to run

```bash
cd builds/regional-capital
python3 oflc.py --out evidence/oflc_run_20261126.json
```

Options:

| Flag | Effect |
|---|---|
| `--fy 2026 --quarter Q4` | Fiscal year / quarter of the disclosure files (default: FY2026 Q4). |
| `--programs H-2A H-2B LCA` | Limit to some programs (default: all three). |
| `--no-addendum-b` | Skip the H-2A Addendum B worksite file. |
| `--no-mirror` | Skip the MORVS mirror leg (official files only). |
| `--mirror-limit 200` | Rows per program requested from the mirror (mirror caps at 200). |
| `--local-dir DIR` | Parse already-downloaded `.xlsx` files from DIR instead of fetching — for blocked hosts or offline runs. |
| `--out <path>` | Write result JSON (default: stdout). |

Stdlib Python only; no dependencies.

## Tests

```bash
cd builds/regional-capital
python3 -m unittest discover -s tests -v
```

22 tests for this sensor (offline fixtures — no network calls): scope
matching, synthetic `.xlsx` parsing (built in-memory with `zipfile`),
Addendum B county fields, Excel serial dates, URL candidates,
User-Agent latin-1 safety, mirror parsing, DOL-blocked/mirror-survives,
mirror dedup against the official leg, and `--local-dir` parsing.

## Suggested activation cadence

**Quarterly, within a week of OFLC's release announcement** (Q1 ~Feb,
Q2 ~May, Q3 ~Aug, Q4 ~Nov). The source updates only quarterly, so a
more frequent run adds nothing except a fresh mirror sample. Each run
is a fresh snapshot; compare `case_number` sets against the previous
run to surface new determinations.

## Live evidence (2026-11-26, retrieved 2026-11-26T19:43:38Z)

Full run: [evidence/oflc_run_20261126.json](evidence/oflc_run_20261126.json)

- **Official DOL leg: 4/4 files BLOCKED** — `ERROR: HTTPError: HTTP Error
  403: Forbidden` on both attempted URLs per file (subfolder + flat
  path). Verified the same day from this environment on the performance
  page itself, on the confirmed FY2025 Q4 record-layout PDF, and on all
  four `.xlsx` URLs: dol.gov answers Akamai `403 Forbidden` to this
  network regardless of URL or User-Agent. The block is on the source's
  bot protection, not proof the files are missing — the FY2026 Q4
  release was announced 2026-11-16 and the file-name stems are
  confirmed from the FY2026 Q3 / FY2025 Q4 releases. **Zero official
  rows scanned, zero VERIFIED observations.** Re-run from an unblocked
  host (or with `--local-dir` after a manual download) to get the
  VERIFIED Starr/RGV cut.
- **Mirror leg: 3/3 OK — 55 Texas observations, all REPORTED**
  (9 H-2A + 15 H-2B + 31 LCA) from 600 recent rows scanned
  (200/program). Decision dates 2026-03-30 → 2026-03-31 only: the
  mirror's newest data is FY2026 Q2 vintage, a full quarter behind the
  official Q4 release. 39 cases carry a worker count (260 workers
  requested in total); H-2B worker counts are all `null` (the mirror
  does not carry them for H-2B); certified-worker totals are `null`
  throughout (mirror carries requested only).
- **Starr County: 0 — RGV: 0.** Not "no activity": the mirror carries
  no worksite city or county, so no Starr/RGV subset can be drawn from
  this leg. The county cut depends entirely on the official files
  (Addendum B county field) and is UNKNOWN until an official fetch
  succeeds.
- Top Texas employers in the mirror window: The University of Texas at
  Austin (3 cases), OYH Construction Materials LLC (2), The University
  Of Texas At Dallas (2), University of North Texas (2). Top job
  titles: Agricultural Equipment Operators, Landscape Laborer /
  Laborers, Software Developer, Research Associate, Assistant Professor
  (2 cases each). Wages: 25 hourly ($11.81–$32.59/hr in the sample) and
  30 yearly ($66,025–$239,841/yr, LCA). One H-2A row lists employer
  city Progreso, TX — that is the *employer* city, not the worksite;
  do not read it as an RGV worksite.

## Cross-checks (REPORTED aggregates, not case rows)

- **LCA, Texas, FY2026 Q1–Q3: 109,130 positions certified (13.1% of
  the national total)** — from OFLC's official LCA Selected Statistics
  FY2026 Q3 PDF (data as of 2026-06-30), verified via text fetch
  2026-11-26: https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/FY26Q3/LCA_Selected_Statistics_FY2026_Q3.pdf
- **H-2A Addendum B, Texas, FY2025 Q4: 7,843 worksite rows** — from the
  us-data-index republication of the official file (last checked
  2026-11-10): https://us-uscis-case-status.us-data-index.com/datasets/h-2a_addendum_b_employ_fy2025_q4/
- **USCIS H-2A Employer Data Hub** (FY2015–FY2026 Q4, queryable by
  employer/city/state/ZIP, downloadable Excel/CSV) is an alternate live
  source for H-2A specifically — NOT wired into this collector (its
  download is an interactive form, not a stable URL):
  https://www.uscis.gov/tools/reports-and-studies/h-2a-employer-data-hub

## Limitations

- **The official leg is blocked from this environment (Akamai 403).**
  Until it runs from an unblocked host, this sensor reports the mirror
  sample only — Texas-level, stale-window, no county cut. That is the
  sensor's honest state, not a data gap to paper over.
- File-name stems for FY2026 Q4 follow the confirmed Q3 pattern; if
  OFLC renames a file, the collector records `ERROR` per file with the
  attempted URLs — check the performance page and update `FILE_SPECS`.
- The mirror's `recent` endpoint caps at 200 rows per program and
  returns only the most recent decision dates; it is a window, not a
  census. `total_workers` in mirror H-2B rows is always null.
- Main disclosure files have no worksite county: Starr/RGV matching
  from them rests on the worksite-city lists in `oflc.py`. The
  Addendum B file is the only county-authoritative source.
- `workers_certified` sums count only cases where DOL reported a
  certified number; a `null` total means "no certified counts in this
  cut", not zero workers.

## Guardrails

$0 recurring cost. No signup, no API key, no spending, no account
creation, no contacting anyone. Read-only public data (official DOL
files + a CC0 mirror of the same data). No secrets or live private
data in any file. Employer names and case numbers are public
disclosure data as published by DOL.
