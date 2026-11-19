# BUILD REPORT — BUILD-20261117-008: School Scraper Assistant
Built 2026-11-17 ~17:35–18:00 CT. Workspace:
`~/workspace/pineapple/builds/school-assistant/`

## Source provenance
- Source: private repo `TechCraft956/new-folder` (single commit
  "initial commit", 2026-04-17), read via the connected GitHub MCP
  (`get_file_contents`), one SHA per file — the GitHub repo was NOT
  modified and no push was made.
- **Clone caveat:** the local `gh` CLI is not logged in
  (`gh auth status`: "You are not logged into any GitHub hosts"), so
  no `git clone` was possible. The build input is instead a complete
  per-file fetch through the connected GitHub connector — all 12 files,
  byte-complete. There is no `.git` history in the workspace copy.
  Per-file blob SHAs (from the connector):
  - `main.py` cce43ef8ce2da17625150699a87fba36c7a05102
  - `requirements.txt` d7c91a35768c56a32592c1db1930ce73c2c99440
  - `.gitignore` c0e0e8aec9d0db54cf74589813f190b2b747314d
  - `modules/school_assistant/__init__.py` 1b2eccc4bf7a729a277b985ecd61216e91157bfa
  - `routes.py` d03966e55b754cfa54b143808aa19202231c1fc0
  - `schemas.py` 5663320d7aa0b8c754b7fe682d0ff7d4824f2c3f
  - `storage.py` 4870a3ba6246cc29fb88354a3ef99cc701641013
  - `ingestion.py` 97f4ed7aa409ca764eb7e627010722c40dfddd7c
  - `parser.py` 8d4fa0f411b6397524be1f49029493f136ef1e59
  - `planner.py` 04f7983a10db4ad4471ab5e2f9f205b571a83301
  - `brief.py` c92814218052bdb25df4ea9e4b918f1cfdf3b654
  - `utils.py` b6a9256d3137b5373050bf47ea31e6711ae4e031
- No README exists in the repo (verified: fetch returns "does not exist").

## Files changed (in `src/` only — the GitHub repo is untouched)
Only 3 of the 12 source files were modified; the other 9 are
byte-identical to the fetched originals.
1. **`src/main.py` (Task 3 — CORS):** `allow_origins=["*"]` /
   `allow_methods=["*"]` / `allow_headers=["*"]` replaced with a
   localhost-only default origin list (`http://localhost`,
   `http://localhost:8000`, `http://localhost:3000`, and the
   `127.0.0.1` equivalents), methods `GET`/`POST` only, headers
   `Content-Type` only. Configurable via `SSA_CORS_ORIGINS`
   (comma-separated). Documented in-file.
2. **`src/modules/school_assistant/planner.py` (Task 2b):** the
   per-type multipliers were hoisted into a module-level
   `TYPE_PRIORITY_BOOST` dict, documented as the single source of
   truth. Values unchanged: exam 1.4, quiz 1.2, lab 1.1, project 1.15,
   assignment 1.0, discussion 0.9, other 0.8; grade-weight multiplier
   `1 + weight/100` unchanged.
3. **`src/modules/school_assistant/brief.py` (Task 2b):** the old flat
   `_exam_weight` (1.3× for exam AND quiz) now defers to
   `planner.TYPE_PRIORITY_BOOST` — an exam outranks a quiz at equal
   due dates. The planner's grade-weight multiplier is intentionally
   NOT applied in the brief (brief ranks by proximity × type only).
   `generate_brief` now documents the 7-day window in its docstring.

## New files (workspace, not in the repo)
- `fixtures/sample_courses.json` — 2 fabricated courses (SAMPLE
  Introduction to Biology BIOL 1406; SAMPLE College Algebra MATH 1314).
- `fixtures/sample_syllabus.txt` — 1 fabricated syllabus paste
  (5 items; no real school data anywhere in this build).
- `tests/test_school_assistant.py` — 27 tests, offline, no network.
- `AUTH_GAP.md` — the auth-gap note with exact prerequisites.
- `ADOPTION_MEMO.md` — the one-page adoption memo for Airam.
- `BUILD_REPORT.md` — this file.
- `data/` — runtime JSON store from the live boot (sample data only).
- `.venv/` — clean venv (fastapi 0.163.2, uvicorn, pydantic, pytest,
  httpx) built from `src/requirements.txt`.

## Test evidence — 27/27 passed
` .venv/bin/python -m pytest tests/ -v` → **27 passed in 1.53s**
(64 warnings, all pre-existing `datetime.utcnow()` deprecations in the
original code and a Starlette/httpx deprecation — none caused by this
build). Coverage: 5 date-format parser tests; exam/quiz/assignment
extraction + weight + signals + confidence; no-date item stays null;
policy/meta chunk filtering; planner ordering + exact multipliers +
grade-weight multiplier + overdue (1.0) / no-date (0.3) + 7-day exam
start lead; brief fidelity (no invented/dropped items), 7-day window
omission, reconciled exam-before-quiz ordering, done/ignored exclusion,
overdue bucket + top actions; PDF/LMS stub tests (source-level + live);
API health/courses/ingest→save→brief end-to-end; CORS allow/deny.

