# ARCHIVE RECORD — marketplace-scraper

**Decision: ARCHIVE — do not rebuild the scraper.**
Written 2026-11-17 as Task 3 of BUILD-20261117-007
(`MARKETPLACE_ARCHIVE_BUILD_BRIEF.md`). The only code carried forward is the
Vehicle Financing Deal Optimizer, extracted standalone in this workspace
(`vehicle_deals.py` + `vehicle_deals_cli.py` + `test_vehicle_deals.py`,
24/24 tests passing — see `BUILD_REPORT.md`).

## What the repo was

`marketplace-scraper` — a Facebook Marketplace deal-hunting module for the
Pineapple Operator Dashboard. Public GitHub repo, 33 commits,
2026-04-16 → 2026-04-21; newest commit `9321601` ("feat: add approvals
module and update scrapers"). FastAPI + React, Playwright scraper with
stealth config, 0–100 deal scoring across 5 factors (price vs median,
urgency keywords, recency, images, distance), chainable smart filters,
SQLite storage with dedup and run history, SSE streaming to a React panel,
plus a Vehicle Financing Deal Optimizer MVP
(`POST /api/vehicle-deals/evaluate`).

Verified state (2026-11-17): code VERIFIED ACCESSIBLE, compiles clean,
30 Python files / 11,308 LOC, 52 files in the read-only snapshot
(`snapshot/`, `.git` and `__pycache__` excluded). Recovered originals
untouched — verified after the build by `git status` / `git diff HEAD`
(both empty) and by a recursive diff of the snapshot against the clone
(no differences); see `BUILD_REPORT.md` for the full verification note,
including that the pre-build md5 manifest was lost to a mid-session
`/tmp` cleanup.

## Verified current state — and what was never verified

- **README claim vs reality:** the README says "Complete,
  production-ready. 4,075 lines of real code." The Python alone is
  11,308 lines. The "production-ready" claim is unverified: no run history
  in the recovered repo proves a successful end-to-end live scrape against
  Facebook. The shared-feed entry for `marketplace_scraper` (last updated
  2026-04-17: 63 scraped, 11 passed filters, 7 new) is consistent with the
  module having run in April 2026, but it is not proof of a live Facebook
  scrape.
- **The repo's own test suite never tested the carried-forward piece:**
  `backend_test.py` (593 lines) is a live-endpoint suite (needs a running
  server + MongoDB) and contains no vehicle-deals test — only a
  `"category": "vehicles"` filter check. The extracted evaluator's tests in
  this workspace are new.
- **No cookies in the recovered repo:** there is no `data/` directory and no
  `fb_cookies.json` anywhere in the clone. Nothing had to be sanitized, and
  none was created, uploaded, or refreshed by this build.
- **Retired-state paths baked in:** `backend/approvals.py` and
  `backend/task_audit.py` persist to
  `/Users/DdyFngr/Desktop/Projects/pineapple-ops-runtime/state` — the
  retired Molt runtime (both Molt1 and Molt2 settled retired 2026-11-17).
  Those modules would fail or write to a nonexistent path on any current
  machine.
- **Its own ToS warning:** `backend/modules/marketplace_scraper/scraper.py`
  carries the disclaimer "Automated scraping may violate Facebook's ToS."

## Cookie-auth failure evidence (why the scraper is not rebuilt)

1. **The mechanism in the code.** Facebook access is cookie-based:
   `FB_COOKIES_PATH` (env, default `/app/cookies/fb_cookies.json`,
   `backend/server.py:83`), cookies uploaded via an endpoint
   (`_write_fb_cookies_upload`, `server.py:190`), Playwright launched with
   those cookies (`server.py:2528`); the module config schema defaults
   `cookies_path` to `data/fb_cookies.json`
   (`backend/modules/marketplace_scraper/config_schema.py:178`).
2. **The historical record.** The ChatGPT bridge supplement
   (`~/workspace/pineapple/bridge-supplement/01_RECOVERED_HISTORY.md`) lists
   "FB cookie auth" first among the key historical breakers, and records
   that "the code-based Facebook Marketplace scraper died on cookie auth;
   the working solution ever since is agents on the owner's signed-in
   connection." The 2026-11-17 repo census
   (`~/workspace/pineapple/recovery/REPO_CENSUS_2026-11-17.md`) records the
   same: scraping runs on exported Facebook cookies, which the README itself
   flags as likely against Facebook's terms, and "today's Deal Scout
   deliberately does not use this path (it uses Airam's signed-in Facebook
   connection instead)."
3. **Rebuilding it re-runs a known failure.** Cookie auth is the exact
   approach that already failed historically. Nothing in the recovered code
   changes that assessment — the scraper, stealth config, and retry logic
   are unchanged since April 2026.

## Supersession mapping — each scraper capability → the live capability

Live Deal Scout: Gate 2 live since 2026-11-14, adapter v0.5, ~4h sweeps,
Roma 60 mi + Laredo trailers/welders, price-drop tracking, FOR YOU
personal-use track, alerts in main chat 06:30–21:30 CT. Live operator
surface: shared feed + Dash (BUILD-20261117-002, VERIFIED 2026-11-17).
Live record schema: Shared Opportunity Engine (brief #2).

| Scraper capability | Live coverage |
|---|---|
| Facebook discovery (`scraper.py` Playwright) | **Deal Scout** — signed-in-session discovery, no cookies |
| Deal scoring 0–100, 5 factors (`scorer.py`) | **Deal Scout** Gates 1/2 + Opportunity Engine ranking |
| Chainable smart filters (`filters.py`) | **Deal Scout** Gate 1 batch + adapter v0.5 |
| SQLite dedup / scores / run history (`storage.py`) | **Deal Scout** seen-listings + Opportunity Engine records |
| Operator Dashboard surface (`server.py`, `frontend/*`, `module.py`) | **Shared feed + Dash** (BUILD-002, VERIFIED) |
| Ranked operator actions (`action_engine.py`) | **Deal Scout** screening + pipeline executive reporting |
| Buyer message drafts (`contact_drafter.py`, no auto-send) | **Deal Scout** draft messages, approval-gated, never auto-sent |
| Approval gating (`approvals.py`) | **Pineapple hard boundaries + Deal Scout approval gating** (module itself obsolete — retired state path) |
| Telegram alerts (`notifier.py`) | **Deal Scout** alerts in main chat (Telegram channel itself had the historical HTTP 409 breaker; not rebuilt) |
| Distance / travel tiers (`geo.py`) | **Deal Scout** transport math (~$0.30/mi round trip) |
| SSE event bus (`events.py`) | **Shared feed + Dash** |
| Unified deal briefing (`operator_console.py`, `operator_cell/console_view.py`) | **Deal Scout** sweep reports + pipeline executive reporting |
| Audit trail (`task_audit.py`) | **Opportunity Engine** outcome records + pipeline logs (module obsolete — retired state path) |
| Config validation (`config_schema.py`) | **Deal Scout** sweep config (goal parameters); the cookie field is obsolete |
| Vehicle Financing Deal Optimizer (`vehicle_deals.py`) | **NOT COVERED — extracted.** The only carry-forward. Pure payment math; Deal Scout scores listings but does no loan/payment math across scenarios. |
| Craigslist / Craigslist RSS / eBay / GovDeals / GovPlanet / PublicSurplus scrapers | **NOT COVERED.** Deal Scout is Facebook Marketplace only. Never wired into live Deal Scout; historical breakers on file (Craigslist DNS, eBay anti-bot). Archived, not built. |
| Screenshot OCR (`ocr.py`, GPT-4o Vision / Tesseract) | **NOT COVERED.** No live equivalent. Archived, not built. |
| Daily brief generator (`operator-cell/generate_brief.py`) | **NOT COVERED as a module** — reads retired `pineapple-ops-runtime` state. Function partially covered by pipeline executive reporting / Life Briefing (hands-off). |
| Legacy state refresh (`pineapple-state/refresh.py`) | **NOT COVERED / obsolete** — self-declared deprecated mirror. |
| Live-endpoint test suite (`backend_test.py`) | **NOT COVERED as an asset** — needs a running server + MongoDB; superseded for the carried-forward piece by `test_vehicle_deals.py`. |

## Full module inventory (Task 1)

30 Python files, 11,308 LOC. Every module carries a covered-by /
not-covered verdict in the table below; the supersession mapping above is
the same verdicts grouped by capability.

| File | LOC | Purpose | Verdict |
|---|---|---|---|
| `backend/server.py` | 3,089 | FastAPI app (DealScope API): MongoDB, scoring, SSE, cookie upload, scheduler, vehicle-deals endpoint | COVERED except the vehicle-deals endpoint, which is EXTRACTED |
| `backend/modules/marketplace_scraper/scraper.py` | 955 | Playwright Facebook Marketplace scraper, cookie auth, stealth, human-like delays | NOT COVERED — deliberately not rebuilt (cookie auth = known breaker) |
| `backend/modules/marketplace_scraper/scorer.py` | 853 | ResaleScorer, 0–150 across price-vs-median / urgency / recency / images / distance | COVERED by Deal Scout scoring |
| `backend/modules/marketplace_scraper/storage.py` | 597 | SQLite listings/scores/run history (aiosqlite), dedup | COVERED by Deal Scout + Opportunity Engine records |
| `backend_test.py` | 593 | Live-endpoint test suite (needs running server + MongoDB) | NOT COVERED as an asset; superseded by `test_vehicle_deals.py` |
| `backend/modules/marketplace_scraper/filters.py` | 503 | Chainable filter pipeline for listings | COVERED by Deal Scout Gate 1 / adapter v0.5 |
| `backend/modules/marketplace_scraper/module.py` | 384 | Dashboard module interface (fetch/stream) | COVERED by shared feed + Dash |
| `backend/scrapers/craigslist.py` | 349 | Craigslist HTML scraping (requests + BeautifulSoup) | NOT COVERED — archived, not built |
| `backend/notifier.py` | 339 | Telegram alerts for high-score deals | COVERED in function by Deal Scout alerts |
| `backend/modules/marketplace_scraper/config_schema.py` | 317 | Pydantic module config incl. `cookies_path` default | COVERED in function by Deal Scout config; cookie field obsolete |
| `backend/scrapers/ebay.py` | 319 | eBay Buy-It-Now / ending-soon (Finding API or HTML fallback) | NOT COVERED — archived, not built |
| `backend/scrapers/ocr.py` | 263 | Screenshot OCR via GPT-4o Vision, Tesseract fallback | NOT COVERED — archived, not built |
| `backend/action_engine.py` | 245 | Scored listings → ranked operator actions | COVERED by Deal Scout screening + Opportunity Engine |
| `backend/operator_console.py` | 229 | Unified deal briefing (analyst/CFO/CoS pipeline over MongoDB) | COVERED by Deal Scout reports + pipeline reporting |
| `backend/scrapers/govplanet.py` | 226 | GovPlanet equipment/vehicle auctions | NOT COVERED — archived, not built |
| `backend/scrapers/craigslist_rss.py` | 214 | Craigslist RSS feeds (stdlib only) | NOT COVERED — archived, not built |
| `backend/contact_drafter.py` | 200 | Buyer message drafts, no auto-send | COVERED in function by Deal Scout drafting |
| `backend/scrapers/publicsurplus.py` | 181 | PublicSurplus government surplus auctions | NOT COVERED — archived, not built |
| `backend/scrapers/govdeals.py` | 176 | GovDeals government auctions | NOT COVERED — archived, not built |
| `backend/approvals.py` | 175 | Approval manager; state in retired `pineapple-ops-runtime` | COVERED in function; module obsolete |
| `backend/geo.py` | 174 | Geographic distance / travel tier logic | COVERED by Deal Scout transport math |
| `backend/vehicle_deals.py` | 168 | Vehicle Financing Deal Optimizer (pure payment math) | NOT COVERED — EXTRACTED (only carry-forward) |
| `operator-cell/generate_brief.py` | 148 | Daily brief from `pineapple-ops-runtime` state | NOT COVERED as a module (retired state); function partially covered by pipeline reporting |
| `backend/operator_cell/console_view.py` | 112 | CLI terminal briefing via `/operator/console` | COVERED by feed/Dash + pipeline reporting |
| `backend/events.py` | 74 | SSE event bus | COVERED by shared feed + Dash |
| `backend/task_audit.py` | 69 | Task/audit records to retired runtime state | COVERED in function; module obsolete |
| `pineapple-state/refresh.py` | 347 | Legacy state mirror, self-declared deprecated | NOT COVERED / obsolete |
| `backend/modules/marketplace_scraper/__init__.py` | 9 | Module registration | COVERED (obsolete with module) |
| `backend/modules/__init__.py` | 0 | Package marker | — |
| `backend/scrapers/__init__.py` | 0 | Package marker | — |

Frontend (covered by shared feed + Dash, BUILD-002 VERIFIED):
`frontend/src/App.js` (779), `frontend/modules/MarketplacePanel.jsx` (739),
`frontend/src/index.css` (70), `frontend/public/index.html` (15),
`frontend/tailwind.config.js` (14), `frontend/src/index.js` (7),
`frontend/postcss.config.js` (6), `frontend/src/App.css` (1).

Docs / config / infra (reference only, preserved in the snapshot):
`architecture.md` (340), `README.md` (298),
`setup_instructions.md` (292), `memory/PRD.md` (92), `.gitignore` (81),
`GIT_INSTRUCTIONS.md` (108), `PUSH_TO_GITHUB.sh` (69),
`docker-compose.yml` (60), `Dockerfile` (30), `requirements.txt` (19),
`image_testing.md` (16), `backend/requirements.txt` (8),
`.emergent/emergent.yml` (4), `.gitconfig` (3).

## The decision

**ARCHIVE — do not rebuild the scraper.** The scraper's whole job
(discovery, scoring, ranking, alerting, dashboard) is already done live by
Deal Scout and the shared feed + Dash, without Facebook cookies. Its
Facebook access is cookie-based, the exact approach that already failed
historically. The Vehicle Financing Deal Optimizer is the only code carried
forward, because it is pure math with no Deal Scout equivalent, no scraping,
no account, and no network.

If Airam ever wants Facebook discovery beyond Deal Scout, that is a new
decision for him — not this brief. If he disagrees and wants the scraper
rebuilt, that is a separate decision; this record preserves the evidence
for the archive recommendation.

## Standing flag — GitHub token exposure (revocation UNVERIFIED)

A historical audit reported a GitHub token exposed in
`marketplace_scraper/.git/config` on the owner's machine copy. The
repo census (2026-11-17) corroborates via pineapple-os's
`SECURITY_ACTIONS.md`, which documents secret-like strings and `.env` /
credential files on the machine copy (including
`01_CORE/marketplace_scraper/.env`) and instructs manual rotation of, among
others, a GitHub token. The recovered GitHub clones were scanned this
session and contain **no credential-shaped strings in tracked code** — but
whether the historically exposed token was revoked remains **unverified**
and can only be confirmed on the owner's side. This flag is carried forward
here so it is not lost. **It is an owner-confirmation item, not a build
task: no credential was read, verified, rotated, or changed by this build,
and none was attempted.**

## What this build did NOT do

- No Facebook cookies created, uploaded, or refreshed; no Playwright
  scraper run against live Facebook; no seller contacted; nothing deployed,
  published, or pushed; no account touched; no production system touched.
- Recovered originals untouched (md5-verified before and after).
