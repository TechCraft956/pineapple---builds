from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from .brief import generate_brief
from .ingestion import filter_actionable, preprocess
from .parser import parse_chunks
from .planner import infer_tasks, save_inferred_tasks
from .schemas import (
    BriefItem,
    ConfirmRequest,
    CorrectionRecord,
    CorrectionRequest,
    Course,
    DailyBrief,
    IngestionLog,
    IngestRequest,
    ItemStatus,
    ParseResult,
    SchoolItem,
)
from .storage import (
    get_corrections,
    get_course,
    get_courses,
    get_item,
    get_items,
    save_correction,
    save_course,
    save_ingestion_log,
    save_items,
    update_item,
)

router = APIRouter(prefix="/school", tags=["school_assistant"])


# ── Courses ────────────────────────────────────────────────────────────────────

@router.get("/courses", response_model=list[Course])
def list_courses():
    return get_courses()


@router.post("/courses", response_model=Course)
def create_course(course: Course):
    return save_course(course)


@router.get("/courses/{course_id}", response_model=Course)
def get_course_detail(course_id: str):
    course = get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


# ── Ingestion ──────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=ParseResult)
def ingest_text(req: IngestRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Input text is empty")

    cleaned, chunks = preprocess(req.text)
    actionable = filter_actionable(chunks)
    candidates = parse_chunks(actionable)

    result = ParseResult(
        raw_input=cleaned,
        course_id=req.course_id,
        candidates=candidates,
        chunk_count=len(chunks),
        item_count=len(candidates),
    )

    log = IngestionLog(
        source_type=req.source_type,
        raw_length=len(req.text),
        chunk_count=len(chunks),
        items_extracted=len(candidates),
        parse_id=result.parse_id,
    )
    save_ingestion_log(log)

    return result


@router.post("/ingest/save", response_model=list[SchoolItem])
def save_parse_result(result: ParseResult):
    """Persist ParseResult candidates as SchoolItems after user review."""
    items = [
        SchoolItem(
            course_id=result.course_id,
            title=c.title,
            type=c.type,
            due_date=c.due_date,
            due_time=c.due_time,
            weight=c.weight,
            source_text=c.source_text,
            confidence_score=c.confidence_score,
        )
        for c in result.candidates
    ]
    save_items(items)

    tasks = infer_tasks()
    save_inferred_tasks(tasks)

    return items


# ── Items ──────────────────────────────────────────────────────────────────────

@router.get("/items", response_model=list[SchoolItem])
def list_items(course_id: Optional[str] = None):
    return get_items(course_id=course_id)


@router.get("/items/{item_id}", response_model=SchoolItem)
def get_item_detail(item_id: str):
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


# ── Correction ─────────────────────────────────────────────────────────────────

@router.post("/correct", response_model=SchoolItem)
def correct_item(req: CorrectionRequest):
    item = get_item(req.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    original_snapshot = item.model_dump(mode="json")
    updates = req.model_dump(exclude_none=True, exclude={"item_id"})

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = update_item(req.item_id, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="Update failed")

    correction = CorrectionRecord(
        item_id=req.item_id,
        original=original_snapshot,
        corrected=updates,
    )
    save_correction(correction)

    return updated


@router.post("/confirm", response_model=SchoolItem)
def confirm_item(req: ConfirmRequest):
    item = get_item(req.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    updated = update_item(req.item_id, {"confirmed": req.confirmed})
    return updated


@router.post("/items/{item_id}/status", response_model=SchoolItem)
def update_status(item_id: str, status: ItemStatus):
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return update_item(item_id, {"status": status.value})


# ── Brief ──────────────────────────────────────────────────────────────────────

@router.get("/brief", response_model=DailyBrief)
def daily_brief(course_id: Optional[str] = None):
    return generate_brief(course_id=course_id)


# ── Corrections history ────────────────────────────────────────────────────────

@router.get("/corrections", response_model=list[CorrectionRecord])
def list_corrections(item_id: Optional[str] = None):
    return get_corrections(item_id=item_id)
