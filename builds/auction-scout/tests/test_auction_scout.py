"""Offline fixture tests for Auction Scout. No network.

Run: python3 -m unittest discover -s tests -v   (from the build root)
Fixtures are real responses recorded live on 2026-11-17 (see cache meta
in BUILD_REPORT.md) — Public Surplus search/detail HTML and the GSA
PPMS search JSON for Texas, page 1.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import auction_scout as scout  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
ROOT = os.path.join(os.path.dirname(__file__), "..")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8", errors="replace") as fh:
        return fh.read()


class TestPublicSurplusParsing(unittest.TestCase):
    def test_all_tx_grid_parses_25_lots(self):
        lots = scout.parse_ps_grid(load("publicsurplus_search_all_tx.html"))
        self.assertEqual(len(lots), 25)
        for lot in lots:
            self.assertEqual(lot["state"], "TX")
            self.assertTrue(lot["lot_id"].isdigit())
            self.assertTrue(lot["closing_at_utc"].endswith("Z"))
        first = next(l for l in lots if l["lot_id"] == "4102866")
        self.assertEqual(first["title"], "FILE CABINET ~ SP-29-3")
        self.assertEqual(first["current_bid_usd"], 13.50)
        self.assertEqual(first["closing_at_utc"], "2026-11-18T16:00:00Z")
        self.assertEqual(first["url"],
                         "https://www.publicsurplus.com/sms/all,tx/auction/view?auc=4102866")

    def test_generator_search_finds_generators(self):
        lots = scout.parse_ps_grid(load("publicsurplus_search_generator.html"))
        self.assertEqual(len(lots), 4)
        titles = [l["title"] for l in lots]
        self.assertTrue(any("GENERATOR" in t.upper() for t in titles))
        gen = next(l for l in lots if l["lot_id"] == "4129958")
        self.assertIn("MEP-807A", gen["title"])
        self.assertEqual(scout.classify_category(gen["title"]), "generators")

    def test_detail_parse_quoted_facts(self):
        det = scout.parse_ps_detail(load("publicsurplus_detail_4129958.html"))
        self.assertEqual(det["city"], "Troup")
        self.assertEqual(det["state"], "TX")
        self.assertEqual(det["zip"], "75789")
        self.assertEqual(det["bid_count"], 1)
        self.assertEqual(det["current_bid_usd"], 555.00)
        self.assertIn("10.5%", det["fees_note"])
        self.assertIn("MEP-807A", det["condition_notes"])


class TestGsaParsing(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(load("gsa_search_tx_page1.json"))
        self.finds = scout.parse_gsa_response(self.payload, "2026-11-17T23:18:00Z")

    def test_texas_lots_normalized(self):
        self.assertEqual(self.payload["totalElements"], 70)
        self.assertEqual(len(self.finds), 10)  # page size 10 in the recorded response
        for f in self.finds:
            self.assertEqual(f["location"]["state"], "TX")
            self.assertEqual(f["source"], "gsa")
            self.assertEqual(f["provenance"]["retrieved_at_utc"], "2026-11-17T23:18:00Z")

    def test_sample_lot_fields(self):
        f = next(x for x in self.finds if x["lot_id"] == "413108")
        self.assertIn("Sikorsky UH-60A", f["title"])
        self.assertEqual(f["location"]["city"], "El Paso")
        self.assertEqual(f["current_bid_usd"], 500000.0)
        self.assertEqual(f["bid_count"], 1)
        # endDate 2026-11-19T10:00 naive, read as America/Chicago (CST, UTC-6)
        self.assertEqual(f["closing_at_utc"], "2026-11-19T16:00:00Z")
        self.assertEqual(f["distance_mi"], scout.distance_from_roma("El Paso"))


class TestCategoryClassifier(unittest.TestCase):
    CASES = {
        "MEP-807A 100KW DIESEL GENERATOR": "generators",
        "7000W Backup Generac Generator": "generators",
        "16FT UTILITY TRAILER": "trailers",
        "2013 Ram 1500": "vehicles",
        "2018 Dodge Durango": "vehicles",
        "Sikorsky UH-60A Blackhawk, SN: 79-23350": "vehicles",
        "CRAFTSMAN TOOL SET 220PC": "tools",
        "DEWALT CORDLESS DRILL": "tools",
        "JOHN DEERE TRACTOR LOADER": "equipment",
        "CATERPILLAR FORKLIFT": "equipment",
        "FILE CABINET ~ SP-29-3": "other",
        "PROJECTOR SCREEN": "other",
    }

    def test_cases(self):
        for title, expected in self.CASES.items():
            with self.subTest(title=title):
                self.assertEqual(scout.classify_category(title), expected)


class TestDistance(unittest.TestCase):
    def test_roma_to_roma_is_zero(self):
        self.assertEqual(scout.distance_from_roma("Roma"), 0.0)

    def test_roma_to_mcallen(self):
        d = scout.distance_from_roma("McAllen")
        self.assertIsNotNone(d)
        self.assertTrue(40 < d < 60, d)  # ~51 mi straight-line

    def test_unknown_city_is_none_never_guessed(self):
        self.assertIsNone(scout.distance_from_roma("Notarealtown"))
        self.assertIsNone(scout.distance_from_roma(None))
        self.assertIsNone(scout.distance_from_roma(""))

    def test_haversine_symmetric(self):
        a = scout.haversine_mi(scout.ROMA, scout.TX_CITIES["houston"])
        b = scout.haversine_mi(scout.TX_CITIES["houston"], scout.ROMA)
        self.assertAlmostEqual(a, b, places=6)
        self.assertTrue(300 < a < 340, a)


class TestBidNullHandling(unittest.TestCase):
    def test_ps_lot_without_price_is_none_not_zero(self):
        html = (
            '<div class="auction-item" id="9990001searchGrid">'
            '<span class="auction-item-state"> TX </span>'
            '<a href="/sms/all,tx/auction/view?auc=9990001" '
            'title="#9990001 - MYSTERY TOOL LOT">#9990001 - MYSTERY TOOL LOT</a>'
            "</div>"
        )
        lots = scout.parse_ps_grid(html)
        self.assertEqual(len(lots), 1)
        self.assertIsNone(lots[0]["current_bid_usd"])
        self.assertNotEqual(lots[0]["current_bid_usd"], 0)

    def test_gsa_lot_without_bid_is_none_not_zero(self):
        payload = {"auctionDTOList": [{
            "lotId": 1, "auctionId": 2, "lotName": "WRENCH SET",
            "endDate": "2026-11-20T10:00:00",
            "location": {"city": "AUSTIN", "state": "TX"},
        }]}
        finds = scout.parse_gsa_response(payload, "2026-11-17T00:00:00Z")
        self.assertEqual(len(finds), 1)
        self.assertIsNone(finds[0]["current_bid_usd"])
        self.assertIsNone(finds[0]["bid_count"])


class TestDedupeUpdate(unittest.TestCase):
    def _find(self, bid):
        return scout.make_find(
            title="GENERATOR", category="generators", source="gsa", lot_id="42",
            url="https://example.invalid/lot", location={"city": "Austin", "state": "TX"},
            current_bid_usd=bid, bid_count=1, closing_at_utc="2026-11-20T00:00:00Z",
            condition_notes="", fees_note=None,
            source_url="https://example.invalid", retrieved_at_utc="2026-11-17T00:00:00Z")

    def test_update_in_place_keeps_first_seen(self):
        first = scout.merge_finds([], [self._find(100.0)], "2026-11-17T01:00:00Z")
        self.assertEqual(len(first), 1)
        second = scout.merge_finds(first, [self._find(150.0)], "2026-11-17T02:00:00Z")
        self.assertEqual(len(second), 1)  # deduped by (source, lot_id)
        self.assertEqual(second[0]["current_bid_usd"], 150.0)  # bid move visible
        self.assertEqual(second[0]["first_seen_utc"], "2026-11-17T01:00:00Z")
        self.assertEqual(second[0]["last_seen_utc"], "2026-11-17T02:00:00Z")


class TestDealFirstSortAndDigest(unittest.TestCase):
    def _find(self, lot_id, closing, dist_city, category="tools", title=None):
        return scout.make_find(
            title=title or f"LOT {lot_id}", category=category, source="gsa",
            lot_id=lot_id, url="https://example.invalid",
            location={"city": dist_city, "state": "TX"} if dist_city else None,
            current_bid_usd=10.0, bid_count=0, closing_at_utc=closing,
            condition_notes="", fees_note=None,
            source_url="https://example.invalid", retrieved_at_utc="2026-11-17T00:00:00Z")

    def test_category_fit_beats_distance_and_closing(self):
        # A far, late-closing vehicle outranks a near, soon-closing tool:
        # category fit is the primary key (closing-first buried value).
        finds = [self._find("1", "2026-11-19T00:00:00Z", "McAllen"),
                 self._find("2", "2026-11-25T00:00:00Z", "Houston", category="vehicles")]
        ordered = scout.sort_open(finds)
        self.assertEqual([f["lot_id"] for f in ordered], ["2", "1"])

    def test_distance_then_closing_within_category(self):
        finds = [self._find("1", "2026-11-19T00:00:00Z", "Houston", category="vehicles"),
                 self._find("2", "2026-11-25T00:00:00Z", "McAllen", category="vehicles"),
                 self._find("3", "2026-11-20T00:00:00Z", "McAllen", category="vehicles")]
        ordered = scout.sort_open(finds)
        # McAllen (near) before Houston; within McAllen, sooner closing first.
        self.assertEqual([f["lot_id"] for f in ordered], ["3", "2", "1"])

    def test_unknown_distance_last_but_still_listed(self):
        finds = [self._find("1", "2026-11-19T00:00:00Z", None, category="vehicles"),
                 self._find("2", "2026-11-25T00:00:00Z", "Houston", category="vehicles"),
                 self._find("3", "2026-11-18T00:00:00Z", "McAllen", category="other")]
        ordered = scout.sort_open(finds)
        # Known distance before unknown within vehicles; "other" last
        # overall even though nearest and soonest; nothing dropped.
        self.assertEqual([f["lot_id"] for f in ordered], ["2", "1", "3"])
        self.assertEqual(len(ordered), 3)

    def test_digest_has_warning_and_splits_closed(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        finds = [self._find("1", "2026-11-20T00:00:00Z", "Austin"),
                 self._find("2", "2026-11-16T00:00:00Z", "Austin")]
        md = scout.render_digest(finds, [{"source": "gsa", "status": "WIRED", "finds": finds}], now)
        self.assertIn(scout.WARNING_LABEL, md)
        self.assertIn("## Recently closed", md)
        open_section = md.split("## Recently closed")[0]
        self.assertIn("LOT 1", open_section)
        self.assertNotIn("LOT 2", open_section)

    def test_digest_counts_sort_and_structure(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        finds = [self._find("1", "2026-11-20T00:00:00Z", "Austin"),
                 self._find("2", "2026-11-16T00:00:00Z", "Austin")]
        md = scout.render_digest(finds, [{"source": "gsa", "status": "WIRED", "finds": finds}], now)
        # Pulled == shown, stated on the page.
        self.assertIn("Lots pulled this run: 2 · Lots shown in this report: 2", md)
        # Sort order is explicit in the header.
        self.assertIn(scout.SORT_DESCRIPTION, md)
        # Source notes are a footnote at the bottom, after the lots.
        self.assertGreater(md.index("## Source notes"), md.index("## Recently closed"))
        # The low/no-anchor signal line is noise and must not render.
        self.assertNotIn("Resale signal:", md)
        self.assertNotIn("no retail anchor known", md)

    def test_digest_groups_by_lead_track_each_lot_once(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
        fy = self._find("1", "2026-11-20T00:00:00Z", "Austin",
                        category="generators", title="GENERAC GENERATOR 7000W")
        rs = self._find("2", "2026-11-20T00:00:00Z", "Austin",
                        category="vehicles", title="2018 DODGE DURANGO")
        md = scout.render_digest([fy, rs],
                                 [{"source": "gsa", "status": "WIRED", "finds": [fy, rs]}], now)
        # Personal section leads; resale section follows; each lot once.
        self.assertLess(md.index("## For You"), md.index("## Resale"))
        self.assertEqual(md.count("GENERAC GENERATOR 7000W"), 1)
        self.assertEqual(md.count("2018 DODGE DURANGO"), 1)
        self.assertIn("[FOR YOU, RESALE]", md)  # all tags ride on the line


class TestTrackClassification(unittest.TestCase):
    CASES = {
        # (title, category) -> expected tag set
        ("Sikorsky UH-60A Blackhawk, SN: 79-23350", "vehicles"):
            {"COOL FIND", "RESALE"},
        ("7000W Backup Generac Generator", "generators"):
            {"FOR YOU", "RESALE"},
        ("MEP-807A 100KW DIESEL GENERATOR", "generators"):
            {"FOR YOU", "RESALE"},
        ("PRUSA 3D PRINTER WITH FILAMENT", "other"):
            {"FOR YOU", "PROJECT ENABLER"},
        ("CRAFTSMAN TOOL SET 220PC", "tools"):
            {"FOR YOU", "RESALE"},
        ("16FT UTILITY TRAILER", "trailers"):
            {"FOR YOU", "RESALE"},
        ("2013 Ram 1500", "vehicles"):
            {"FOR YOU", "RESALE"},  # truck & trailer stuff is personal too
        ("LINCOLN WELDER", "tools"):
            {"FOR YOU", "PROJECT ENABLER", "RESALE"},
        ("FILE CABINET ~ SP-29-3", "other"):
            set(),  # untagged — still reported, under More lots
    }

    def test_cases(self):
        for (title, category), expected in self.CASES.items():
            with self.subTest(title=title):
                self.assertEqual(set(scout.classify_tracks(title, category)), expected)

    def test_lead_track_priority(self):
        f = scout.make_find(
            title="PRUSA 3D PRINTER", category="other", source="gsa", lot_id="9",
            url="https://example.invalid", location=None, current_bid_usd=None,
            bid_count=None, closing_at_utc=None, condition_notes="",
            fees_note=None, source_url="https://example.invalid",
            retrieved_at_utc="2026-11-17T00:00:00Z")
        self.assertEqual(f["tracks"], ["FOR YOU", "PROJECT ENABLER"])
        self.assertEqual(scout.lead_track(f), "FOR YOU")


class TestNoSnuffFetches(unittest.TestCase):
    """The no-filter guarantee at the fetch layer: lots are never dropped
    for category, and pagination never truncates a source silently."""

    def test_publicsurplus_keeps_other_category(self):
        fixture = load("publicsurplus_search_all_tx.html").encode()

        def fake_fetch(url, **kwargs):
            return 200, "2026-11-18T00:00:00Z", fixture

        import unittest.mock as mock
        with mock.patch.object(scout, "fetch", fake_fetch):
            result = scout.fetch_publicsurplus(cache_dir=None, detail_cap=0)
        # All 5 keyword searches return the same 25-lot grid; deduped to
        # 25 raw lots and EVERY one is kept, "other" included.
        self.assertEqual(result["raw_lot_count"], 25)
        self.assertEqual(len(result["finds"]), 25)
        self.assertTrue(any(f["category"] == "other" for f in result["finds"]))

    def test_gsa_pulls_all_pages(self):
        def lot(lot_id, name):
            return {"lotId": lot_id, "auctionId": lot_id + 100,
                    "lotName": name, "endDate": "2026-11-20T10:00:00",
                    "currentBid": 5, "numberOfBidders": 1,
                    "location": {"city": "AUSTIN", "state": "TX"}}

        pages = {
            1: {"totalElements": 3, "auctionDTOList": [lot(1, "DRILL"), lot(2, "SAW")]},
            2: {"totalElements": 3, "auctionDTOList": [lot(3, "WRENCH SET")]},
        }

        def fake_fetch(url, method="GET", body=None, **kwargs):
            page = json.loads(body)["params"]["page"]
            return 200, "2026-11-18T00:00:00Z", json.dumps(pages[page]).encode()

        import unittest.mock as mock
        with mock.patch.object(scout, "fetch", fake_fetch):
            result = scout.fetch_gsa(cache_dir=None)
        self.assertEqual(len(result["finds"]), 3)
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["total_elements"], 3)


class TestStubs(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "sources.json")) as fh:
            registry = json.load(fh)
        self.entries = {s["id"]: s for s in registry["sources"]}

    def test_registry_covers_four_sources(self):
        self.assertEqual(set(self.entries),
                         {"publicsurplus", "gsa", "govplanet", "txsurplus"})
        self.assertEqual(self.entries["publicsurplus"]["status"], "WIRED")
        self.assertEqual(self.entries["gsa"]["status"], "WIRED")
        self.assertEqual(self.entries["govplanet"]["status"], "NOT WIRED")
        self.assertEqual(self.entries["txsurplus"]["status"], "NOT WIRED")

    def test_stub_yields_zero_finds_with_reason_and_evidence(self):
        for source_id in ("govplanet", "txsurplus"):
            result = scout.NotWiredFetcher(self.entries[source_id]).fetch()
            self.assertEqual(result["status"], "NOT WIRED")
            self.assertEqual(result["finds"], [])  # a stub can never fabricate a lot
            self.assertTrue(result["reason"])
            self.assertTrue(result["evidence"])


class TestFindContract(unittest.TestCase):
    def test_contract_keys_and_signal(self):
        f = scout.make_find(
            title="DRILL", category="tools", source="gsa", lot_id="7",
            url="https://example.invalid", location=None, current_bid_usd=None,
            bid_count=None, closing_at_utc=None, condition_notes="",
            fees_note=None, source_url="https://example.invalid",
            retrieved_at_utc="2026-11-17T00:00:00Z")
        self.assertEqual(set(f), {
            "title", "category", "tracks", "source", "lot_id", "url", "location",
            "distance_mi", "current_bid_usd", "bid_count", "closing_at_utc",
            "condition_notes", "fees_note", "resale_signal", "provenance"})
        self.assertIsNone(f["distance_mi"])  # no location -> distance unknown
        self.assertEqual(f["resale_signal"]["level"], "low")
        self.assertIn("no retail anchor", f["resale_signal"]["note"])
        self.assertEqual(f["tracks"], ["FOR YOU", "RESALE"])  # a drill is both

    def test_feed_items_confidence_capped(self):
        f = scout.make_find(
            title="DRILL", category="tools", source="gsa", lot_id="7",
            url="https://example.invalid", location=None, current_bid_usd=None,
            bid_count=None, closing_at_utc=None, condition_notes="",
            fees_note=None, source_url="https://example.invalid",
            retrieved_at_utc="2026-11-17T00:00:00Z")
        items = scout.feed_items([f])
        self.assertEqual(items[0]["category"], "ASSETS")
        self.assertLessEqual(items[0]["confidence"], 0.6)
        self.assertIsNone(items[0]["est_value"])


if __name__ == "__main__":
    unittest.main()
