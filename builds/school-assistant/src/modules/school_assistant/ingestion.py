from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .utils import normalize_whitespace, strip_noise


@dataclass
class Chunk:
    text: str
    chunk_type: str = "unknown"   # syllabus_meta | assignment | exam | policy | irrelevant
    index: int = 0


# Keywords that identify academic item chunks
_ASSIGNMENT_KEYWORDS = re.compile(
    r"\b(assignment|homework|hw|project|paper|report|submission|deliverable)\b",
    re.IGNORECASE,
)
_EXAM_KEYWORDS = re.compile(
    r"\b(exam|midterm|final|test)\b",
    re.IGNORECASE,
)
_QUIZ_KEYWORDS = re.compile(
    r"\b(quiz|quizzes)\b",
    re.IGNORECASE,
)
_DISCUSSION_KEYWORDS = re.compile(
    r"\b(discussion|post|forum|response|reply)\b",
    re.IGNORECASE,
)
_LAB_KEYWORDS = re.compile(
    r"\b(lab|laboratory|practical)\b",
    re.IGNORECASE,
)
_DUE_KEYWORDS = re.compile(
    r"\b(due|submit|deadline|by)\b",
    re.IGNORECASE,
)
_POLICY_KEYWORDS = re.compile(
    r"\b(attendance|plagiarism|policy|late work|grading|grade scale|academic integrity|accommodations?)\b",
    re.IGNORECASE,
)
_META_KEYWORDS = re.compile(
    r"\b(instructor|professor|office hours?|email|syllabus|course description|textbook|prerequisite|required material)\b",
    re.IGNORECASE,
)
_DATE_SIGNAL = re.compile(
    r"\b(\d{1,2}[/\-]\d{1,2}|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
    re.IGNORECASE,
)


def _classify_chunk(text: str) -> str:
    lower = text.lower()
    has_date = bool(_DATE_SIGNAL.search(lower))
    has_due = bool(_DUE_KEYWORDS.search(lower))

    if _EXAM_KEYWORDS.search(lower) and (has_date or has_due):
        return "exam"
    if _QUIZ_KEYWORDS.search(lower) and (has_date or has_due):
        return "quiz"
    if _DISCUSSION_KEYWORDS.search(lower) and (has_date or has_due):
        return "discussion"
    if _LAB_KEYWORDS.search(lower) and (has_date or has_due):
        return "lab"
    if _ASSIGNMENT_KEYWORDS.search(lower) and (has_date or has_due):
        return "assignment"
    if has_due and has_date:
        return "assignment"   # fallback: has due + date, treat as assignment
    if _POLICY_KEYWORDS.search(lower):
        return "policy"
    if _META_KEYWORDS.search(lower):
        return "syllabus_meta"
    return "irrelevant"


def _split_chunks(text: str) -> list[str]:
    """
    Split text into chunks. Strategy:
    1. Double-newline boundaries (paragraph break)
    2. Numbered list items  (1. / 2. )
    3. Bullet points (- / * / •)
    4. Lines starting with a week/module keyword
    """
    # First: split on paragraph breaks
    paragraphs = re.split(r"\n{2,}", text)

    chunks: list[str] = []
    for para in paragraphs:
        # Try to split bullets/numbers within the paragraph
        lines = para.split("\n")
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            is_item_start = bool(re.match(r"^(\d+[\.\)]\s+|[-*•]\s+)", stripped))
            if is_item_start and current:
                chunks.append(" ".join(current))
                current = [stripped]
            else:
                current.append(stripped)
        if current:
            chunks.append(" ".join(current))

    return [c for c in chunks if len(c.strip()) > 10]


def preprocess(raw_text: str) -> tuple[str, list[Chunk]]:
    """
    Normalize raw input and return (clean_text, classified_chunks).
    """
    cleaned = strip_noise(raw_text)
    cleaned = normalize_whitespace(cleaned)

    raw_chunks = _split_chunks(cleaned)
    chunks = [
        Chunk(text=c, chunk_type=_classify_chunk(c), index=i)
        for i, c in enumerate(raw_chunks)
    ]
    return cleaned, chunks


def filter_actionable(chunks: list[Chunk]) -> list[Chunk]:
    """Keep only chunks that may contain school items."""
    actionable = {"assignment", "exam", "quiz", "discussion", "lab"}
    return [c for c in chunks if c.chunk_type in actionable]
