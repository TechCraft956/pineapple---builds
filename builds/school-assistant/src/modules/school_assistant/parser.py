from __future__ import annotations

import re
from typing import Optional

from .ingestion import Chunk
from .schemas import ItemType, ParsedCandidate
from .utils import parse_date, extract_time


# ── Title extraction ───────────────────────────────────────────────────────────

_NOISE_PREFIXES = re.compile(
    r"^[-*•–—\s]+|^(\d+[\.\)]\s*)",
    re.IGNORECASE,
)
_DUE_SPLIT = re.compile(
    r"\s+(due|by|deadline|submit(?:ted)?\s+by)\s+",
    re.IGNORECASE,
)
_DATE_INLINE = re.compile(
    r"\s*(?:[–\-:])\s*(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|\d{1,2}/\d{1,2})\b.*$",
    re.IGNORECASE,
)
_WEIGHT_TRAILING = re.compile(r"\s*\(?\d{1,3}(?:\.\d+)?%.*$")
_WEIGHT_PATTERN = re.compile(
    r"\(?\s*(\d{1,3}(?:\.\d+)?)\s*%\s*\)?"
)
_POINTS_PATTERN = re.compile(
    r"\b(\d{1,3})\s*(?:points?|pts?)\b",
    re.IGNORECASE,
)


def _extract_title(text: str) -> str:
    # Try splitting on "due" boundary first
    parts = _DUE_SPLIT.split(text, maxsplit=1)
    title = parts[0].strip()

    # Remove leading noise (bullet, number, "due:")
    title = _NOISE_PREFIXES.sub("", title).strip()

    # Strip trailing date and weight fragments like ": March 5 (30%)"
    title = _DATE_INLINE.sub("", title).strip()
    title = _WEIGHT_TRAILING.sub("", title).strip()

    # Truncate if too long (>80 chars likely contains noise)
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0]

    return title or text[:60]


def _extract_weight(text: str) -> Optional[float]:
    m = _WEIGHT_PATTERN.search(text)
    if m:
        return float(m.group(1))
    return None


def _map_chunk_type(chunk_type: str) -> ItemType:
    mapping = {
        "assignment": ItemType.assignment,
        "exam":       ItemType.exam,
        "quiz":       ItemType.quiz,
        "discussion": ItemType.discussion,
        "lab":        ItemType.lab,
    }
    return mapping.get(chunk_type, ItemType.other)


# ── Confidence scoring ─────────────────────────────────────────────────────────

def _score_confidence(signals: list[str]) -> float:
    """
    Each confirmed signal adds weight. Max 1.0.

    Signals and their weights:
      due_keyword       0.25
      date_found        0.30
      type_keyword      0.20
      title_clean       0.15
      weight_found      0.10
    """
    weights = {
        "due_keyword":  0.25,
        "date_found":   0.30,
        "type_keyword": 0.20,
        "title_clean":  0.15,
        "weight_found": 0.10,
    }
    return min(1.0, sum(weights.get(s, 0) for s in signals))


_DUE_KEYWORD_RE = re.compile(r"\b(due|deadline|submit|by)\b", re.IGNORECASE)
_TYPE_KEYWORD_RE = re.compile(
    r"\b(assignment|homework|hw|exam|midterm|final|quiz|discussion|post|lab|project|paper|report)\b",
    re.IGNORECASE,
)


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_chunk(chunk: Chunk) -> Optional[ParsedCandidate]:
    """
    Parse a single actionable chunk into a ParsedCandidate.
    Returns None if we can't extract a meaningful title.
    """
    text = chunk.text
    signals: list[str] = []

    # Date
    due_date = parse_date(text)
    if due_date:
        signals.append("date_found")

    # Due keyword
    if _DUE_KEYWORD_RE.search(text):
        signals.append("due_keyword")

    # Type keyword
    if _TYPE_KEYWORD_RE.search(text):
        signals.append("type_keyword")

    # Title
    title = _extract_title(text)
    if title and len(title) > 3:
        signals.append("title_clean")

    if not title:
        return None

    # Weight
    weight = _extract_weight(text)
    if weight is not None:
        signals.append("weight_found")

    # Time
    due_time = extract_time(text)

    return ParsedCandidate(
        title=title,
        type=_map_chunk_type(chunk.chunk_type),
        due_date=due_date,
        due_time=due_time,
        weight=weight,
        source_text=text,
        confidence_score=_score_confidence(signals),
        signals=signals,
    )


def parse_chunks(chunks: list[Chunk]) -> list[ParsedCandidate]:
    results = []
    for chunk in chunks:
        candidate = parse_chunk(chunk)
        if candidate:
            results.append(candidate)
    return results
