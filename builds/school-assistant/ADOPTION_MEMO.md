# ADOPTION MEMO — School Scraper Assistant (BUILD-20261117-008)

**To: Airam — decision required. No Pineapple wiring has been built.**

## What it is
A small FastAPI backend ("School Scraper Assistant", v0.1.0) that
ingests pasted syllabus/announcement text, infers dated school items
(exams, quizzes, assignments, labs, discussions), and produces a daily
brief ranked by due-date proximity. Recovered from the private repo
`TechCraft956/new-folder` (single commit, 2026-04-17). It references
nothing Pineapple and maps to no previously known Pineapple system.

## What it verifiably does (built + tested 2026-11-17, this workspace)
- Boots in a clean venv; `/health` returns `{"status": "ok"}`; all 11
  `/school` routes respond (courses, ingest, ingest/save, items,
  correct, confirm, status, brief, corrections).
- Ingesting the SAMPLE syllabus (2 fabricated courses, 5 items) yields
  5 candidates with confidence scores (0.6–1.0) and rule signals; the
  daily brief ranks the nearest-due exam first
  (Midterm Exam, 2026-11-19, in `due_within_48h`).
- Parser handles multiple date formats (November 19, 2026; 11/24/2026;
  Nov 21, 2026; month-day without year); an item with no date stays
  `due_date: null` — dates are never invented. **27/27 tests pass,
  offline, no network.**
- **Weighting reconciled (Task 2b):** `planner.py` exam 1.4× / quiz 1.2×
  (+ grade-weight multiplier) is now the single source of truth
  (`TYPE_PRIORITY_BOOST`); `brief.py`'s old flat 1.3× for both is gone.
  Tests assert exam > quiz > assignment at equal due dates in both the
  planner and the brief.
- **7-day window, stated plainly:** the daily brief shows only items due
  within 7 days (plus no-date items). **Items due more than 7 days out
  are omitted from the brief** — they still exist as stored items, but
  the brief is NOT a complete upcoming schedule. Read `/school/items`
  for the full list.

## What it does NOT do
- **PDF / LMS ingestion are stubs, not features.** `source_type`
  "pdf"/"lms" is only a label on the ingestion log; there is no PDF
  extractor and no LMS connector in the code. Only pasted text works.
- **No authentication, no per-user scoping** (see `AUTH_GAP.md`). Safe
  local-only; unsafe to expose or share as-is.
- **No Pineapple links at all** — no feed, no shared-feed wiring, no
  reference to any other Pineapple system. Feed wiring was explicitly
  out of this build.
- Parser titles are crude: a no-date line containing the word "due"
  gets its title cut at that word (e.g. "Discussion Post Introduce
  Yourself — no"). Cosmetic, but real.
- Storage is whole-file JSON rewrites per operation; fine at this
  scale, not a design to grow far.

## Decision for Airam (pick one)
1. **Adopt into Pineapple** — the daily school brief becomes a Pineapple
   feed source. Follow-up brief required first: auth + per-user scoping
   (see `AUTH_GAP.md` prerequisites), then feed wiring. Nothing is
   wired until you say so.
2. **Keep as a standalone student tool** — it stays a local-only app in
   this workspace, used as-is for pasted syllabi. No further Pineapple
   work.

**Recommendation:** option 2 for now — keep it standalone. It is a
working, genuinely useful local tool, but it only handles pasted text
and has no auth; the adoption payoff (school deadlines in the Pineapple
feed) is real only if you want those deadlines surfaced daily, and the
auth work must come first either way. If you do want it in the feed,
say "adopt" and the auth-then-wiring follow-up gets briefed.
