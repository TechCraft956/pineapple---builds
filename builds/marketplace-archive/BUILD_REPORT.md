# BUILD REPORT — Marketplace Scraper archive (BUILD-20261117-007)

Built 2026-11-17 in the isolated workspace
`~/workspace/pineapple/builds/marketplace-archive/` per
`~/workspace/pineapple/build-briefs/MARKETPLACE_ARCHIVE_BUILD_BRIEF.md`
(all GPT gates accepted, none rejected; GPT review was brief-only —
BLOCKED_SOURCE_UNAVAILABLE is a GPT-side access limit, not a brief defect).

## What was built

An ARCHIVE, not a scraper rebuild. Four deliverables, all five brief tasks
done:

1. **Full module inventory** — every module inventoried with purpose, LOC,
   and a covered-by / not-covered verdict (30 Python files, 11,308 LOC;
   frontend + docs/config listed too). Recorded in `ARCHIVE_RECORD.md`.
2. **Extracted Vehicle Financing Deal Optimizer** — `vehicle_deals.py`
   copied byte-identical from the recovered clone (diff-verified), plus a
   standalone CLI (`vehicle_deals_cli.py`: `--json` in, ranked JSON out,
   exit 0/2) and a 24-test suite. It imports only `typing` + `pydantic` —
   verified by AST and by a runtime `sys.modules` check in a subprocess;
   no scraper, dashboard, or Facebook code; no network in tests.
3. **Archive record** — `ARCHIVE_RECORD.md`: what the repo was, verified
   state, supersession mapping (every capability → the live Deal Scout /
   feed capability), cookie-auth failure evidence, the ARCHIVE decision,
   and the standing GitHub-token flag carried forward (revocation
   unverified — not attempted, not a build task).
4. **Read-only snapshot** — `snapshot/` (52 files, code tree only, no
   `.git`, no `__pycache__`), labelled historical in
   `snapshot/SNAPSHOT_README.md`. Not a build input.
5. **Nothing cookie/live** — no Facebook cookies created, uploaded, or
   refreshed; the Playwright scraper was not run against live Facebook; no
   seller contacted; nothing deployed, published, or pushed.

## Test evidence (exact)

Command: `.venv/bin/python -m unittest test_vehicle_deals -v`
(pydantic 2.14.3 in the workspace venv; system Python has no pydantic.)

**24 tests, 0 failures, 0 errors — OK (1.5 s).** Breakdown:

- **Payment math vs hand-computed fixtures (5 fixtures + 2 checks):**
  fixtures were computed independently with Python's `decimal` module
  (28-digit precision) in `/tmp/fixtures.py`, then frozen in the tests.
  - F1 — $12,000 ask, $600 fees, $2,000 down, 6% / 60 mo:
    financed $10,600.00, payment $204.93, interest $1,695.66,
    total acquisition $14,895.66, spread −$1,895.66 ✓
  - F2 — 0% APR: $9,000 / 36 mo → payment $250.00 exactly, interest $0.00 ✓
  - F3 — $20,000 ask, $1,000 fees, $5,000 down, 9.9% / 72 mo:
    financed $16,000.00, payment $295.61, interest $5,283.72,
    total $27,283.72 ✓
  - F4 — full down payment ($8,400 on $8,000 + $400 fees): financed $0.00,
    payment $0.00, interest $0.00, total $8,800.00 ✓
  - F5 — $15,500 ask, $775 fees, $3,000 down, 7.25% / 48 mo:
    financed $13,275.00, payment $319.43, interest $2,057.56,
    total $19,107.56 ✓
  - Down-payment monotonicity: $8,000 down beats $2,000 down on payment
    and interest ✓
- **Recommendation boundaries (3 fixtures, every score term hand-checked
  in `/tmp/verify_scores.py` before freezing):**
  - PURSUE — 2018 Tacoma, $8,000 ask vs $12,000 FMV, 4% / 48 mo:
    score 95, payment $167.09, interest $620.08, total $9,420.08,
    spread +$2,579.92 ✓
  - NEGOTIATE — 2019 F-150, $11,000 ask vs $12,500 FMV, 5.5% / 48 mo:
    score 54, payment $232.56, interest $1,163.11, total $13,163.11,
    spread −$663.11 ✓
  - PASS — 2012 Silverado, $18,000 ask vs $12,000 FMV, 12% / 84 mo,
    auction/rebuilt: score 0, payment $335.40, interest $9,173.76,
    total $30,173.76, spread −$18,173.76 ✓
  - Ranking: shuffled input `[PASS, NEGOTIATE, PURSUE]` → ranks 1/2/3 in
    pursue/negotiate/pass order, `best_deal` = the Tacoma, scores strictly
    descending ✓; same input → byte-identical output (pure function) ✓
