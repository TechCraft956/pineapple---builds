# IPO, SPAC & S-1 pipeline — sensor #62 (`ipo_pipeline.py`)

## What it does

Scans the SEC daily master index (the nightly submissions feed) for
the last N days and lists every filing whose form is a registration
or pricing form, with company, CIK, filing date and accession.

Forms tracked: S-1, S-1/A (IPO registration), F-1, F-1/A (foreign
issuer), S-4, S-4/A (merger / SPAC business combination), 424B4
(final prospectus — pricing), 424B3, EFFECT (notice of
effectiveness).

An S-1 is a registration, not a completed IPO — the collector never
labels a filing as a completed offering. EFFECT + 424B4 together are
the closest thing to "priced and effective" in this feed.

## Run

```sh
python3 ipo_pipeline.py --days 5 --out evidence/ipo_pipeline_run_20261126.json
```

## Live evidence (2026-11-26)

170 pipeline filings (Nov 23–25: 35 / 77 / 58): S-1 15, S-1/A 11,
F-1 5, F-1/A 6, S-4 9, S-4/A 5, 424B4 1 (Yesway, Inc., Nov 23),
424B3 90, EFFECT 28. All 170 VERIFIED.

## Caveats

- Same-day runs see no index yet (posted end-of-day).