## Live boot evidence (Task 1, uvicorn on 127.0.0.1:8123)
- `GET /health` → `{"status": "ok"}` (HTTP 200).
- 11 `/school` routes live (from OpenAPI): `/school/brief`,
  `/confirm`, `/correct`, `/corrections`, `/courses`,
  `/courses/{course_id}`, `/ingest`, `/ingest/save`, `/items`,
  `/items/{item_id}`, `/items/{item_id}/status`.
- `POST /school/ingest` (SAMPLE syllabus): **7 chunks → 5 candidates**:
  - Midterm Exam in Introduction to Biology — exam, due 2026-11-19,
    weight 30.0, confidence 1.0, all 5 signals
  - Quiz 3 on Cell Structure — quiz, due 2026-11-21, conf 0.9
  - Homework 5 Photosynthesis Lab Report — lab, due 2026-11-24, conf 0.9
  - Research Paper on Ecosystems — assignment, due 2026-12-01,
    weight 25.0, conf 1.0
  - Discussion Post Introduce Yourself — no — discussion, due null,
    conf 0.6
- `POST /school/ingest/save` → 5 items saved.
- `GET /school/brief` → `due_within_48h`: Midterm Exam (2026-11-19)
  first; `upcoming_7d`: Quiz 3 (2026-11-21), Homework 5 (2026-11-24);
  `no_due_date`: Discussion Post; Research Paper (due 2026-12-01,
  >7 days) omitted from every bucket, still stored. Top actions:
  "Complete Midterm Exam in Introduction to Biology — due in 2 days",
  "Begin Quiz 3 on Cell Structure — due in 4 days".
- CORS live: `Origin: http://localhost:8000` → 200 with
  `access-control-allow-origin: http://localhost:8000`;
  `Origin: https://evil.example.com` → 200 with NO ACAO header.

## PDF / LMS: STUBS, not implementations (verified)
- No PDF library in `requirements.txt` or `ingestion.py` (checked for
  fitz/pypdf/pdfplumber/PyPDF2/pdfminer — none present); no LMS code
  anywhere in the repo. `source_type` "pdf"/"lms" is only a label on
  the `IngestionLog`. Live test: ingesting with `source_type: "pdf"`
  and non-syllabus bytes yields 0 candidates while the log records
  `"pdf"`. Only pasted text is actually parsed.

## Weighting reconciliation decision (Task 2b)
- **Decision: `planner.py` governs.** `TYPE_PRIORITY_BOOST`
  (exam 1.4×, quiz 1.2×, lab 1.1×, project 1.15×, assignment 1.0×,
  discussion 0.9×, other 0.8×) is the single source of truth, imported
  by `brief.py`. The old flat 1.3× for exam+quiz in `brief.py` is
  deleted. Rationale: the planner's per-type split is strictly more
  informative than the brief's flat figure, and the planner is the
  component that already combined type weight with grade weight — one
  canonical table beats two drifting ones.
- The grade-weight multiplier (`1 + weight/100`) stays planner-only;
  the brief ranks by proximity × type, not grade weight. This asymmetry
  is documented in both files' comments.
- **7-day bucket window:** items due >7 days out are omitted from the
  brief (overdue / within-48h / upcoming-7d / no-date buckets) while
  remaining stored and listable via `/school/items`. No-date items
  appear in `no_due_date`. Stated in `brief.py`'s docstring, asserted
  by test, and stated plainly in `ADOPTION_MEMO.md` — the brief must
  not be mistaken for a complete upcoming schedule.

## Surprises / findings
1. **Re-saving the same parse duplicates items AND tasks (verified
   live).** `POST /school/ingest/save` mints fresh UUIDs for every
   item on each call and `save_inferred_tasks` appends without
   dedupe: saving the identical SAMPLE parse twice grew
   `tasks.json` 5 → 15 (and items 5 → 10). There is no idempotency
   key. Harmless in single-save use; a real footgun for any UI with a
   double-submit or a retry. Not fixed here — out of the brief's
   scope, flagged for a follow-up.
2. **Title extraction truncates on the word "due" anywhere in a line.**
   The no-date discussion line ("…no due date listed…") became the
   title "Discussion Post Introduce Yourself — no". Cosmetic, but the
   parser is cruder than its docstrings suggest.
3. **Date parsing uses the current year for year-less dates**
   (`utils.parse_date`), so "June 12" means June 12 of the run year —
   fine for a current-term syllabus, wrong for an old one.
4. `datetime.utcnow()` deprecation warnings throughout the original
   code (Python 3.12) — cosmetic, not fixed here.
5. No README, no tests, and no `.git` history came with the repo
   (single squashed commit); the build supplies the missing test
   suite and docs in the workspace only.

## How to re-run
```
cd ~/workspace/pineapple/builds/school-assistant
.venv/bin/python -m pytest tests/ -v
SSA_MEMORY_ROOT=$PWD/data .venv/bin/uvicorn main:app --app-dir src --port 8123 --host 127.0.0.1
curl http://127.0.0.1:8123/health   # {"status":"ok"}
```

## What was NOT done (per the brief)
- No feed wiring, no auth system built (see `AUTH_GAP.md`).
- No deployment, no real school data, no account changes, no GitHub
  repo changes. No writes to the AI Bridge sheet or PIPELINE_STATE.md
  (parent agent's job).
