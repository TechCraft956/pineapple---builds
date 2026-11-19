"""Tests for School Scraper Assistant (BUILD-20261117-008).

No network. All dates are computed relative to today so the suite does not
go stale. Storage is pointed at a throwaway temp dir via SSA_MEMORY_ROOT,
set BEFORE the app modules are imported (storage binds MEMORY_ROOT at
import time).
"""
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="ssa_test_")
os.environ["SSA_MEMORY_ROOT"] = _TMP

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from modules.school_assistant import brief as brief_mod  # noqa: E402
from modules.school_assistant import planner as planner_mod  # noqa: E402
from modules.school_assistant.ingestion import Chunk, filter_actionable, preprocess  # noqa: E402
from modules.school_assistant.parser import parse_chunk, parse_chunks  # noqa: E402
from modules.school_assistant.planner import (  # noqa: E402
    TYPE_PRIORITY_BOOST,
    _priority_score,
    _suggested_start,
    infer_tasks,
)
from modules.school_assistant.schemas import (  # noqa: E402
    ItemStatus,
    ItemType,
    SchoolItem,
)
from modules.school_assistant.storage import get_items, save_items  # noqa: E402
from modules.school_assistant.utils import parse_date  # noqa: E402

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _d(days: int) -> date:
    return date.today() + timedelta(days=days)


def _fmt(d: date) -> str:
    return d.strftime("%B %d, %Y")


def _item(title, itype, due=None, weight=None, status=ItemStatus.not_started):
    return SchoolItem(
        course_id="sample-biol-1406",
        title=title,
        type=itype,
        due_date=due,
        weight=weight,
        source_text=f"SAMPLE {title}",
        confidence_score=0.9,
        status=status,
    )


def _clear_items():
    for key in ("items", "tasks", "courses", "corrections", "ingestion_logs"):
        p = Path(_TMP) / f"{key}.json"
        p.write_text("[]", encoding="utf-8")


# ── Parser: date formats ──────────────────────────────────────────────────────

def test_parse_date_month_name_full_year():
    assert parse_date("Midterm due November 19, 2026") == date(2026, 11, 19)


def test_parse_date_numeric_slash():
    assert parse_date("Report due 11/24/2026") == date(2026, 11, 24)


def test_parse_date_short_month():
    assert parse_date("Quiz due Nov 21, 2026") == date(2026, 11, 21)


def test_parse_date_month_day_no_year_uses_current_year():
    assert parse_date("Exam June 12") == date(date.today().year, 6, 12)


def test_parse_date_invalid_month_day_returns_none():
    assert parse_date("nothing dated here at all") is None


# ── Parser: types, weight, no-date, signals ──────────────────────────────────

def test_parser_exam_with_weight_and_signals():
    c = parse_chunk(Chunk(text=f"Midterm Exam in Biology due {_fmt(_d(2))} (30%)",
                          chunk_type="exam"))
    assert c is not None
    assert c.type == ItemType.exam
    assert c.due_date == _d(2)
    assert c.weight == 30.0
    assert "date_found" in c.signals and "due_keyword" in c.signals
    assert "type_keyword" in c.signals and "weight_found" in c.signals
    assert 0 < c.confidence_score <= 1.0


def test_parser_quiz_and_assignment():
    quiz = parse_chunk(Chunk(text=f"Quiz 3 on Cells due {_fmt(_d(4))}",
                             chunk_type="quiz"))
    assert quiz.type == ItemType.quiz and quiz.due_date == _d(4)
    hw = parse_chunk(Chunk(text=f"Homework 5 due {_fmt(_d(7))} (10%)",
                           chunk_type="assignment"))
    assert hw.type == ItemType.assignment and hw.weight == 10.0


def test_parser_item_with_no_date_stays_null_never_invented():
    c = parse_chunk(Chunk(text="Discussion Post Introduce Yourself post anytime",
                          chunk_type="discussion"))
    assert c is not None
    assert c.due_date is None
    assert "date_found" not in c.signals


def test_parser_title_has_no_date_or_weight_fragments():
    c = parse_chunk(Chunk(text=f"Midterm Exam in Biology due {_fmt(_d(2))} (30%)",
                          chunk_type="exam"))
    assert "2026" not in c.title and "30%" not in c.title
    assert c.title.startswith("Midterm Exam")


