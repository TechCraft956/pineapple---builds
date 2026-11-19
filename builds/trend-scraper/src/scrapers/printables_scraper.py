"""Printables scraper — search + model pages, same record shape as Thingiverse.

Selector verification, live text fetch 2026-11-17 (see SELECTORS.md):
- Search page https://www.printables.com/search/models?q=miniature returned
  model result links (first: "Honeycomb Wall Miniature Paint Holder ...",
  /model/589261-...). Selector `a[href^="/model/"]` VERIFIED.
- Model page /model/589261-... returned title, author ("dasfrodo"),
  description, and rating "4.8571428571/5 (21 ratings, 32 reviews)"
  in the server-rendered text. Title/author/description/rating selectors
  VERIFIED.
- Licence text and likes/downloads counts are NOT in the server-rendered
  text fetch (client-rendered). The Selenium path below looks for them in
  the rendered page; those two selectors are PROVISIONAL until a live
  browser run confirms them — the parser never invents them (unknown stays
  unknown, licence None => not sellable).

Licence is proven PER MODEL from its own page, never from a category default.
"""
from __future__ import annotations

import logging
import re
import time

from src.licensing import apply_licence, extract_licence_from_text, filament_fit
from src.models import TrendRecord, parse_compact_count, utcnow_iso

logger = logging.getLogger(__name__)

BASE_URL = "https://www.printables.com"
SEARCH_URL = BASE_URL + "/search/models?q={query}"

# Verified 2026-11-17 via live text fetch (see module docstring).
MODEL_LINK_SELECTOR = "a[href^='/model/']"


def parse_search_html(html: str, source_url: str = "") -> list[TrendRecord]:
    """Parse a Printables search page. Search results carry title + URL;
    counts/licence are not on the search page — they come from the model
    page via enrich_from_model_page()."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    records: list[TrendRecord] = []
    seen: set[str] = set()
    for link in soup.select(MODEL_LINK_SELECTOR):
        href = link.get("href") or ""
        if not href.startswith("/model/"):
            continue
        url = BASE_URL + href.split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        title = link.get_text(" ", strip=True)
        if not title:
            title = link.get("title", "") or link.get("aria-label", "")
        if not title:
            continue
        fit, fit_note = filament_fit(title)
        rec = TrendRecord(
            source="printables", title=title, url=url,
            collected_at_utc=utcnow_iso(), spike=False,
            filament_fit=fit, filament_fit_note=fit_note,
            confidence=0.5,
        )
        apply_licence(rec)  # unknown licence => sellable False
        records.append(rec)
    return records


def parse_model_page_html(html: str, url: str = "") -> TrendRecord | None:
    """Parse a Printables model page into a trend record.

    Verified-visible fields (2026-11-17 live fetch): <title> holds
    "<title> by <author> | Download free STL model | Printables.com";
    description text; rating "N/5 (R ratings, V reviews)". Licence and
    likes/downloads are client-rendered and may be absent — they stay None.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.string if soup.title and soup.title.string else ""
    h1 = soup.select_one("h1")
    title_text = h1.get_text(strip=True) if h1 and h1.get_text(strip=True) else page_title
    author = ""
    m = re.search(r"\bby\s+([A-Za-z0-9_\-]+)\s*\|", page_title)
    if m:
        author = m.group(1)
    title = re.split(r"\s+by\s+", title_text)[0].strip()
    title = re.sub(r"\s*\|\s*Download free STL model.*$", "", title).strip()
    if not title:
        return None
    text = soup.get_text("\n")
    licence = extract_licence_from_text(text)
    rating = None
    rm = re.search(r"Rating:\s*([\d.]+)/5\s*\((\d+)\s+ratings?,\s*(\d+)\s+reviews?\)",
                    text)
    likes = parse_compact_count(rm.group(2)) if rm else None
    desc = ""
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        desc = meta["content"]
    fit, fit_note = filament_fit(title, desc)
    rec = TrendRecord(
        source="printables", title=title, url=url, author=author,
        licence=licence, likes=likes,
        collected_at_utc=utcnow_iso(), spike=False,
        filament_fit=fit, filament_fit_note=fit_note,
        confidence=0.65 if licence else 0.5,
    )
    apply_licence(rec)
    return rec


def enrich_from_model_page(rec: TrendRecord, model_page_html: str) -> TrendRecord:
    """Fill author/licence/likes from a model page into a search record."""
    parsed = parse_model_page_html(model_page_html, url=rec.url)
    if parsed is None:
        return rec
    if parsed.author:
        rec.author = parsed.author
    if parsed.licence:
        rec.licence = parsed.licence
        apply_licence(rec)
        rec.confidence = min(rec.confidence + 0.1, 0.85)
    if parsed.likes is not None:
        rec.likes = parsed.likes
    return rec


def fetch_page_html(url: str, timeout: int = 30) -> str:
    import requests

    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                 "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
        timeout=timeout)
    resp.raise_for_status()
    return resp.text


def scrape_search(query: str, limit: int = 20, enrich: bool = False,
                  delay: float = 2.0) -> list[TrendRecord]:
    """Live search scrape (opt-in live use only)."""
    url = SEARCH_URL.format(query=query)
    records = parse_search_html(fetch_page_html(url), source_url=url)[:limit]
    if enrich:
        for rec in records:
            try:
                enrich_from_model_page(rec, fetch_page_html(rec.url))
            except Exception as exc:  # one bad model page must not kill the run
                logger.warning("Printables model page failed %s: %s", rec.url, exc)
            time.sleep(delay)
    return records


if __name__ == "__main__":
    print(scrape_search("miniature"))
