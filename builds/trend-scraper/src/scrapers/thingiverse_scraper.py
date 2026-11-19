"""Thingiverse scraper — search/category pages with counts + licence.

Selector verification (see SELECTORS.md for the dated log):
- 2026-11-17: live fetch of a Thingiverse search page was HTTP 403
  (anti-bot). Live re-verification is pending a browser-agent run on the
  owner's signed-in session, per the brief's routing.
- The card selectors below (div.ThingCard__card / h3.ThingCard__title) are
  the ones the recovered code used against the live homepage, and the card
  text structure (author, likes, downloads, remixes, title, in that order)
  is verified against the recorded real homepage paste in
  data/trends_input.txt (2025-01-31 recording, re-checked 2026-11-17).
- The parsers here are pure functions over HTML/text so they are testable
  offline against fixtures; the Selenium path is only for live runs.

Licence is proven PER MODEL from its own page (never inherited from a
category or site default). The search-page parse leaves licence None
(unknown => not sellable); enrich_with_licence() fills it from the model
page when a live run fetches it.
"""
from __future__ import annotations

import logging
import random
import time

from src.licensing import apply_licence, extract_licence_from_text, filament_fit
from src.models import TrendRecord, parse_compact_count, utcnow_iso

logger = logging.getLogger(__name__)

BASE_URL = "https://www.thingiverse.com"
SEARCH_URL = BASE_URL + "/search?q={query}&type=things&sort={sort}"
CATEGORY_URL = BASE_URL + "/categories/{category}"

# Selectors (recovered code, live homepage — see module docstring).
CARD_SELECTOR = "div.ThingCard__card"
TITLE_SELECTOR = "h3.ThingCard__title"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/109.0.5414.119 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/108.0.5359.124 Safari/537.36",
]


def parse_search_html(html: str, source_url: str = "") -> list[TrendRecord]:
    """Parse a Thingiverse search/category page into trend records.

    Card text order (verified against data/trends_input.txt): author,
    likes, downloads, remixes, then the title. Licence is NOT on the card:
    it stays None (unknown) until the model page is fetched.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    records: list[TrendRecord] = []
    for card in soup.select(CARD_SELECTOR):
        title_el = card.select_one(TITLE_SELECTOR)
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            continue
        link = card.select_one("a[href*='/thing:']")
        url = ""
        if link and link.get("href"):
            url = link["href"]
            if url.startswith("/"):
                url = BASE_URL + url
        # Card text lines after stripping the title: author, likes,
        # downloads, remixes (in that order, per the recorded paste).
        lines = [t.strip() for t in card.get_text("\n").split("\n") if t.strip()]
        lines = [t for t in lines if t != title]
        author = lines[0] if lines else ""
        counts = [parse_compact_count(t) for t in lines[1:4]]
        likes, downloads, remixes = (counts + [None, None, None])[:3]
        fit, fit_note = filament_fit(title)
        rec = TrendRecord(
            source="thingiverse", title=title, url=url or source_url,
            author=author, licence=None,
            likes=likes, downloads=downloads, remixes=remixes,
            collected_at_utc=utcnow_iso(), spike=False,
            filament_fit=fit, filament_fit_note=fit_note,
            confidence=0.6 if url else 0.5,
        )
        apply_licence(rec)  # unknown licence => sellable False
        records.append(rec)
    return records


def enrich_with_licence(rec: TrendRecord, model_page_html: str) -> TrendRecord:
    """Fill licence (verbatim, per model) from a model page's HTML/text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(model_page_html, "html.parser")
    text = soup.get_text("\n")
    licence = extract_licence_from_text(text)
    if licence:
        rec.licence = licence
        apply_licence(rec)
        rec.confidence = min(rec.confidence + 0.1, 0.85)
    return rec


def fetch_page_html(url: str, timeout: int = 30) -> str:
    """Plain HTTP fetch (no browser). Thingiverse may 403 this — callers
    must handle that and fall back to the Selenium path or the GUI paste."""
    import requests

    resp = requests.get(url, headers={"User-Agent": random.choice(USER_AGENTS)},
                        timeout=timeout)
    resp.raise_for_status()
    return resp.text


def scrape_search(query: str, sort: str = "popular", limit: int = 20,
                  driver=None) -> list[TrendRecord]:
    """Live search scrape. With driver=None tries plain HTTP first; on
    failure raises so the caller can use the Selenium path or GUI paste."""
    url = SEARCH_URL.format(query=query, sort=sort)
    if driver is None:
        html = fetch_page_html(url)
        return parse_search_html(html, source_url=url)[:limit]
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(url)
    WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, CARD_SELECTOR)))
    time.sleep(1)
    return parse_search_html(driver.page_source, source_url=url)[:limit]


def make_driver(headless: bool = True):
    """Create the undetected-Chrome driver (lazy import: importing this
    module never launches a browser)."""
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    if headless:
        options.add_argument("--headless=new")
    return uc.Chrome(options=options, use_subprocess=True)


def scrape_thingiverse(query: str = "miniature", sort: str = "popular",
                       limit: int = 20, use_browser: bool = False,
                       enrich_licences: bool = False) -> list[TrendRecord]:
    """Top-level live entry point (opt-in live use only)."""
    driver = make_driver() if use_browser else None
    try:
        records = scrape_search(query, sort=sort, limit=limit, driver=driver)
        if enrich_licences and driver is not None:
            for rec in records:
                if rec.url:
                    driver.get(rec.url)
                    time.sleep(1)
                    enrich_with_licence(rec, driver.page_source)
        return records
    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    print(scrape_thingiverse())