def test_preprocess_filters_policy_and_meta_chunks():
    _, chunks = preprocess(
        "Attendance policy: attend all lectures.\n\n"
        f"Midterm Exam due {_fmt(_d(2))}.\n\n"
        "Instructor: Dr. X, office hours Tuesdays.\n")
    actionable = filter_actionable(chunks)
    assert len(actionable) == 1 and actionable[0].chunk_type == "exam"


# ── Planner: ordering, weighting, overdue, no-date ───────────────────────────

def test_planner_exam_outranks_quiz_outranks_assignment_same_date():
    # 10 days out so the 1.0 cap does not flatten the scores.
    due = _d(10)
    e = _priority_score(_item("Exam", ItemType.exam, due))
    q = _priority_score(_item("Quiz", ItemType.quiz, due))
    a = _priority_score(_item("HW", ItemType.assignment, due))
    assert e > q > a


def test_planner_reconciled_multipliers_are_exact():
    assert TYPE_PRIORITY_BOOST[ItemType.exam] == 1.4
    assert TYPE_PRIORITY_BOOST[ItemType.quiz] == 1.2
    # The old flat 1.3x for both is gone: exam and quiz now differ.
    assert TYPE_PRIORITY_BOOST[ItemType.exam] != TYPE_PRIORITY_BOOST[ItemType.quiz]


def test_planner_grade_weight_multiplier_raises_score():
    due = _d(10)
    plain = _priority_score(_item("HW", ItemType.assignment, due))
    heavy = _priority_score(_item("HW", ItemType.assignment, due, weight=30.0))
    assert heavy > plain


def test_planner_overdue_is_max_and_no_date_is_low():
    assert _priority_score(_item("Late", ItemType.assignment, _d(-2))) == 1.0
    assert _priority_score(_item("Someday", ItemType.assignment, None)) == 0.3


def test_planner_exam_suggested_start_is_7_day_lead():
    assert _suggested_start(_item("Exam", ItemType.exam, _d(10))) == _d(3)
    assert _suggested_start(_item("Someday", ItemType.assignment, None)) is None


def test_planner_infer_tasks_sorted_by_priority():
    _clear_items()
    save_items([_item("HW", ItemType.assignment, _d(10)),
                _item("Exam", ItemType.exam, _d(10))])
    tasks = infer_tasks()
    assert tasks[0].linked_item_id == get_items()[1].item_id  # exam first
    assert tasks[0].priority_score >= tasks[1].priority_score


# ── Brief: fidelity, 7-day window, reconciled weighting ──────────────────────

def test_brief_contains_exactly_the_stored_active_items_in_window():
    _clear_items()
    save_items([_item("Exam", ItemType.exam, _d(2)),
                _item("Quiz", ItemType.quiz, _d(4)),
                _item("HW", ItemType.assignment, _d(7))])
    b = brief_mod.generate_brief()
    titles = [i.title for i in b.due_within_48h + b.upcoming_7d
              + b.overdue + b.no_due_date]
    assert sorted(titles) == ["Exam", "HW", "Quiz"]  # nothing invented/dropped


def test_brief_7day_window_omits_far_items_but_keeps_no_date_items():
    _clear_items()
    save_items([_item("Far Paper", ItemType.assignment, _d(14)),
                _item("Someday Post", ItemType.discussion, None)])
    b = brief_mod.generate_brief()
    all_titles = [i.title for i in b.due_within_48h + b.upcoming_7d
                  + b.overdue + b.no_due_date]
    assert "Far Paper" not in all_titles  # due >7 days: omitted, not deleted
    assert "Someday Post" in [i.title for i in b.no_due_date]
    # ...and the stored item itself still exists:
    assert any(i.title == "Far Paper" for i in get_items())


def test_brief_reconciled_weighting_exam_before_quiz_same_date():
    _clear_items()
    # Insert quiz FIRST so insertion order cannot explain the result.
    save_items([_item("Quiz", ItemType.quiz, _d(3)),
                _item("Exam", ItemType.exam, _d(3))])
    b = brief_mod.generate_brief()
    assert [i.title for i in b.upcoming_7d] == ["Exam", "Quiz"]


