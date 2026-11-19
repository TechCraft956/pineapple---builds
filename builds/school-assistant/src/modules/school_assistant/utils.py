from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional


# Month name maps
_MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_DATE_PATTERNS = [
    # Month DD, YYYY  — e.g. "June 12, 2025"
    re.compile(
        r"\b(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b"
    ),
    # Month DD  — e.g. "June 12"
    re.compile(
        r"\b(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})\b"
    ),
    # MM/DD/YYYY or MM-DD-YYYY
    re.compile(
        r"\b(?P<month>\d{1,2})[/\-](?P<day>\d{1,2})[/\-](?P<year>\d{4})\b"
    ),
    # MM/DD
    re.compile(
        r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})\b"
    ),
]

_TIME_PATTERN = re.compile(
    r"\b(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))\b"
)


def parse_date(text: str) -> Optional[date]:
    """Extract the first recognizable date from a text snippet."""
    current_year = datetime.utcnow().year

    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):   # try every match, not just first
            g = m.groupdict()
            try:
                month_raw = g["month"]
                day = int(g["day"])
                year = int(g.get("year") or current_year)

                if month_raw.isdigit():
                    month = int(month_raw)
                else:
                    month = _MONTH_MAP.get(month_raw.lower())
                    if not month:
                        continue

                if not (1 <= month <= 12 and 1 <= day <= 31):
                    continue

                return date(year, month, day)
            except (ValueError, TypeError):
                continue

    return None


def extract_time(text: str) -> Optional[str]:
    m = _TIME_PATTERN.search(text)
    return m.group(1) if m else None


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def strip_noise(text: str) -> str:
    """Remove common header/footer noise and HTML artifacts."""
    text = re.sub(r"<[^>]+>", " ", text)            # basic HTML tags
    text = re.sub(r"&\w+;", " ", text)               # HTML entities
    text = re.sub(r"\[image[^\]]*\]", "", text)      # image placeholders
    text = re.sub(r"https?://\S+", "", text)         # URLs
    return text


def days_until(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days
