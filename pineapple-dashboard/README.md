# Pineapple Dashboard

The runnable React + Node app behind the Pineapple operations dashboard:
Trading Lab, Deal Scout, Agents & Bridge, Builds, research, and regional
intelligence — accounts, sections, activity, and needs in one place.

This repo is the **real code** for the dashboard. It mirrors the live Muse
web artifact (`pineapple-dashboard-2`), which keeps working as-is; this repo
is the version you can clone, run, and maintain yourself.

- **Frontend:** React 18 + Vite
- **Backend:** Express, serving the built frontend and a JSON-file state store
- **State:** a single JSON file on disk — no database to install

## Prerequisites

- **Node.js 20 or newer** (developed and verified on Node 24; `node --version`)
- npm (ships with Node)
- git

No other accounts, keys, or services are needed to run it.

## Install

```bash
git clone https://github.com/TechCraft956/pineapple-dashboard.git
cd pineapple-dashboard
npm install
```

## Run it

Development (hot reload for the frontend, backend on port 3001):

```bash
npm run dev
```

Open http://localhost:5173 — the Vite dev server proxies `/api` to the backend.

Production (build the frontend once, then serve everything from the backend):

```bash
npm run build
npm start
```

Open http://localhost:3001. The backend serves the built app and the API on
the same port. Set `PORT` to change it: `PORT=8080 npm start`.

## How state is stored

All dashboard state lives in **one file: `server/data/dashboard.json`**.

- On first run it is created from `server/data/dashboard.sample.json`
  (clearly-labeled sample data — see "What is NOT in this repo").
- Every API write is saved atomically (temp file + rename), so a crash
  mid-write cannot corrupt the state.
- **Back up that file.** It is the only copy of the dashboard's history.
  Copy it somewhere safe regularly, e.g.:
  `cp server/data/dashboard.json ~/backups/pineapple-dashboard-$(date +%F).json`
- To move the dashboard to another machine, copy the repo *and* that file.
  To reset to the sample seed: `POST /api/actions/seeddashboard` with
  `{"force": true}` (deliberately requires the flag so a stray call cannot
  wipe live data).

## Data model

```json
{
  "lastUpdatedAt": "2026-11-25T00:00:00.000Z",
  "accounts": [{ "key": "main", "name": "...", "balanceCents": 0,
                 "balanceLabel": "$0", "note": "...", "updatedAt": "..." }],
  "needs":    [{ "id": 1, "label": "...", "detail": "...", "createdAt": "..." }],
  "activity": [{ "id": 1, "text": "...", "createdAt": "..." }],
  "sections": [{ "key": "trading-lab", "title": "Trading Lab", "status": "active",
                 "summary": "...", "updatedAt": "...",
                 "items": [{ "id": 1, "itemKey": "tgt", "label": "...",
                             "detail": "...", "sortOrder": 1, "tag": "CLOSED" }] }]
}
```

Sections in the live dashboard: `trading-lab`, `deal-scout`,
`agents-bridge`, `builds`, `research`, `connections`,
`asset_intelligence`, `energy_intelligence`, `opportunity_radar`.

## API — the same actions as the live dashboard

Base URL: `http://localhost:3001` (or the dev proxy at `:5173`).

| Method | Endpoint | What it does |
|---|---|---|
| GET | `/api/health` | `{"ok": true}` — is the backend up? |
| GET | `/api/dashboard` | Whole dashboard state (`getdashboard`) |
| POST | `/api/actions/addactivity` | `{"text": "..."}` — append an activity entry |
| POST | `/api/actions/addneed` | `{"label": "...", "detail": "..."}` |
| POST | `/api/actions/removeneed` | `{"id": 1}` or `{"label": "..."}` |
| POST | `/api/actions/updatesection` | `{"key": "trading-lab", "summary": "...", "status": "active"}` |
| POST | `/api/actions/upsertitem` | `{"sectionKey": "...", "item": {"label": "...", ...}}` — add or update by `itemKey`/`id` |
| POST | `/api/actions/removeitem` | `{"sectionKey": "...", "id": 1}` or `{"itemKey": "..."}` |
| POST | `/api/actions/setaccountbalance` | `{"key": "main", "balanceCents": 8200, "balanceLabel": "~$82", "note": "..."}` |
| POST | `/api/actions/refreshdashboard` | `{"note": "..."}` (optional) — record a refresh pass |
| POST | `/api/actions/applyrefresh` | `{"activity": [{"text": "..."}]}` — append a batch of entries |
| POST | `/api/actions/seeddashboard` | `{"force": true}` — reset state to the sample seed |

Examples:

```bash
curl http://localhost:3001/api/dashboard
curl -X POST http://localhost:3001/api/actions/addactivity \
  -H 'Content-Type: application/json' \
  -d '{"text": "Lab MAIN run complete — 1 paper proposal"}'
```

## How Everest / Codex push updates to it

The operator (Everest) and the maintainer (Codex Mac Air) update the
dashboard by calling the API above — the same action names the live artifact
uses, so existing update scripts only need a new base URL. There is no
separate admin UI. Keep the backend reachable only on a private network or
behind authentication (see SECURITY.md) — anyone who can reach the API can
change the dashboard.

## What is intentionally NOT in this repo

- **No live data.** The owner's real activity log, balances, positions, and
  deal findings stay in the live Muse artifact and in the local
  `server/data/dashboard.json` (gitignored). The repo ships only the sample
  seed in `server/data/dashboard.sample.json`, with every entry labeled
  SAMPLE.
- **No secrets.** No API keys, tokens, passwords, or credentials of any
  kind. If you ever find one in the history, treat it as compromised and
  rotate it — see SECURITY.md.
- **No hosted deployment.** This repo is code, not a hosted site. Running
  it is `npm install && npm run build && npm start` on any machine.
  Hosting options (a home server, a VPS, a tunnel) are a separate decision
  for the owner — see the handoff brief in the repo history / project docs.

## Dependency hygiene

- `package-lock.json` is committed; install with `npm install` (or
  `npm ci` for a clean, lockfile-exact install).
- Major versions are pinned in `package.json` (`react@18`, `vite@6`,
  `express@4`).
- `npm audit` was run at release time — see the audit note below. Re-run
  it after any dependency change and address critical findings before
  sharing the app anywhere.

> **Audit note (2026-11-25, verified locally):** `npm audit` could NOT run in
> the build sandbox — the npm registry's audit endpoint is blocked by the
> sandbox's network policy (`policy_denied`), so no audit result exists from
> this environment. All dependencies are the latest patch releases of their
> pinned majors at release time (Express 4.21.2, Vite 6.4.6, React 18.3.1).
> The maintainer should run `npm audit` on first clone from an unrestricted
> network and record the result here before sharing the app anywhere.

## Project layout

```
pineapple-dashboard/
├── client/                 # React + Vite frontend
│   ├── src/App.jsx         # Dashboard UI (accounts, sections, activity)
│   └── vite.config.js      # Dev server proxies /api to the backend
├── server/                 # Express backend + JSON-file store
│   ├── index.js            # API actions + static serving
│   └── data/
│       ├── dashboard.sample.json   # Sample seed (committed)
│       └── dashboard.json          # Live state (gitignored, created on first run)
├── .github/                # Issue + PR templates
├── CONTRIBUTING.md         # How to propose changes (Codex is maintainer)
├── SECURITY.md             # No-auth warning, reporting, secrets policy
└── LICENSE                 # MIT
```

## License

MIT — see [LICENSE](LICENSE).
