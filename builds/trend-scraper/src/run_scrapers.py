"""Runner: `python -m src.run_scrapers` from the repo root.

Modes:
- `--help` exits 0 without launching a browser or touching the network
  (acceptance check, brief #3 task 1).
- `--offline` (default): parse the recorded fixtures into trend records
  and save them — no network, no browser.
- `--live --source thingiverse|printables|google_trends`: live scrape
  (opt-in only; Thingiverse may 403 plain HTTP — use --browser for the
  Selenium path, or the GUI paste fallback).
- `--paste-file <path>`: parse a pasted-text file (the GUI workflow, headless).
- `--feed`: also POST the resulting records to the shared feed
  (FEED_URL / FEED_API_TOKEN env; see writers/feed_writer.py).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import TrendRecord  # noqa: E402
from src.processors.data_cleaner import save_records  # noqa: E402
from src.processors.paste_parser import parse_pasted_text  # noqa: E402


def _ensure_logs():
    Path(ROOT, "logs").mkdir(parents=True, exist_ok=True)


def _load_fixture_records() -> list[TrendRecord]:
    """Offline fixture run: recorded Thingiverse paste + Google Trends CSV
    + Printables fixture HTML, all under tests/fixtures/."""
    from src.scrapers import google_trends_scraper as gts
    from src.scrapers import printables_scraper as prs
    from src.scrapers import thingiverse_scraper as tvs

    records: list[TrendRecord] = []
    fx = ROOT / "tests" / "fixtures"
    paste = (fx / "thingiverse_paste_2026-11-17.txt").read_text(encoding="utf-8")
    records += parse_pasted_text(paste, source="thingiverse")
    records += prs.parse_search_html(
        (fx / "printables_search_2026-11-17.html").read_text(encoding="utf-8"))
    # Enrich the matching search record with the model page — do NOT append
    # a second record for the same model (same id would 409 the feed).
    model_html = (fx / "printables_model_2026-11-17.html").read_text(
        encoding="utf-8")
    for rec in records:
        if rec.source == "printables" and "589261" in rec.url:
            prs.enrich_from_model_page(rec, model_html)
    series = gts.parse_trends_csv(fx / "google_trends_2026-11-17.csv")
    records += gts.series_to_records(series)
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="src.run_scrapers",
        description="3D Trend Scraper — sellable-prints feeder (brief #3).")
    parser.add_argument("--source", choices=["thingiverse", "printables",
                                             "google_trends", "all"],
                        default="all")
    parser.add_argument("--offline", action="store_true",
                        help="fixture run only: no network, no browser (default)")
    parser.add_argument("--live", action="store_true",
                        help="opt-in live scrape (network + maybe browser)")
    parser.add_argument("--browser", action="store_true",
                        help="use Selenium for live Thingiverse (headless)")
    parser.add_argument("--query", default="miniature",
                        help="search term for live Thingiverse/Printables")
    parser.add_argument("--paste-file", type=Path,
                        help="parse a pasted-text file (GUI workflow, headless)")
    parser.add_argument("--output", default="trend_records",
                        help="output filename stem under data/")
    parser.add_argument("--feed", action="store_true",
                        help="also POST records to the shared feed")
    args = parser.parse_args(argv)

    _ensure_logs()
    logging.basicConfig(filename=str(ROOT / "logs" / "scraper.log"),
                        level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Starting scrapers (live=%s source=%s)", args.live, args.source)

    records: list[TrendRecord] = []
    if args.paste_file:
        records = parse_pasted_text(
            args.paste_file.read_text(encoding="utf-8"), source="thingiverse")
    elif args.live:
        from src.scrapers import google_trends_scraper as gts
        from src.scrapers import printables_scraper as prs
        from src.scrapers import thingiverse_scraper as tvs

        if args.source in ("thingiverse", "all"):
            records += tvs.scrape_thingiverse(query=args.query,
                                              use_browser=args.browser)
        if args.source in ("printables", "all"):
            records += prs.scrape_search(args.query)
        if args.source in ("google_trends", "all"):
            series = gts.fetch_all_terms()
            records += gts.series_to_records(series)
    else:
        records = _load_fixture_records()

    json_path, csv_path = save_records(records, filename=args.output)
    print(f"{len(records)} records -> {json_path} | {csv_path}")
    logging.info("Saved %d records to %s", len(records), json_path)

    if args.feed:
        from src.writers.feed_writer import post_records

        posted = post_records(records)
        print(f"Feed: {posted}")
        logging.info("Feed post: %s", posted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