def test_brief_excludes_done_and_ignored_items():
    _clear_items()
    save_items([_item("Done HW", ItemType.assignment, _d(1),
                      status=ItemStatus.done),
                _item("Ignored", ItemType.assignment, _d(1),
                      status=ItemStatus.ignored),
                _item("Live", ItemType.assignment, _d(1))])
    b = brief_mod.generate_brief()
    titles = [i.title for i in b.due_within_48h]
    assert titles == ["Live"]


def test_brief_overdue_bucket_and_top_actions():
    _clear_items()
    save_items([_item("Overdue HW", ItemType.assignment, _d(-1))])
    b = brief_mod.generate_brief()
    assert [i.title for i in b.overdue] == ["Overdue HW"]
    assert any("Overdue HW" in a for a in b.top_actions)


# ── PDF / LMS are stubs, not implementations ──────────────────────────────────

def test_pdf_lms_are_stubs_no_pdf_code_or_dependency():
    src = Path(__file__).resolve().parents[1] / "src"
    reqs = (src / "requirements.txt").read_text()
    ingestion = (src / "modules/school_assistant/ingestion.py").read_text()
    for lib in ("fitz", "pypdf", "pdfplumber", "PyPDF2", "pdfminer"):
        assert lib not in reqs and lib not in ingestion
    assert "lms" not in ingestion.lower().replace("source_type", "")


def test_ingest_pdf_source_type_records_label_only_parses_paste_text():
    _clear_items()
    r = client.post("/school/ingest", json={
        "text": "garbage \x00\x01 binary not a syllabus",
        "source_type": "pdf"})
    assert r.status_code == 200
    assert r.json()["item_count"] == 0  # no PDF extractor runs
    logs = Path(_TMP, "ingestion_logs.json").read_text()
    assert '"pdf"' in logs  # the label is recorded, nothing is extracted


# ── API: health, courses, ingest → save → brief ───────────────────────────────

def test_health_returns_ok():
    assert client.get("/health").json() == {"status": "ok"}


def test_courses_crud_roundtrip():
    _clear_items()
    courses = json.loads((FIXTURES / "sample_courses.json").read_text())
    for c in courses:
        r = client.post("/school/courses", json=c)
        assert r.status_code == 200
    listed = client.get("/school/courses").json()
    assert {c["course_id"] for c in listed} == {
        "sample-biol-1406", "sample-math-1314"}


def test_sample_syllabus_ingest_save_and_brief():
    _clear_items()
    for c in json.loads((FIXTURES / "sample_courses.json").read_text()):
        client.post("/school/courses", json=c)
    text = (FIXTURES / "sample_syllabus.txt").read_text()
    r = client.post("/school/ingest", json={
        "text": text, "course_id": "sample-biol-1406",
        "source_type": "paste"})
    assert r.status_code == 200
    parsed = r.json()
    assert parsed["item_count"] >= 4
    cands = parsed["candidates"]
    assert all(0 < c["confidence_score"] <= 1.0 for c in cands)
    assert all(c["signals"] for c in cands)
    titles = [c["title"] for c in cands]
    assert any("Midterm Exam" in t for t in titles)
    assert any("Quiz 3" in t for t in titles)
    # No-date discussion item stays null-dated, never invented:
    nodate = [c for c in cands if "Discussion" in c["title"]]
    assert nodate and nodate[0]["due_date"] is None

    saved = client.post("/school/ingest/save", json=parsed).json()
    assert len(saved) == parsed["item_count"]

    b = client.get("/school/brief").json()
    first = b["due_within_48h"][0]
    assert "Midterm Exam" in first["title"]  # nearest-due exam ranks first
    assert first["due_date"] == "2026-11-19"
    # Item due Dec 1 (>7 days) is omitted from the brief, not deleted:
    brief_titles = [i["title"] for k in
                    ("overdue", "due_within_48h", "upcoming_7d", "no_due_date")
                    for i in b[k]]
    assert not any("Research Paper" in t for t in brief_titles)
    assert any("Discussion" in t for t in
               [i["title"] for i in b["no_due_date"]])


def test_cors_localhost_allowed_external_origin_not():
    ok = client.get("/health", headers={"Origin": "http://localhost:8000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8000"
    bad = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in bad.headers
