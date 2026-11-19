# BUILD REPORT — 3D Trend Scraper (BUILD-20261117-003)
Built by Everest 2026-11-17 (hourly build-brief pipeline run).
Workspace: `~/workspace/pineapple/builds/trend-scraper/` (isolated copy;
recovered originals verified untouched via `git status` — clean).

## What was built (all 6 build tasks)

1. **Packaging + hygiene.** `requirements.txt` with pinned versions
   (verified install in a clean venv); `run_scrapers.py` runs from the
   repo root (`python -m src.run_scrapers --help` exits 0, no browser, no
   network); GrabCAD driver creation moved into `create_driver()` (no
   import side effect); `logs/` created defensively; `.env.example`
   documents GrabCAD vars (no real `.env` committed; credential scan clean).
   One fix found during install: `undetected-chromedriver==3.5.5` imports
   `distutils` (removed in Python 3.12) — pinned `setuptools==80.9.0` as
   the shim until uc is fixed.
2. **Normalized output.** ONE trend record (`src/models.py`): source,
   title, url, author, licence, likes, downloads, remixes,
   collected_at_utc, spike, filament_fit, sellable + reason, confidence.
   Every scraper + the paste parser emits it. `src/writers/feed_writer.py`
   maps it onto the feed's opportunity schema v0.2 (`type sellable_print`,
   est_value unknown ⇒ 0 + `est_value_unknown: true`, PENDING +
   REVIEW_REQUIRED, licence + sellability in provenance).
3. **Scrapers rebuilt.**
   - Thingiverse: search/category pages with counts (was homepage-only
     top-5 titles); licence enrichment per model page. Parsers are pure
     functions over HTML, offline-testable.
   - Printables: NEW scraper, same record shape (search + model page).
   - Google Trends: terms refreshed to sellable-prints categories
     (miniatures, organizers, tools, household, toys/games); 429 doubling
     backoff + 120 s delay kept; CSV-export fallback parser added.
   - Reddit: claim DELETED from the README (no scraper ever existed);
     not implemented — no phantom sources.
4. **Licence + sellability filter** (`src/licensing.py`, GPT hardening
   folded): unknown licence is a hard default — `sellable: false`, reason
   `licence: unknown`. Sellable only on a verbatim licence, proven per
   model, that affirmatively permits commercial use. NC ⇒ false;
   no-derivatives ⇒ false (conservative); unrecognized ⇒ false.
   Filament fit is a labelled heuristic against the owner's filament.
5. **Offline fixtures + tests.** Dated fixtures under `tests/fixtures/`
   (see SELECTORS.md for provenance — synthetic vs recorded is labelled
   per file). Old live-only test is now opt-in (`pytest --live`).
6. **GUI kept as manual-paste fallback** (`src/gui.py`): opens Thingiverse /
   Printables / Google Trends, parses pasted text into the SAME record
   shape, saves JSON + CSV. Headless equivalent: `--paste-file`.

## Acceptance evidence

- Clean-venv install + `--help`: **pass** (fresh venv in workspace —
  `/tmp` is a 512 MB tmpfs and ran out of space mid-install; the clean
  venv was built under `~/workspace/` instead and removed after).
  All imports OK; `--help` exits 0; full suite passes in the clean venv.
- `pytest tests/ -q`: **27 passed, 1 skipped** (the skipped one is the
  opt-in live test). Covers schema validation, licence filter (CC-BY-NC /
  CC-BY / licence-less ⇒ exactly one sellable:true), spike threshold
  boundary, empty/partial pages, paste parser on the real recording
  (20 records), trends CSV parsing, feed mapping, GrabCAD import with no
  browser launch.
- Fixture run (`python -m src.run_scrapers`): **28 records** — 20
  gui_paste (Thingiverse), 5 google_trends, 3 printables. All
  `sellable: false` (no licence proven in fixtures — the hard default
  working as designed). Output: `data/trend_records.json/.csv`.
- Feed round-trip, live (`verify_feed_roundtrip.py`): real feed service
  started on a scratch data dir (feed-dash code read, never modified);
  **28/28 records POSTed (200) and GET back unchanged in meaning**
  (title, sellable, verbatim licence, est_value_unknown, PENDING);
  unauthenticated POST → **401**. Exit 0.
- No credentials in the repo; no `.env` committed (scan clean).

## Selector verification (dated, see SELECTORS.md)

- **Printables VERIFIED live 2026-11-17** (text fetch): search result
  links `a[href^="/model/"]`; model page title/author (`dasfrodo`),
  description, rating `4.8571428571/5 (21 ratings, 32 reviews)`.
  Licence + likes/downloads are client-rendered — NOT in the text fetch,
  so the parser leaves them unknown (never invented); Selenium path to
  confirm.
- **Thingiverse BLOCKED live 2026-11-17**: search-page fetch returned
  HTTP 403 (anti-bot); not retried. Card selectors retained from the
  recovered code + verified against the recorded real paste. Live
  re-verification needs a browser-agent run on the owner's signed-in
  session (brief routing).
- Google Trends CSV shape verified against the real 2024 recording;
  refreshed terms are code-only (no live pytrends call made).
- GrabCAD selectors NOT verified — login deferred, no live attempt.

## Bugs found and fixed during the build

1. `undetected-chromedriver 3.5.5` fails to import on Python 3.12
   (`distutils` removed) — fixed with pinned `setuptools==80.9.0`.
2. Fixture run emitted the same Printables model twice (search + model
   page) → feed 409'd on the duplicate id. Fixed: the model page now
   enriches the search record instead of appending a second record.
   Regression test added (`test_fixture_run_records_have_unique_feed_ids`).
3. Printables author regex read `<h1>` (title only) instead of `<title>`
   (which carries "by dasfrodo") — fixed, test added.

## Not done / deferred (exact reasons)

- **Thingiverse live selector re-verification** — blocked by HTTP 403 on
  2026-11-17; needs a browser-agent run on the owner's signed-in session.
  The scraper code is written and fixture-tested; only the live
  confirmation is pending.
- **Printables licence/counts selectors** — provisional until a live
  browser run confirms the client-rendered fields.
- **GrabCAD live pull + login** — DEFERRED per the brief (owner decision):
  no login attempted, no credentials used. Code path is ready.
- **Live Google Trends pull with refreshed terms** — not run (pytrends
  rate-limit caution); opt-in via `--live --source google_trends`.
- **Nothing deployed.** The feed round-trip ran against a local scratch
  instance; no service was started persistently, nothing published.

## Files

- `src/{models,licensing,run_scrapers,gui}.py`
- `src/scrapers/{thingiverse,printables,google_trends,grabcad}_scraper.py`
- `src/processors/{data_cleaner,text_extractor,paste_parser}.py`
- `src/writers/feed_writer.py`
- `tests/{test_trend_scraper,test_feed_roundtrip,conftest}.py`,
  `tests/fixtures/*`, `pytest.ini`, `requirements.txt`, `.env.example`
- `README.md`, `SELECTORS.md`, `verify_feed_roundtrip.py`, this report
- `data/trend_records.{json,csv}` (fixture-run output), `logs/scraper.log`
- `.venv/` (build venv; `pip install -r requirements.txt` reproduces it)
