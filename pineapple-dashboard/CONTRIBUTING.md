# Contributing

This repo is maintained by **Codex Mac Air** (the owner's agent) on behalf of
the owner, Airam. Outside contributions are welcome as suggestions, but
changes land only through the maintainer.

## How to propose a change

1. **Open an issue first** describing the change and why it helps. Small
   fixes (typos, dependency bumps) can go straight to a pull request.
2. **Fork and branch** from `main`. Keep one change per pull request.
3. **Run the checks before opening the PR:**
   - `npm install`
   - `npm run build` (client production build must pass)
   - `npm start` and confirm `GET /api/health` returns `{"ok":true,...}`
     and the page renders at `http://localhost:3001`.
4. **Never include live data.** The sample seed in
   `server/data/dashboard.sample.json` is the only data that ships.
   `server/data/dashboard.json` is gitignored for a reason — do not commit
   it, and do not paste real balances, positions, or activity text into
   tests or fixtures.
5. **No secrets, ever.** No API keys, tokens, passwords, or credentials in
   code, fixtures, or commit messages.

## Maintainer notes (Codex)

- The live dashboard that this repo mirrors is a Muse web artifact
  (`pineapple-dashboard-2`). The artifact keeps working; this repo is the
  runnable copy. Keep the data model and the action names in sync with it
  (see README.md, "Data model & actions").
- State writes go through the API actions in `server/index.js` and are
  persisted atomically to `server/data/dashboard.json`. Keep that file out
  of git.
- Default branch is `main`. Tag releases as `vX.Y.Z` when a change is
  worth naming.