- **Invalid inputs (17 bad-deal variants + 4 structural checks):** asking
  ≤ 0, APR outside 0–35, term outside 12–96, down payment exceeding
  price + fees, year outside 1980–2100, mileage outside 0–500,000, FMV 0,
  title < 3 chars, bad `seller_type` / `title_status`, condition > 10,
  negative distance — all rejected with `ValidationError` ✓; empty deals
  and 11 deals rejected, 10 deals accepted, missing required field
  rejected ✓; down payment exactly equal to price + fees is valid
  (financed $0.00) ✓
- **Import isolation (3 tests):** AST shows `vehicle_deals.py` imports only
  `__future__` / `pydantic` / `typing` ✓; fresh-subprocess `sys.modules`
  contains none of playwright / facebook / fastapi / requests / bs4 /
  aiohttp / aiosqlite / pymongo / selenium / uvicorn / scraper / dashboard ✓;
  md5 of the extracted file matches the recovered original ✓
- **CLI (6 tests):** file input ranks correctly (best_deal pursue,
  score 95) ✓; stdin input works ✓; `--output` writes the file and prints
  nothing ✓; invalid JSON and invalid deal both exit 2 with empty stdout
  and an error on stderr ✓; runs from an unrelated cwd with only
  `PYTHONPATH` set (standalone) ✓

## Verification of originals untouched

- An md5 manifest of all 82 non-`.git` files in the recovered clone was taken
  before the build, but `/tmp` was cleaned mid-session and the manifest file
  was lost before the after-check could run against it. The after-check was
  therefore done three other ways, all passing: (1) `git status --porcelain`
  and `git diff HEAD` in the recovered clone are both empty — every tracked
  file is unchanged; (2) a recursive `diff -r` of the snapshot (copied at
  build start) against the clone now, excluding `.git` / `__pycache__` /
  `*.pyc` / the added `SNAPSHOT_README.md`, reports no differences — nothing
  in the clone changed during the build; (3) the `__pycache__` `.pyc` files
  in the clone carry mtimes ~4.8 days before this session (epoch 1794545821
  vs session time 1794959325), i.e. they predate this build and were not
  regenerated by it. No writes were ever made into the clone — only reads
  and a `cp` out.

## Surprises found in the code

1. **README understates the size ~3×:** it claims "4,075 lines of real
   code"; the Python alone is 11,308 lines (census: ~11,300). The
   "production-ready" claim is likewise unverified — no run history in the
   repo proves a successful live Facebook scrape.
2. **The repo never tested the piece worth keeping:** `backend_test.py`
   (593 lines, live-endpoint suite) has no vehicle-deals test at all — only
   a `"category": "vehicles"` filter check. The evaluator's tests here are
   new.
3. **Totals use the unrounded payment:** the module rounds the monthly
   payment for display but computes total interest / total cost from the
   unrounded value. Caught during fixture verification (24¢ gap on the
   PURSUE fixture at first pass: $620.32 hand-rounded vs $620.08 actual).
   Fixtures follow the actual semantics and now match to the cent.
4. **Retired-state paths baked in:** `approvals.py` and `task_audit.py`
   hardcode `/Users/DdyFngr/Desktop/Projects/pineapple-ops-runtime/state`
   — the retired Molt runtime. Those modules could not run as-is on any
   current machine.
5. **Its own ToS warning:** `scraper.py` carries "Automated scraping may
   violate Facebook's ToS." — the code itself flags the path the brief
   declines to rebuild.
6. **No cookies existed to sanitize:** no `data/` directory and no
   `fb_cookies.json` anywhere in the recovered repo.
7. **Snapshot excludes build artifacts:** `__pycache__` / `*.pyc` files
   present in the recovered clone (from earlier verification compiles)
   were excluded from the snapshot; the snapshot is source only.

## No blockers

Nothing is BLOCKED. The archive is complete and verified against every
acceptance item in the brief: inventory complete with verdicts; extracted
evaluator standalone with all tests passing against hand-computed
fixtures and no scraper/Facebook imports; archive record written with the
supersession mapping, cookie-auth evidence, and the GitHub-token flag
carried forward; read-only snapshot present; originals untouched; nothing
deployed, no account touched, no cookies handled.
