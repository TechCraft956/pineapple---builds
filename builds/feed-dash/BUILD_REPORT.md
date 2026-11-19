# BUILD REPORT — Shared Feed + Pineapple Dash (BUILD-20261117-002)
Built by Everest 2026-11-17 (hourly build-brief pipeline run). Stage: VERIFIED.

## What was built (isolated workspace `~/workspace/pineapple/builds/feed-dash/`)
1. **Feed service** (`feed-service/`, FastAPI, Python 3.12 venv):
   - `GET /api/feed/apps` — the documented route that existed nowhere; serves
     the two historical apps from the recovered feed.json.
   - `GET /api/feed/opportunities` — Opportunity Engine schema v0.2 records,
     with limit/offset, type/source/approval_status filters, sort.
   - `POST /api/feed/items` — bearer-token writes (FEED_API_TOKEN env),
     per-record jsonschema validation, dedupe by id (canonical comparison
     ignores writer timestamps), 409 on same-id-different-payload,
     Idempotency-Key, 1 MB body limit, audit log (`data/audit.jsonl`).
   - `POST /api/feed/apps/{app_id}` — HTTP form of feed.py's
     write_app_status(), same merge semantics.
   - Storage: JSON files, atomic tmp+replace writes, threading + fcntl lock,
     swappable behind `store.py`. Reads unauthenticated by design (GPT
     patch: no secret in the React bundle); writes 401 without/invalid token.
2. **Radar writer adapter** (`writers/patent_radar_writer.py`): radar items()
   fixture → normalized opportunity records → authenticated POST. Unknown
   est_value kept as `est_value_unknown: true` (never confused with $0);
   expiring/filing items flagged REVIEW_REQUIRED / PENDING.
3. **Dash frontend hookup** (copy of recovered frontend; exactly 3 files changed):
   - `src/lib/api.js` — `feedApi` (`REACT_APP_FEED_URL`, default 127.0.0.1:8100)
   - `src/pages/Opportunities.jsx` — real view, polls every 30s, re-renders
     on change, degrades gracefully if the feed is down (was a 2-line
     re-export of Overview)
   - `src/pages/SystemHealth.jsx` — "Feed Apps" section polling `/api/feed/apps`
   - `npm run build` compiles clean (174.1 kB gzipped JS); bundle verified
     to contain the feed endpoints and `setInterval(h,3e4)`; built app serves
     HTTP 200. Two pre-existing dependency issues fixed at install time
     (documented, not code changes): date-fns peer conflict → `--legacy-peer-deps`;
     ajv 6 vs ajv-keywords 5 hoisting → pinned ajv@8.12.0.

## Acceptance evidence
- `pytest tests/ -v`: **11/11 pass** (apps seed, radar round-trip with schema
  validation on both ends, 401 unauthenticated, idempotent duplicate POST,
  409 conflict, 422 malformed, pagination/filter, restart persistence,
  5-thread concurrent writers, audit log).
- Live verification (`verify_live.py`, log `BUILD_LOG_live.txt`): service up;
  writer POSTed 3 fixture records live; GET returned all 3; unauthenticated
  POST → 401; poll 1 showed template_app idle, record changed via API,
  poll 2 showed running — change visible on next poll, no rebuild.
- One real bug found and fixed during testing: duplicate POSTs 409'd because
  the writer re-stamped `collected_at`; dedupe now compares canonical
  records ignoring writer timestamps.

## Not done / not deployed
- Nothing deployed. Deployment waits for Airam's access-model decision:
  (a) login-gated hosted app (default assumption), (b) private tunnel/VPN,
  (c) read-only public view. No host, TLS, or identity proxy exists yet.
- The Dash backend was not run (needs MongoDB + the retired ops-runtime
  folder); v1 only touches the frontend's Opportunities + SystemHealth pages.
- The "unauthenticated requests to the deployed feed are rejected" check is
  N/A until deployment; locally, unauthenticated *writes* are rejected (401)
  and reads are open by design.
- The radar writer used the SYNTHETIC fixture; the real radar module is
  brief #1 (BUILD-20261117-001), still GPT_REVIEWED, not yet built — the
  writer's `map_items()` is ready to take its real `items()` output.

## Files
- `feed-service/{app,store}.py`, `writers/patent_radar_writer.py`,
  `fixtures/radar_items_fixture.json`, `tests/test_feed_service.py`,
  `verify_live.py`, `BUILD_LOG_live.txt`
- `dash-frontend/` (3 src files changed; `build/` output included)
- `INTERFACE_INVENTORY.md`, `README.md`, this report
- Recovered originals untouched (verified by diff + md5).
