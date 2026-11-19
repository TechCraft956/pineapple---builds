from __future__ import annotations

import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any, Optional, TypeVar, Type

from pydantic import BaseModel

from .schemas import (
    Course, SchoolItem, InferredTask,
    CorrectionRecord, IngestionLog, ParseResult,
)

T = TypeVar("T", bound=BaseModel)

MEMORY_ROOT = Path(os.environ.get("SSA_MEMORY_ROOT", "memory/school"))

_FILES = {
    "courses":       MEMORY_ROOT / "courses.json",
    "items":         MEMORY_ROOT / "items.json",
    "tasks":         MEMORY_ROOT / "tasks.json",
    "corrections":   MEMORY_ROOT / "corrections.json",
    "ingestion_logs": MEMORY_ROOT / "ingestion_logs.json",
}


def _ensure_storage() -> None:
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    for path in _FILES.values():
        if not path.exists():
            path.write_text("[]", encoding="utf-8")


def _default_serializer(obj: Any) -> str:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


def _load(key: str) -> list[dict]:
    _ensure_storage()
    raw = _FILES[key].read_text(encoding="utf-8")
    return json.loads(raw) if raw.strip() else []


def _save(key: str, records: list[dict]) -> None:
    _ensure_storage()
    _FILES[key].write_text(
        json.dumps(records, indent=2, default=_default_serializer),
        encoding="utf-8",
    )


def _append(key: str, record: dict) -> None:
    records = _load(key)
    records.append(record)
    _save(key, records)


# ── Courses ────────────────────────────────────────────────────────────────────

def save_course(course: Course) -> Course:
    records = _load("courses")
    records = [r for r in records if r["course_id"] != course.course_id]
    records.append(course.model_dump(mode="json"))
    _save("courses", records)
    return course


def get_courses() -> list[Course]:
    return [Course(**r) for r in _load("courses")]


def get_course(course_id: str) -> Optional[Course]:
    for r in _load("courses"):
        if r["course_id"] == course_id:
            return Course(**r)
    return None


# ── SchoolItems ────────────────────────────────────────────────────────────────

def save_item(item: SchoolItem) -> SchoolItem:
    records = _load("items")
    records = [r for r in records if r["item_id"] != item.item_id]
    records.append(item.model_dump(mode="json"))
    _save("items", records)
    return item


def save_items(items: list[SchoolItem]) -> None:
    records = _load("items")
    existing_ids = {i.item_id for i in items}
    records = [r for r in records if r["item_id"] not in existing_ids]
    records.extend(i.model_dump(mode="json") for i in items)
    _save("items", records)


def get_items(course_id: Optional[str] = None) -> list[SchoolItem]:
    records = _load("items")
    if course_id:
        records = [r for r in records if r.get("course_id") == course_id]
    return [SchoolItem(**r) for r in records]


def get_item(item_id: str) -> Optional[SchoolItem]:
    for r in _load("items"):
        if r["item_id"] == item_id:
            return SchoolItem(**r)
    return None


def update_item(item_id: str, updates: dict) -> Optional[SchoolItem]:
    records = _load("items")
    for i, r in enumerate(records):
        if r["item_id"] == item_id:
            records[i] = {**r, **updates}
            _save("items", records)
            return SchoolItem(**records[i])
    return None


# ── InferredTasks ──────────────────────────────────────────────────────────────

def save_task(task: InferredTask) -> InferredTask:
    _append("tasks", task.model_dump(mode="json"))
    return task


def get_tasks(item_id: Optional[str] = None) -> list[InferredTask]:
    records = _load("tasks")
    if item_id:
        records = [r for r in records if r.get("linked_item_id") == item_id]
    return [InferredTask(**r) for r in records]


# ── Corrections ────────────────────────────────────────────────────────────────

def save_correction(record: CorrectionRecord) -> CorrectionRecord:
    _append("corrections", record.model_dump(mode="json"))
    return record


def get_corrections(item_id: Optional[str] = None) -> list[CorrectionRecord]:
    records = _load("corrections")
    if item_id:
        records = [r for r in records if r.get("item_id") == item_id]
    return [CorrectionRecord(**r) for r in records]


# ── Ingestion logs ─────────────────────────────────────────────────────────────

def save_ingestion_log(log: IngestionLog) -> IngestionLog:
    _append("ingestion_logs", log.model_dump(mode="json"))
    return log


def get_ingestion_logs() -> list[IngestionLog]:
    return [IngestionLog(**r) for r in _load("ingestion_logs")]
