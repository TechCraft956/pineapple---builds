from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ItemType(str, Enum):
    assignment = "assignment"
    exam = "exam"
    quiz = "quiz"
    discussion = "discussion"
    lab = "lab"
    project = "project"
    other = "other"


class ItemStatus(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    done = "done"
    overdue = "overdue"
    ignored = "ignored"


# ── Core entities ──────────────────────────────────────────────────────────────

class Course(BaseModel):
    course_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    code: Optional[str] = None
    term: Optional[str] = None
    instructor: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SchoolItem(BaseModel):
    item_id: str = Field(default_factory=lambda: str(uuid4()))
    course_id: Optional[str] = None
    title: str
    type: ItemType = ItemType.assignment
    due_date: Optional[date] = None
    due_time: Optional[str] = None        # raw string, e.g. "11:59 PM"
    weight: Optional[float] = None       # % of grade
    status: ItemStatus = ItemStatus.not_started
    source_text: str                      # always preserved
    confidence_score: float = Field(ge=0.0, le=1.0)
    confirmed: bool = False              # user has manually confirmed
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


class InferredTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    linked_item_id: str
    action: str
    suggested_start_date: Optional[date] = None
    priority_score: float = Field(ge=0.0, le=1.0, default=0.5)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Ingestion / parse lifecycle ────────────────────────────────────────────────

class ParsedCandidate(BaseModel):
    """Raw extraction output before user confirmation."""
    title: str
    type: ItemType
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    weight: Optional[float] = None
    source_text: str
    confidence_score: float
    signals: list[str] = Field(default_factory=list)  # debug: which rules fired


class ParseResult(BaseModel):
    parse_id: str = Field(default_factory=lambda: str(uuid4()))
    raw_input: str
    course_id: Optional[str] = None
    candidates: list[ParsedCandidate]
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
    chunk_count: int = 0
    item_count: int = 0


class CorrectionRecord(BaseModel):
    correction_id: str = Field(default_factory=lambda: str(uuid4()))
    item_id: str
    original: dict                       # snapshot of SchoolItem before edit
    corrected: dict                      # fields that were changed
    corrected_at: datetime = Field(default_factory=datetime.utcnow)


class IngestionLog(BaseModel):
    log_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: str = "paste"          # paste | pdf | lms
    raw_length: int
    chunk_count: int
    items_extracted: int
    items_confirmed: int = 0
    parse_id: str
    logged_at: datetime = Field(default_factory=datetime.utcnow)


# ── API shapes ─────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    text: str
    course_id: Optional[str] = None     # attach to known course if provided
    source_type: str = "paste"


class CorrectionRequest(BaseModel):
    item_id: str
    title: Optional[str] = None
    type: Optional[ItemType] = None
    due_date: Optional[date] = None
    due_time: Optional[str] = None
    weight: Optional[float] = None
    confirmed: Optional[bool] = None
    status: Optional[ItemStatus] = None


class ConfirmRequest(BaseModel):
    item_id: str
    confirmed: bool = True


class BriefItem(BaseModel):
    item_id: str
    title: str
    type: ItemType
    due_date: Optional[date]
    days_until_due: Optional[int]
    status: ItemStatus
    confidence_score: float
    course_name: Optional[str] = None


class DailyBrief(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    overdue: list[BriefItem]
    due_within_48h: list[BriefItem]
    upcoming_7d: list[BriefItem]
    no_due_date: list[BriefItem]
    top_actions: list[str]              # plain language directives
