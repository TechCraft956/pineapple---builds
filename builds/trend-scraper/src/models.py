"""Trend-record schema (build brief #3, BUILD-20261117-003).

ONE normalized record shape for every source (Thingiverse, Printables,
Google Trends, GUI paste). It reuses the Opportunity Engine / shared-feed
record shape from brief #2 — itemized costs, confidence, evidence quality,
approval status, provenance — never a second schema. The feed writer maps
this record onto the feed's opportunity schema (see writers/feed_writer.py).

Rules (carried over from the feed work + GPT-folded hardening 2026-11-17):
- unknown stays unknown, never zero (counts: None, never 0, when unstated).
- `licence` is recorded verbatim from the source page. A model is sellable
  ONLY when its licence, proven per model from the source page, affirmatively
  permits commercial use. Non-commercial => sellable False. Unknown licence
  => sellable False, reason "licence: unknown" (hard default, not "unknown").
- `filament_fit` is a heuristic against the owner's filament list, labelled
  as such — never a guarantee the model prints well.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

RECORD_FIELDS = (
    "source", "title", "url", "author", "licence",
    "likes", "downloads", "remixes", "collected_at_utc",
    "spike", "filament_fit", "filament_fit_note",
    "sellable", "sellable_reason", "confidence",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TrendRecord:
    source: str                     # thingiverse | printables | google_trends | gui_paste
    title: str
    url: str = ""
    author: str = ""
    licence: str | None = None      # verbatim from source page; None = unstated
    likes: int | None = None        # None = unknown, never 0-by-default
    downloads: int | None = None
    remixes: int | None = None
    collected_at_utc: str = field(default_factory=utcnow_iso)
    spike: bool = False
    filament_fit: str = "unknown"   # pla_plus | petg | silk_pla | not_compatible | unknown
    filament_fit_note: str = "filament fit is a heuristic, not a print guarantee"
    sellable: bool = False
    sellable_reason: str = "licence: unknown"
    confidence: float = 0.5         # 0..1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrendRecord":
        known = {k: v for k, v in data.items() if k in RECORD_FIELDS}
        return cls(**known)


def validate_record(rec: TrendRecord) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors = []
    if not rec.source:
        errors.append("source is required")
    if not rec.title:
        errors.append("title is required")
    if not (0.0 <= rec.confidence <= 1.0):
        errors.append(f"confidence {rec.confidence!r} outside 0..1")
    for name in ("likes", "downloads", "remixes"):
        value = getattr(rec, name)
        if value is not None and (not isinstance(value, int) or value < 0):
            errors.append(f"{name} must be a non-negative int or None, got {value!r}")
    if rec.sellable and rec.sellable_reason.startswith("licence: unknown"):
        errors.append("sellable=True with unknown licence is forbidden")
    if rec.sellable and rec.sellable_reason.startswith("licence: non-commercial"):
        errors.append("sellable=True with a non-commercial licence is forbidden")
    return errors


def parse_compact_count(text: str) -> int | None:
    """Parse '2K', '1.5K', '864' style counts. None when unparseable."""
    if text is None:
        return None
    text = str(text).strip().replace(",", "")
    if not text:
        return None
    m = re.fullmatch(r"([\d.]+)\s*([KM])?", text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    if suffix == "K":
        value *= 1_000
    elif suffix == "M":
        value *= 1_000_000
    return int(value)
