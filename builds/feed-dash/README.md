# Feed + Dash build (BUILD-20261117-002)

Isolated build workspace. Recovered originals were copied, never modified:
`recovered/shared-feed/`, `recovered/pineapple-Dash/frontend/`,
`pineapple/opportunity-engine/opportunity.schema.json`.

## Layout
- `feed-service/` — FastAPI feed service (Python 3.12)
  - `app.py` — routes (see INTERFACE_INVENTORY.md §5)
  - `store.py` — JSON storage, atomic writes, locks, audit log
  - `writers/patent_radar_writer.py` — radar items() → feed adapter
  - `fixtures/radar_items_fixture.json` — 3 SYNTHETIC radar items
  - `data/` — seed `feed.json` (copy of recovered), `opportunity.schema.json`
  - `tests/test_feed_service.py` — 11 tests
  - `verify_live.py` — live round-trip + poll-change verification
- `dash-frontend/` — copy of recovered Dash frontend with 3 files changed:
  - `src/lib/api.js` — added `feedApi` (`REACT_APP_FEED_URL`, default `http://127.0.0.1:8100`)
  - `src/pages/Opportunities.jsx` — real view polling `/api/feed/opportunities` every 30s
  - `src/pages/SystemHealth.jsx` — added "Feed Apps" section polling `/api/feed/apps`
- `INTERFACE_INVENTORY.md` — verified interfaces of all three components
- `.venv/` — Python venv (fastapi, uvicorn, httpx, pydantic, jsonschema, pytest)

## Run the service
```bash
cd feed-service
FEED_API_TOKEN=<token> FEED_CORS_ORIGINS=http://localhost:3000 \
  ../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8100
```
## Run the tests
```bash
cd feed-service
../.venv/bin/python -m pytest tests/ -v
```
## Run the writer (fixture)
```bash
cd feed-service
FEED_URL=http://127.0.0.1:8100 FEED_API_TOKEN=<token> \
  ../.venv/bin/python writers/patent_radar_writer.py fixtures/radar_items_fixture.json
```
## Build the frontend
```bash
cd dash-frontend
npm install --legacy-peer-deps   # pre-existing date-fns peer conflict, see inventory
REACT_APP_FEED_URL=http://127.0.0.1:8100 npm run build
```

## Status
Built + verified 2026-11-17 (see BUILD_REPORT.md). NOT deployed — deployment
waits for Airam's outside-network access decision.
