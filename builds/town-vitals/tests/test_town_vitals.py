"""Offline fixture tests for Town Vitals. No network.

Run:  python3 -m unittest discover -s tests -v   (from the build root)
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from town_vitals.census_client import (  # noqa: E402
    CensusClient, CensusKeyRequiredError, VariableVerificationError, parse_value)
from town_vitals.hooks import all_hooks, economy_signals, town_hall_items  # noqa: E402
from town_vitals.resolver import (  # noqa: E402
    AmbiguousPlaceError, Place, PlaceNotFoundError, PlaceResolver,
    normalize_name, places_from_dicts)
from town_vitals.vitals import assemble_vitals, to_item  # noqa: E402
from town_vitals.renderer import render_brief  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE_VALUES = json.loads((ROOT / "fixtures" / "fixture_values.json").read_text())
FIXTURE_PLACES = json.loads((ROOT / "fixtures" / "fixture_places.json").read_text())

PLACE = Place(name="Roma city", state_fips="48", place_fips="63020", state_name="Texas")
PROVENANCE = {
    "source_url": "https://api.census.gov/data/2024/acs/acs5?get=NAME,B01003_001E&for=place:63020&in=state:48",
    "retrieved_at_utc": "2026-11-17T00:00:00Z",
    "api_query": "https://api.census.gov/data/2024/acs/acs5?get=NAME,B01003_001E&for=place:63020&in=state:48",
    "vintage": 2024,
}


def parsed(raw):
    return {k: parse_value(v) for k, v in raw.items()}


def make_record(with_prior=True):
    prior = parsed(FIXTURE_VALUES["prior"]) if with_prior else None
    return assemble_vitals(
        PLACE, parsed(FIXTURE_VALUES["latest"]), 2024, dict(PROVENANCE),
        prior_values=prior, prior_vintage=2019 if with_prior else None)


class TestSentinelParsing(unittest.TestCase):
    def test_sentinels_become_null(self):
        for raw in ("-666666666", "-888888888", "-999999999", "-555555555",
                    -666666666, "", None, "null"):
            self.assertIsNone(parse_value(raw), raw)

    def test_normal_values_parse(self):
        self.assertEqual(parse_value("11545"), 11545)
        self.assertEqual(parse_value("32.5"), 32.5)
        self.assertEqual(parse_value("0"), 0)

    def test_sentinel_in_fixture_record_is_null_not_number(self):
        record = make_record()
        self.assertIsNone(record["figures"]["median_home_value"])


class TestVariableVerification(unittest.TestCase):
    def test_missing_variable_fails_loudly(self):
        catalog = {"variables": {"B01003_001E": {"label": "Estimate!!Total"}}}
        client = CensusClient(fetch=lambda url: (url, json.dumps(catalog)))
        with self.assertRaises(VariableVerificationError):
            client.verify_variables(2024, ["B01003_001E", "B99999_001E"])

    def test_present_variables_verify(self):
        catalog = {"variables": {"B01003_001E": {"label": "Estimate!!Total"}}}
        client = CensusClient(fetch=lambda url: (url, json.dumps(catalog)))
        labels = client.verify_variables(2024, ["B01003_001E"])
        self.assertEqual(labels["B01003_001E"], "Estimate!!Total")


class TestKeyRequiredDetection(unittest.TestCase):
    def test_missing_key_redirect_raises(self):
        def fake_fetch(url):
            return ("https://api.census.gov/data/missing_key.html",
                    "<html><title>Missing Key</title></html>")
        client = CensusClient(fetch=fake_fetch)
        with self.assertRaises(CensusKeyRequiredError):
            client.fetch_place(2024, "48", "63020", ["B01003_001E"])


class TestRateMath(unittest.TestCase):
    def test_rates_from_raw_counts(self):
        f = make_record()["figures"]
        self.assertEqual(f["poverty_rate"], 25.0)          # 2500/10000
        self.assertEqual(f["unemployment_rate"], 5.0)      # 200/4000
        self.assertEqual(f["owner_occupied_rate"], 70.0)   # 2100/3000

    def test_composition_math(self):
        comp = make_record()["figures"]["composition"]
        self.assertEqual(comp["hispanic_or_latino_pct"], 90.0)
        self.assertEqual(comp["white_alone_pct"], 78.0)    # (800+7000)/10000
        self.assertEqual(comp["black_alone_pct"], 1.5)     # (100+50)/10000
        self.assertEqual(comp["other_pct"], 20.5)          # remainder

    def test_formulas_stored_on_record(self):
        record = make_record()
        for key in ("poverty_rate", "unemployment_rate", "owner_occupied_rate",
                    "hispanic_or_latino_pct", "growth_pct_change"):
            self.assertIn(key, record["formulas"])


class TestResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = PlaceResolver(places_from_dicts(FIXTURE_PLACES))

    def test_exact_match(self):
        place = self.resolver.resolve("Roma city", state_fips="48")
        self.assertEqual(place.geoid, "4863020")

    def test_suffix_insensitive_match(self):
        self.assertEqual(normalize_name("Roma city"), "roma")
        place = self.resolver.resolve("roma", state_fips="48")
        self.assertEqual(place.place_fips, "63020")

    def test_ambiguity_returns_candidates_never_silent_pick(self):
        with self.assertRaises(AmbiguousPlaceError) as ctx:
            self.resolver.resolve("Midway", state_fips="48")
        self.assertEqual(len(ctx.exception.candidates), 2)
        self.assertEqual({c.place_fips for c in ctx.exception.candidates},
                         {"11111", "22222"})

    def test_not_found(self):
        with self.assertRaises(PlaceNotFoundError):
            self.resolver.resolve("Nowhereville", state_fips="48")


class TestGrowthGating(unittest.TestCase):
    def test_growth_with_two_vintages(self):
        growth = make_record(with_prior=True)["growth"]
        self.assertEqual(growth["prior_vintage"], 2019)
        self.assertEqual(growth["prior_population"], 9500)
        self.assertEqual(growth["pct_change"], 5.26)  # (10000-9500)/9500*100

    def test_no_growth_from_single_vintage(self):
        self.assertIsNone(make_record(with_prior=False)["growth"])

    def test_no_growth_when_prior_population_missing(self):
        record = assemble_vitals(
            PLACE, parsed(FIXTURE_VALUES["latest"]), 2024, dict(PROVENANCE),
            prior_values={"B01003_001E": None}, prior_vintage=2019)
        self.assertIsNone(record["growth"])


class TestRenderer(unittest.TestCase):
    def test_every_nonnull_figure_appears_and_nulls_render_unknown(self):
        brief = render_brief(make_record())
        for expected in ("10,000", "$30,000", "32.5", "25.0%", "5.0%",
                         "70.0%", "90.0%", "78.0%", "1.5%", "20.5%"):
            self.assertIn(expected, brief)
        # median home value is the sentinel fixture -> unknown, never a number
        self.assertIn("| Median home value | unknown |", brief)

    def test_growth_line_names_both_vintages(self):
        brief = render_brief(make_record())
        self.assertIn("ACS 2019", brief)
        self.assertIn("ACS 2024", brief)
        self.assertIn("+5.3%", brief)

    def test_single_vintage_growth_line(self):
        brief = render_brief(make_record(with_prior=False))
        self.assertIn("Growth unknown — single vintage pulled", brief)

    def test_provenance_and_planning_signal_and_hooks_footer(self):
        brief = render_brief(make_record())
        self.assertIn("planning signal, not an official statistic", brief.lower())
        self.assertIn(PROVENANCE["source_url"], brief)
        self.assertIn("2026-11-17T00:00:00Z", brief)
        self.assertIn("town_hall_items: NOT WIRED", brief)
        self.assertIn("economy_signals: NOT WIRED", brief)


class TestHooksAndItem(unittest.TestCase):
    def test_hooks_return_not_wired_markers(self):
        for hook in (town_hall_items(), economy_signals()):
            self.assertEqual(hook["status"], "NOT WIRED")
            self.assertEqual(hook["items"], [])
        self.assertEqual(len(all_hooks()), 2)

    def test_item_shape(self):
        item = to_item(make_record())
        self.assertEqual(item["title"], "Town Vitals — Roma city, Texas")
        self.assertEqual(item["category"], "PLACES")
        self.assertIsNone(item["est_value"])
        self.assertEqual(item["confidence"], 0.8)
        self.assertEqual(item["url"], PROVENANCE["source_url"])
        self.assertEqual(item["location"], "Roma city, Texas")


if __name__ == "__main__":
    unittest.main()
