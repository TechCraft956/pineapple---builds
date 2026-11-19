"""Parse the manual-paste workflow into normalized trend records.

This is the workflow that demonstrably worked (brief #3): open the site in
a browser, copy the page text, paste it into the GUI. The recorded example
is data/trends_input.txt — a Thingiverse "Popular Last 30 Days" page paste.

Card block structure in the paste (verified against the recording):
    Thumbnail representing <title>
    Avatar
    <author>
    <likes>        (compact, e.g. 2K)
    <downloads>
    <remixes>
    <title>

Licence is NOT in the paste, so it stays unknown => sellable False (hard
default). Counts are unknown (None) when a block is partial.
"""
from __future__ import annotations

import re

from src.licensing import apply_licence, filament_fit
from src.models import TrendRecord, parse_compact_count, utcnow_iso

_NOISE = {
    "search", "welcome to thingiverse", "digital designs for physical objects",
    "popular last 30 days", "popular last 7 days", "all things", "filter by",
    "ready to be surprised?",
    "find and print unique, unexpected items from across thingiverse.",
    "thingiverse newsletter",
    "subscribe for news, community spotlights, and more!",
    "enter your email address", "hyper icon", "avatar",
}


def parse_pasted_thingiverse_text(raw_text: str) -> list[TrendRecord]:
    """Parse pasted Thingiverse page text into trend records."""
    lines = [ln.strip() for ln in raw_text.splitlines()]
    records: list[TrendRecord] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        thumb = re.match(r"^Thumbnail representing\s+(.+)$", line,
                         re.IGNORECASE)
        if not thumb:
            i += 1
            continue
        title = thumb.group(1).strip()
        # Walk forward: expect Avatar, author, likes, downloads, remixes, title.
        j = i + 1
        block: list[str] = []
        while j < len(lines) and len(block) < 6:
            nxt = lines[j]
            if re.match(r"^Thumbnail representing\s+", nxt, re.IGNORECASE):
                break
            block.append(nxt)
            j += 1
        # block: [Avatar?, author, likes, downloads, remixes, title?]
        block = [b for b in block if b.lower() != "avatar"]
        author = block[0] if block else ""
        likes = parse_compact_count(block[1]) if len(block) > 1 else None
        downloads = parse_compact_count(block[2]) if len(block) > 2 else None
        remixes = parse_compact_count(block[3]) if len(block) > 3 else None
        fit, fit_note = filament_fit(title)
        rec = TrendRecord(
            source="gui_paste", title=title, author=author,
            url="", licence=None,
            likes=likes, downloads=downloads, remixes=remixes,
            collected_at_utc=utcnow_iso(), spike=False,
            filament_fit=fit, filament_fit_note=fit_note,
            confidence=0.55,
        )
        apply_licence(rec)  # unknown licence => sellable False
        records.append(rec)
        i = j
    return records


def parse_pasted_text(raw_text: str, source: str = "thingiverse") -> list[TrendRecord]:
    """Generic entry point: today only the Thingiverse paste format is
    implemented (the recorded workflow). Other sources raise, rather than
    silently mis-parsing."""
    if source == "thingiverse":
        return parse_pasted_thingiverse_text(raw_text)
    raise ValueError(f"no paste parser for source {source!r}")
