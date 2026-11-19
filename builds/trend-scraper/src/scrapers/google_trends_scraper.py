"""Google Trends scraper — refreshed terms for the sellable-prints track.

Refreshed 2026-11-17 (brief #3): the old 2024-era terms
("3D printed tools", "best STL files", "3D printer upgrades",
"custom keycaps", "miniature models") are replaced by the sellable-prints
categories: miniatures, organizers, tools, household, toys/games.
The 429 retry with doubling backoff and the 120 s inter-term delay are
kept; pytrends is unofficial and rate-limited, so a manual CSV export
remains the fallback (see parse_trends_csv()).

pytrends is imported lazily: importing this module never touches the
network. Spike detection (MinMaxScaler, threshold 0.5) is unchanged from
the recovered code.
"""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Sellable-prints categories (brief #3): miniatures, organizers, tools,
# household, toys/games.
SEARCH_TERMS = [
    "3d printed miniature",
    "3d printed organizer",
    "3d printed tools",
    "3d printed household",
    "3d printed toys",
]

# Terms kept from the recovered code (2024 recording, data/):
LEGACY_TERMS = ["3D printed tools", "best STL files", "3D printer upgrades",
                "custom keycaps", "miniature models"]

INTER_TERM_DELAY_S = 120


def detect_search_spike(data, threshold: float = 0.5) -> bool:
    """MinMaxScaler spike check (recovered logic, unchanged)."""
    if data is None:
        return False
    try:
        import pandas as pd
        from sklearn.preprocessing import MinMaxScaler

        if isinstance(data, pd.DataFrame):
            if data.empty:
                return False
            values = data.values
        else:
            values = data
        if len(values) == 0:
            return False
        scaler = MinMaxScaler()
        normalized = scaler.fit_transform(values)
        return bool(any(v > threshold for v in normalized.flatten()))
    except Exception as exc:
        logger.warning("spike detection failed: %s", exc)
        return False


def parse_trends_csv(path: str | Path) -> dict[str, list[float]]:
    """Parse a pytrends interest_over_time CSV (the format in
    data/google_trends_results.csv) into {term: [values]}. Offline-safe;
    this is the manual-export fallback when pytrends is rate-limited."""
    series: dict[str, list[float]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if len(rows) < 3:
        return series
    terms = [t.strip() for t in rows[0][1:] if t.strip()]
    for row in rows[2:]:
        if not row or not row[0].strip():
            continue
        for term, cell in zip(terms, row[1:]):
            try:
                series.setdefault(term, []).append(float(cell))
            except ValueError:
                continue
    return series


def series_to_records(series: dict[str, list[float]],
                      collected_at_utc: str | None = None) -> list:
    """Turn {term: values} into TrendRecords (source google_trends)."""
    from src.models import TrendRecord, utcnow_iso

    records = []
    for term, values in series.items():
        spike = detect_search_spike([values]) if values else False
        peak = max(values) if values else 0
        records.append(TrendRecord(
            source="google_trends",
            title=f"Google Trends: {term}",
            url="https://trends.google.com/trends/explore?q="
                + term.replace(" ", "%20"),
            licence=None,  # search interest has no licence; unknown => not sellable
            spike=spike,
            filament_fit="unknown",
            filament_fit_note="search-interest signal only; no model to fit filament to (heuristic)",
            confidence=0.7 if spike else 0.5,
            collected_at_utc=collected_at_utc or utcnow_iso(),
        ))
        # Attach the peak as evidence in the title-adjacent field via confidence:
        _ = peak
    return records


def fetch_trends(search_term: str, timeframe: str = "today 3-m",
                 max_retries: int = 5, wait_time: int = 60):
    """Fetch one term via pytrends with 429 doubling backoff (recovered
    logic). Returns a DataFrame or None. Live use only."""
    from pytrends.request import TrendReq

    pytrends = TrendReq(hl="en-US", tz=360)
    logging.info("Fetching trends for: %s", search_term)
    for _attempt in range(max_retries):
        try:
            pytrends.build_payload([search_term], cat=0, timeframe=timeframe,
                                   geo="", gprop="")
            data = pytrends.interest_over_time()
            if data is not None and not data.empty:
                return data.drop(columns=["isPartial"], errors="ignore")
            return data
        except Exception as exc:
            if "429" in str(exc):
                logging.error("Rate limit hit. Waiting %ss before retrying...",
                              wait_time)
                time.sleep(wait_time)
                wait_time *= 2
            else:
                logging.error("Error fetching trends for %s: %s", search_term, exc)
                return None
    logging.error("Failed to fetch trends for %s after retries.", search_term)
    return None


def fetch_all_terms(terms=None, timeframe: str = "today 3-m",
                    delay: int = INTER_TERM_DELAY_S) -> dict[str, list[float]]:
    """Live fetch for every term (opt-in live use only)."""
    out: dict[str, list[float]] = {}
    for term in (terms or SEARCH_TERMS):
        data = fetch_trends(term, timeframe=timeframe)
        if data is not None and not data.empty:
            col = data.columns[0]
            out[term] = [float(v) for v in data[col].tolist()]
            if detect_search_spike(data):
                logging.info("Potential trend spike detected for %s", term)
        time.sleep(delay)
    return out


def main():
    import pandas as pd

    all_data = {}
    for term in SEARCH_TERMS:
        trend_data = fetch_trends(term)
        if trend_data is not None:
            all_data[term] = trend_data
            if detect_search_spike(trend_data):
                logging.info("Potential trend spike detected for %s", term)
        time.sleep(INTER_TERM_DELAY_S)
    if all_data:
        combined = pd.concat(all_data.values(), axis=1)
        combined.to_csv("google_trends_results.csv")
        logging.info("Trends data saved to google_trends_results.csv")
    else:
        logging.warning("No data retrieved. Possible rate limit or empty results.")


if __name__ == "__main__":
    main()
