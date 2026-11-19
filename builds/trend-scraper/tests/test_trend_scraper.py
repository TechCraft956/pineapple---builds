"""Offline tests for the 3D Trend Scraper (brief #3, task 5).

No live network in the default run. The old live-only test becomes the
opt-in test at the bottom (run with --live; skipped otherwise).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.licensing import apply_licence, classify_licence, filament_fit  # noqa: E402
from src.models import TrendRecord, parse_compact_count, validate_record  # noqa: E402
from src.processors.paste_parser import parse_pasted_text  # noqa: E402
from src.scrapers import google_trends_scraper as gts  # noqa: E402
from src.scrapers import printables_scraper as prs  # noqa: E402
from src.scrapers import thingiverse_scraper as tvs  # noqa: E402
from src.writers.feed_writer import map_record  # noqa: E402

FX = ROOT / "tests" / "fixtures"


# --- schema ----------------------------------------------------------------

def test_record_validates():
    rec = TrendRecord(source="thingiverse", title="Flexi Fox",
                      url="https://www.thingiverse.com/thing:1",
                      author="LaCalavera", licence="CC BY 4.0",
                      likes=1000, downloads=373, remixes=6, confidence=0.7)
    apply_licence(rec)
    assert validate_record(rec) == []
    assert rec.sellable is True


def test_record_rejects_sellable_with_unknown_licence():
    rec = TrendRecord(source="thingiverse", title="Mystery Model",
                      sellable=True, sellable_reason="licence: unknown")
    assert validate_record(rec)  # must flag the contradiction


def test_counts_unknown_stays_none_not_zero():
    rec = TrendRecord(source="printables", title="No Counts Model")
    assert rec.likes is None and rec.downloads is None and rec.remixes is None


def test_parse_compact_count():
    assert parse_compact_count("2K") == 2000
    assert parse_compact_count("1.5K") == 1500
    assert parse_compact_count("864") == 864
    assert parse_compact_count("1,234") == 1234
    assert parse_compact_count("") is None
    assert parse_compact_count("n/a") is None


# --- licence filter (brief task 4 + GPT hardening) --------------------------

def test_licence_filter_fixture_set():
    """The brief's acceptance: CC-BY-NC, CC-BY, licence-less => exactly
    one sellable:true."""
    cases = json.loads((FX / "licence_cases.json").read_text())
    results = {}
    for case in cases["cases"]:
        sellable, reason = classify_licence(case["licence"])
        assert sellable == case["sellable"], case
        assert case["reason_contains"] in reason, (case, reason)
        results[case["licence"] or "<none>"] = sellable
    trio = [results["CC BY-NC-SA 4.0"], results["CC BY 4.0"],
            results["<none>"]]
    assert trio.count(True) == 1


def test_unknown_licence_hard_default():
    for lic in (None, "", "unknown", "No licence stated"):
        sellable, reason = classify_licence(lic)
        assert sellable is False
        assert reason == "licence: unknown"


def test_noncommercial_never_sellable():
    for lic in ("CC BY-NC 4.0", "CC BY-NC-SA 4.0", "Creative Commons - "
                "Attribution - Non-Commercial"):
        sellable, reason = classify_licence(lic)
        assert sellable is False
        assert "non-commercial" in reason


def test_filament_fit_is_labelled_heuristic():
    fit, note = filament_fit("Flexible TPU Phone Case")
    assert fit == "not_compatible"
    assert "heuristic" in note
    fit, note = filament_fit("Plain Desk Organizer")
    assert fit == "pla_plus"
    assert "heuristic" in note


# --- Thingiverse parsers ------------------------------------------------------

def test_thingiverse_search_fixture():
    html = (FX / "thingiverse_search_2026-11-17.html").read_text()
    recs = tvs.parse_search_html(html)
    assert len(recs) == 3  # empty card skipped
    first = recs[0]
    assert first.title == "Universal 3D Printed Bearing That Works"
    assert first.author == "ThinkingandTinkering"
    assert first.likes == 2000 and first.downloads == 1000
    assert first.remixes == 50
    assert first.url == "https://www.thingiverse.com/thing:1234567"
    assert first.licence is None and first.sellable is False
    assert first.sellable_reason == "licence: unknown"
    # Partial card: counts unknown, never zero.
    partial = recs[2]
    assert partial.title == "Unfinished Draft Model"
    assert partial.likes is None and partial.downloads is None
    assert partial.remixes is None


def test_thingiverse_empty_page():
    assert tvs.parse_search_html("<html><body></body></html>") == []
    assert tvs.parse_search_html("") == []


def test_thingiverse_licence_enrichment():
    rec = TrendRecord(source="thingiverse", title="Bearing",
                      url="https://www.thingiverse.com/thing:1")
    apply_licence(rec)
    assert rec.sellable is False
    html = ("<html><body><p>License: CC BY 4.0</p></body></html>")
    tvs.enrich_with_licence(rec, html)
    assert rec.licence == "CC BY 4.0"
    assert rec.sellable is True
    # NC model page must NOT flip to sellable.
    rec2 = TrendRecord(source="thingiverse", title="Fox")
    tvs.enrich_with_licence(
        rec2, "<html><body><p>License: CC BY-NC-SA 4.0</p></body></html>")
    assert rec2.sellable is False


# --- Printables parsers ------------------------------------------------------

def test_printables_search_fixture():
    html = (FX / "printables_search_2026-11-17.html").read_text()
    recs = prs.parse_search_html(html)
    assert len(recs) == 3  # duplicate link deduped
    assert recs[0].title.startswith("Honeycomb Wall Miniature Paint Holder")
    assert recs[0].url == ("https://www.printables.com/model/589261-"
                           "honeycomb-wall-miniature-paint-holder-citadel-vall")
    assert recs[0].licence is None and recs[0].sellable is False


def test_printables_model_fixture():
    html = (FX / "printables_model_2026-11-17.html").read_text()
    rec = prs.parse_model_page_html(
        html, url="https://www.printables.com/model/589261-"
                  "honeycomb-wall-miniature-paint-holder-citadel-vall")
    assert rec is not None
    assert rec.title.startswith("Honeycomb Wall Miniature Paint Holder")
    assert rec.author == "dasfrodo"
    assert rec.likes == 21  # ratings count parsed from the rating line
    assert rec.licence is None  # live fetch surfaced no licence
    assert rec.sellable is False
    assert rec.sellable_reason == "licence: unknown"


def test_printables_empty_page():
    assert prs.parse_search_html("<html><body></body></html>") == []
    assert prs.parse_model_page_html("<html><body></body></html>") is None


# --- GUI paste path -----------------------------------------------------------

def test_paste_parser_recorded_text():
    text = (FX / "thingiverse_paste_2026-11-17.txt").read_text()
    recs = parse_pasted_text(text, source="thingiverse")
    assert len(recs) == 20
    first = recs[0]
    assert first.title == "Universal 3D Printed Bearing That Works"
    assert first.author == "ThinkingandTinkering"
    assert first.likes == 2000 and first.downloads == 1000
    assert first.remixes == 50
    assert all(r.source == "gui_paste" for r in recs)
    assert all(r.sellable is False for r in recs)  # no licence in paste
    assert all(validate_record(r) == [] for r in recs)


def test_paste_parser_empty_text():
    assert parse_pasted_text("", source="thingiverse") == []
    assert parse_pasted_text("nothing relevant here", source="thingiverse") == []


def test_paste_parser_unknown_source():
    with pytest.raises(ValueError):
        parse_pasted_text("x", source="reddit")


# --- Google Trends ------------------------------------------------------------

def test_trends_csv_fixture_parses():
    series = gts.parse_trends_csv(FX / "google_trends_2026-11-17.csv")
    assert set(series) == set(gts.LEGACY_TERMS)
    assert len(series["miniature models"]) > 20
    recs = gts.series_to_records(series)
    assert len(recs) == 5
    assert all(r.source == "google_trends" for r in recs)
    assert all(validate_record(r) == [] for r in recs)


def test_spike_detection_around_threshold():
    # MinMaxScaler normalises per column, so a flat series never spikes
    # (every value maps to 0) and any varying series has a max of 1.
    assert gts.detect_search_spike([[0], [0], [0], [0]]) is False
    assert gts.detect_search_spike([[0], [0], [0], [100]]) is True
    # Threshold boundary: normalised max is exactly 1, so threshold 1.0
    # does NOT trigger but 0.99 does.
    assert gts.detect_search_spike([[0], [50], [100]], threshold=1.0) is False
    assert gts.detect_search_spike([[0], [50], [100]], threshold=0.99) is True
    assert gts.detect_search_spike(None) is False
    assert gts.detect_search_spike([]) is False


def test_refreshed_terms_are_sellable_categories():
    assert gts.SEARCH_TERMS == [
        "3d printed miniature", "3d printed organizer", "3d printed tools",
        "3d printed household", "3d printed toys",
    ]


# --- feed mapping (schema validation is in test_feed_roundtrip.py) -----------

def test_feed_mapping_keeps_unknown_value_unknown():
    rec = TrendRecord(source="thingiverse", title="Flexi Fox",
                      licence="CC BY 4.0")
    apply_licence(rec)
    mapped = map_record(rec)
    assert mapped["est_value"] == 0
    assert mapped["est_value_unknown"] is True
    assert mapped["approval_status"] == "PENDING"
    assert mapped["provenance"]["licence_verbatim"] == "CC BY 4.0"
    assert mapped["provenance"]["sellable"] is True


def test_fixture_run_records_have_unique_feed_ids():
    """Regression: the fixture run once emitted the same Printables model
    twice (search + model page) and the feed 409'd on the duplicate id."""
    from src.run_scrapers import _load_fixture_records
    from src.writers.feed_writer import map_records

    mapped = map_records(_load_fixture_records())
    ids = [m["id"] for m in mapped]
    assert len(ids) == len(set(ids)), "duplicate feed ids in fixture run"
    assert len(mapped) == 28


# --- GrabCAD: no import side effect ------------------------------------------

def test_grabcad_import_launches_no_browser():
    import src.scrapers.grabcad_scraper as grab

    assert hasattr(grab, "create_driver")
    assert hasattr(grab, "login")
    # login() with no credentials must fail loudly, not silently.
    with pytest.raises(RuntimeError, match="credentials not set"):
        grab.login(driver=None)


def test_thingiverse_import_launches_no_browser():
    import src.scrapers.thingiverse_scraper as tvs_mod

    assert hasattr(tvs_mod, "scrape_thingiverse")


# --- live test (opt-in only) ---------------------------------------------------

@pytest.mark.live
def test_live_thingiverse_homepage_smoke():
    """Old live-only test, now explicitly opt-in: pytest --live."""
    import requests

    resp = requests.get("https://www.thingiverse.com/",
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    assert resp.status_code == 200
    assert "ThingCard__card" in resp.text or "thingiverse" in resp.text.lower()
