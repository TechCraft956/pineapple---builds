# Patent / Product-Opportunity Radar

`04_INTELLIGENCE/patent_radar/`

Surfaces **buildable or licensable product ideas** from patent activity, biased
toward **3D-printable / cheap-to-manufacture** items the owner can prototype
locally in the Rio Grande Valley.

## What it does

Reads patent records and classifies each into one of three signal types, then
turns it into a ranked product-opportunity idea:

| status | meaning | how to use it |
|--------|---------|----------------|
| `expired` | term ended / lapsed -> **public domain** | build & sell freely |
| `expiring` | expires within a window | license or design-around; be first to market |
| `filing` | newly published application | **trend/whitespace signal only** - do not copy a live application |

For every patent it produces an idea with:

- `idea` - one-line buildable concept
- `monetization_path` - how to make money from it (direct sale, license, adjacent build)
- `difficulty` - `TRIVIAL` / `LOW` / `MEDIUM` / `HIGH` (manufacturability)
- `capital_needed` - rough dollar range to a first unit
- `prototype_steps` - concrete steps from patent figures to a validated v1
- `opportunity_score` - 0-100 blend of status + manufacturability + demand + 3D-printability

## Scoring

`opportunity_score = 0.40*status + 0.30*manufacturability + 0.30*demand (+0.10 if 3D-printable)`,
scaled to 0-100. Expired + trivial-to-print + high-demand items rise to the top.

## Run

```bash
python patent_radar.py              # print ranked ideas, write output/ideas.json
python patent_radar.py --selftest   # health check, exits 0 on success
python patent_radar.py --json       # dump items() as JSON
python patent_radar.py --quiet      # write output, no table
```

## Data

`data/sample_patents.json` — **~10 clearly-marked SAMPLE records** modeled on the
*shape* of real USPTO / PatentsView records. Patent numbers, dates and assignees
are illustrative. The file's `_meta` block documents the real source URLs and the
US patent-term rules (20 years from filing for utility patents; maintenance-fee
lapses can drop a patent into the public domain early).

This module is **offline** and **read-only**. It never fetches the network and
writes only inside this folder (`output/`) and `00_PROCESSED/opportunities/`.

## REAL live sources (for later wiring)

- **PatentsView API** (free structured JSON): https://search.patentsview.org/api/v1/patent/ — docs: https://search.patentsview.org/docs/
- **PatentsView bulk download tables**: https://patentsview.org/download/data-download-tables
- **USPTO Patent Public Search** (replaces PatFT granted + AppFT applications full-text): https://ppubs.uspto.gov/pubwebapp/
- **USPTO Maintenance Fee Events bulk data** (detect EARLY lapses -> public domain): https://bulkdata.uspto.gov/
- **USPTO patent-term rules**: https://www.uspto.gov/patents/laws/patent-term
- **Google Patents** (browse + legal status): https://patents.google.com/
- **Google Patents Public Datasets on BigQuery** (`patents-public-data`): https://console.cloud.google.com/marketplace/product/google_patents_public_datasets/google-patents-public-data

### Wiring sketch
1. Query **PatentsView API** for utility patents by CPC class + grant date; compute
   `expiration_date = filing_date + 20y` and bucket into expired / expiring.
2. Cross-reference **USPTO Maintenance Fee Events** to catch patents that lapsed
   EARLY (non-payment) — those enter the public domain ahead of schedule.
3. Pull **new applications** (filing signal) for trend/whitespace detection.
4. Re-verify legal status on **Google Patents / USPTO Patent Center** before acting.

## How it plugs into the decision brief

`decision_engine.py` aggregates opportunity items from modules. This module exposes:

- `PLUGIN` — module-level dict (`id`, `name`, `category="OPPORTUNITIES"`, `authority`,
  `status="sample"`, `inputs`, `outputs`, `sources`, `safety`).
- `items()` — list of items in the decision-engine contract: `title`, `category`,
  `source`, `action`, `est_value` (number|null), `risk` (`LOW`/`MED`/`HIGH`),
  `location`, `url`, `confidence` (0-1), plus the richer idea fields.

`est_value` is a rough monthly-upside estimate; `confidence` is capped (<=0.85)
because the data is sample. Items land in the `OPPORTUNITIES` decision bucket.

Output is also mirrored to `00_PROCESSED/opportunities/patent_radar_ideas.json`
when the Pineapple root is reachable.

## Safety / disclaimer

**Not legal advice.** "Expired" here flags a *public-domain candidate* — always
re-verify in-force status and any continuation/term-extension before building or
licensing. Newly-filed applications are trend signals; do **not** copy a pending
application.
