# pineapple-builds

Source snapshots of the Pineapple builds, with commit history — one snapshot
commit per build, pushed by Everest through the GitHub connector
(`push_files`). Owner: TechCraft956. Private.

## Layout

- `builds/<name>/` — one directory per build, mirroring that build's own
  source tree (code, tests, docs, small config).
- This README and `.gitignore` live at the root.

## Builds in this repo

| Build | What it is |
|---|---|
| auction-scout | Auction & Surplus Scout — Public Surplus + GSA lot pulls, deal-first ranking, four-track tagging |
| panopticon | Panopticon — public-data OSINT/recon: source registry, query planner, ethics gate, brief generator |
| town-vitals | Town Vitals — one-page Census ACS briefs per town (Roma, McAllen, …) |
| lake-capacities | Lake Capacities — Texas reservoir levels / % of capacity (TWDB + USGS) |
| print-queue | 3D Print Business Queue — ranked print/sell queue matched to filament on hand |
| patent-radar | Patent Radar — expired/expiring patent mining (USPTO ODP) → buildable product ideas |
| decision-engine | Decision Engine + Context Intake + Source Scanner trio |
| feed-dash | shared-feed service + Dash frontend |
| geoint | TerraRecon — RGV parcels + FEMA flood scoring |
| regional-capital | Regional Capital Radar — Starr County SBA loans, USAspending awards, TxDOT traffic (sensors #72/#31/#52), KoFile deeds (sensor #81) |
| regional-hazards | Regional Hazards — Starr County FEMA disasters/PA/NFIP claims, NWS weather + drought, EPA ECHO + FRS/TCEQ (sensors #57/#73/#74/#53/#75) |
| intelligence | 04_INTELLIGENCE group — 11 RGV public-record modules |
| marketplace-archive | Marketplace Scraper — ARCHIVE (vehicle financing deal optimizer), not an active build |
| os-modules | Remaining OS modules — 09_SENSORS, 07_NETWORK and related |
| school-assistant | School Scraper Assistant (from the new-folder repo) — adoption candidate |
| trading-lab | Trading lab — futures research / backtesting / ML (from localedge-site PR #2) |
| trend-scraper | 3D Trend Scraper — print-trend discovery with licence checks |

## What's excluded, and why

Snapshots carry **source only**. Excluded at selection time:

- `cache/`, `evidence/`, `data/`, `out/`, `output/` — run artifacts and
  datasets; large, regenerable, and not source.
- `__pycache__/`, `*.pyc`, `*.zip`, images and any binary, any file > 1 MB.
- Bulk data JSON (e.g. `finds.json`, `queue.json`, patent datasets) and
  fixture files over 100 KB.
- Anything matching secret patterns (`.env*`, `*credential*`, `*secret*`,
  `*.key`, `*.pem`) — and any text file whose contents trip a secret scan
  (key shapes or credential-looking assignments). Dropped files are listed
  in the sync notes, never silently.

## How snapshots are made

There is no local git push in Everest's environment (SSH is blocked and the
connector is the only write path). Snapshots follow the connector's
snapshot-push procedure:

1. Source files are selected from `~/workspace/pineapple/builds/<name>/`
   into the staging tree `~/workspace/github-staging/pineapple-builds/`
   under `builds/<name>/`, applying the exclusions above plus a secret scan.
2. Each push is one `push_files` snapshot commit on `main` with a NUL-
   delimited path manifest kept outside the staging tree.
3. Confirmed commit SHAs and exact path lists are recorded in the sync
   record adjacent to the staging dir
   (`pineapple-builds.muse-github-snapshot-sync.json`). That record is
   local-only metadata and is never pushed.

Limits of a snapshot: ≤ 2,000 files and ≤ 16 MiB of UTF-8 text per commit,
no deletions, no binaries, no branches/tags — a faithful source snapshot
with history, not a mirror of a local git repo.

The recovered original Pineapple repositories (pineapple-os,
marketplace-scraper, pineapple-Dash, shared-feed, localedge-site, …) live in
their own repos and are untouched by this one.
