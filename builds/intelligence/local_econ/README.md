# Local Economic + Permits Radar

`04_INTELLIGENCE/local_econ` — surfaces **local economic signals for the Rio Grande Valley** and scores each for opportunity (contractor leads, real-estate tailwinds, marketplace demand), shaped to feed the Pineapple decision brief.

Status: **sample / offline**. No live network calls. Ships realistic, clearly-labeled SAMPLE data; real source portals are documented for later wiring.

## What it does

Reads `data/sample_signals.json` (~15 RGV signals across McAllen, Edinburg, Brownsville, Harlingen + Pharr, Raymondville, San Benito) covering six signal kinds:

| kind | what it is | primary opportunity lens |
|---|---|---|
| `building_permit` | new construction / renovation permits | contractor lead, supplier |
| `business_opening` | EDC announcements, new openings, leases | marketplace demand, services |
| `public_bid` | city/county RFPs & solicitations | direct contractor lead (deadline) |
| `federal_bid` | SAM.gov solicitations | contractor lead (registration req) |
| `road_project` | TxDOT lettings / infrastructure | civil subs + RE corridor lift |
| `council_econdev` | council agenda econ-dev items (380/TIRZ) | early-warning pipeline |
| `grant` | EDA / Texas / grants.gov windows | capital / positioning intel |

`items()` scores each signal across three lenses — `contractor_lead`, `realestate_lift`, `marketplace_demand` — adjusting a per-kind base score by **dollar size, deadline urgency, freshness, and geography** (RGV core counties rank higher than neighbors). It returns a ranked list shaped for the decision engine.

## Run

```bash
python local_econ.py --selftest   # health summary, exit 0 on success
python local_econ.py              # print scored radar to console
python local_econ.py --json       # dump items() as JSON
python local_econ.py --write      # write radar JSON to output/ and 00_PROCESSED
```

Pure Python 3.11 stdlib only. UTF-8. Windows host.

## Decision-engine contract

- `PLUGIN` — module-level dict: `id, name, category, authority, status="sample", inputs, outputs, sources[real URLs], safety`.
- `items() -> list[dict]` — each item has at least:
  `title, category, source, action, est_value (number|null), risk (LOW/MED/HIGH), location, url, confidence (0-1)`,
  plus extras: `id, kind, agency, posted_date, deadline, deadline_days, opportunity_score, opportunity_lens, best_lens, naics, summary, status`.

`category` maps signals to the brief's buckets: permits & road projects → `ASSETS`; bids, openings, council items, grants → `OPPORTUNITIES`. `est_value` carries the project/contract dollar amount; `action` includes the deadline countdown and the real source URL to verify.

## How it plugs into the decision brief

`decision_engine.py` ranks scored items into MONEY / ASSETS / OPPORTUNITIES / RISKS and logs recommended actions to `06_DECISION/outcomes_log.jsonl`. This module emits items already shaped for that flow (title/category/action/risk/est_value/confidence). A loader can call `local_econ.items()` directly, or read the written `00_PROCESSED/local_econ_radar.json`. No existing files are modified.

## Outputs (written only inside this folder or 00_PROCESSED)

- `output/local_econ_radar.json`
- `00_PROCESSED/local_econ_radar.json`

A write-guard refuses any path outside this module folder or `00_PROCESSED`.

## REAL live data sources (to wire later — currently offline, sample only)

Permits & city portals:
- McAllen Development Services — https://www.mcallen.net/departments/development-services
- McAllen Purchasing / Bids — https://www.mcallen.net/departments/purchasing/bids
- Edinburg Planning & Zoning — https://www.cityofedinburg.com/departments/planning_and_zoning
- Edinburg Council agendas/minutes — https://www.cityofedinburg.com/government/city_council/agendas_and_minutes
- Brownsville Building Inspection — https://www.cob.us/197/Building-Inspection
- Brownsville Agenda Center — https://www.cob.us/AgendaCenter
- Harlingen Permits & Licensing — https://www.myharlingen.us/179/Permits-Licensing

County, state & federal:
- Cameron County Purchasing/Bids — https://www.cameroncountytx.gov/purchasing/
- TxDOT letting & bids — https://www.txdot.gov/business/letting-bids.html
- TxDOT Pharr District — https://www.txdot.gov/about/districts/pharr.html
- SAM.gov opportunities — https://sam.gov/content/opportunities
- Grants.gov — https://www.grants.gov/search-grants
- US EDA funding — https://www.eda.gov/funding
- Texas Gov economic development finance — https://gov.texas.gov/business/page/economic-development-finance

Economic development corporations:
- McAllen EDC news — https://www.medc.org/news
- Edinburg EDC news — https://edinburgedc.com/news/

## Safety

Offline and read-only. Sample dollar amounts, dates, and project IDs are illustrative — **verify every signal on the official portal before acting**. Public bids are competitive with hard deadlines and bonding/registration requirements. This module never writes outside its own folder or `00_PROCESSED`.
