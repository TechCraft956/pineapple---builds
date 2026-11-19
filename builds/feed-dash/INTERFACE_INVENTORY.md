# Interface inventory — Feed + Dash build (BUILD-20261117-002)
Verified by Everest 2026-11-17 in the recovered code before any edit.
GPT review patch step 1.

## 1. shared-feed (`recovered/shared-feed/`)
- `feed.py` — stdlib only, no deps. Two functions:
  - `read_feed()` → dict `{app_id: {app_name, status, last_updated, metrics, recent_events[-10:], actions}}`; `{}` on any failure.
  - `write_app_status(app_id, app_name, status, metrics=None, recent_events=None, actions=None)` — merges one app, atomic tmp+os.replace write, never raises.
- `feed.json` — last live state 2026-04-17, exactly 2 apps: `marketplace_scraper` (idle), `template_app` (idle).
- No HTTP surface, no auth, no opportunity records. The feed service keeps
  feed.py's write discipline (atomic replace) and merge semantics.

## 2. pineapple-Dash (`recovered/pineapple-Dash/`)
- Backend `backend/server.py` — FastAPI, router prefix `/api`, MongoDB via
  motor (`MONGO_URL`/`DB_NAME` env, required at import). ~80 defs. Verified
  by grep: **no `/api/feed` route exists anywhere in the recovered code** —
  the documented route is described in the mini-app template and bridge
  supplement but implemented nowhere. The Dash backend is NOT modified in
  this build; the feed service is a separate service (GPT: do not introduce
  a second competing feed service *inside* Dash — this one is the feed).
- Frontend `frontend/` — React (craco), `src/lib/api.js` axios client at
  `REACT_APP_BACKEND_URL + /api`; pages in `src/pages/`. Pre-existing state:
  - `Opportunities.jsx` was a 2-line re-export of `Overview` (placeholder).
  - `SystemHealth.jsx` is a real page polling `dashboardApi.overview()` every
    15s; its sections render from `overview` (services/agents/contract).
  - Pre-existing dependency conflict: `date-fns@^4.1.0` vs
    `react-day-picker@8.10.1` peer `date-fns@^2.28.0 || ^3.0.0` — `npm install`
    fails without `--legacy-peer-deps`. Not caused by this build; noted for
    any future frontend work.

## 3. Shared Opportunity Engine (`pineapple/opportunity-engine/`)
- `opportunity.schema.json` — "Pineapple Opportunity Record v0.2" (JSON Schema
  draft-07). Required: `id, type, title, source, collected_at,
  purchase_price, est_value, confidence, approval_status`. Enums for
  approval_status / evidence_quality / qualification / risk_level /
  liquidity. No `additionalProperties: false`, so provenance extensions are
  allowed. `est_value` is required-number — unknown values must NOT be
  written as 0 without a flag; this build adds `est_value_unknown: true`.
- `engine.py` — ranking over these records (not reused as a library here;
  the feed serves records, the engine consumes them).

## 4. Patent Radar items() contract (brief #1 — fixture only, module not built yet)
- `items()` returns dicts with title, category, source, action, est_value
  (number|null), risk (LOW/MED/HIGH), location, url, confidence (0–1, capped
  0.85 on sample data), plus idea fields. The writer adapter maps this onto
  the opportunity schema; the mapping is documented in
  `feed-service/writers/patent_radar_writer.py`. Fixture:
  `feed-service/fixtures/radar_items_fixture.json` (3 SYNTHETIC items).

## 5. Feed service contract (this build)
- `GET /health` → `{"status": "ok", "schema_version": 1}`
- `GET /api/feed/apps` → `{"schema_version": 1, "apps": [{app_id, app_name, status, last_updated, metrics, recent_events, actions}]}` (sorted by app_id)
- `POST /api/feed/apps/{app_id}` (bearer) → upserts one app status, feed.py merge semantics
- `GET /api/feed/opportunities?limit&offset&type&source&approval_status&sort=collected_at_desc|est_value_desc` → `{"schema_version":1, "total", "limit", "offset", "items":[...]}`
- `POST /api/feed/items` (bearer) → `{"schema_version":1, "inserted":[], "duplicates":[], "conflicts":[]}`; body `{"items":[...]}`; 400 empty/non-list, 401 missing/invalid token, 409 same-id-different-payload, 413 body > 1 MB, 422 schema validation errors listed per record
- Auth: reads unauthenticated by design (read-only dashboard polling, no
  secret in the React bundle); writes require `Authorization: Bearer
  <FEED_API_TOKEN>`. No roles in v1, so 403 is unused.
- Storage: `data/feed.json` (apps) + `data/opportunities.json` (records) +
  `data/audit.jsonl`; atomic tmp+replace writes; threading + fcntl lock;
  dedupe by `id`, canonical comparison ignores writer timestamps
  (`collected_at`, `provenance.retrieved_at`).
- CORS: allowlist from `FEED_CORS_ORIGINS` env (empty = no CORS).

## Gaps / assumptions found while building
- Dash backend needs MongoDB at import and points at a retired runtime
  folder (`/Users/DdyFngr/...pineapple-ops-runtime`); the frontend build is
  verified, but the full Dash backend was not run — out of scope for v1,
  which only touches the frontend's Opportunities + SystemHealth pages.
- The feed service is NOT deployed anywhere (no host, no TLS, no identity
  proxy). Deployment waits for Airam's access-model decision (brief:
  (a) login-gated hosted app [default assumption], (b) private tunnel/VPN,
  (c) read-only public view). Nothing in this build deploys.
