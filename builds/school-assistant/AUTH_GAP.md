# Auth Gap — School Scraper Assistant (BUILD-20261117-008)

**Status: NO authentication exists in this app. Verified by code read
2026-11-17 — there is no login, token, session, or per-user concept
anywhere in `TechCraft956/new-folder`.**

## What is true today
- `main.py` exposes the whole API with no auth check on any route.
  Anyone who can reach the port can list/create courses, ingest text,
  read, edit, confirm, and delete-equivalent (status/ignore) every
  stored school item, and read the daily brief.
- Storage (`storage.py`) is plain JSON files under `memory/school/`
  (env `SSA_MEMORY_ROOT`). There is **no user concept**: no user id on
  any record, no per-user scoping, no ownership check. Two users would
  silently share one dataset.
- CORS was tightened in this build (Task 3) to localhost-only origins
  by default, GET/POST only — but CORS is a browser policy, not
  authentication. Any non-browser client (curl, a script, another
  service on the machine) is unaffected by it.

## What this means
- **Local-only use (same machine, owner only): acceptable.** This is
  how the app was written and how it was verified in this build.
- **Anything else: NOT acceptable until the prerequisites below are met.**
  Do not put it on a shared network, a server, a tunnel (ngrok etc.),
  or behind the Pineapple shared feed in its current state.

## Exact prerequisites before ANY exposure or shared-feed wiring
1. **Authentication** — pick one and implement it; none exists today:
   - simplest local option: a bearer token checked by FastAPI
     dependency on every `/school` route (token from env, never in code);
   - or put the app behind an authenticated reverse proxy / identity
     provider and reject unauthenticated requests at the proxy.
2. **Per-user scoping** — add a user/owner id to `Course`, `SchoolItem`,
   `InferredTask`, `CorrectionRecord`, and `IngestionLog`; every storage
   read/write must filter by the authenticated user. (Today the storage
   layer cannot express "my items" at all.)
3. **Transport** — serve only over HTTPS (or localhost-only) once it
   leaves the machine; never plain HTTP on a network.
4. **Secrets handling** — any token/password lives in env / the vault,
   never in the repo, the JSON store, or logs.
5. **Re-verify** — after 1–4, re-run the full test suite plus a live
   unauthenticated-request probe (expect 401 on every route) before any
   feed wiring is attempted.

## What was deliberately NOT built here
No auth system was built in this brief (per the brief, Task 3). The
CORS tightening in `main.py` (localhost-only default, configurable via
`SSA_CORS_ORIGINS`) reduces drive-by browser abuse only; it does not
close the gap above.
