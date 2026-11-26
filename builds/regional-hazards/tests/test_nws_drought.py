"""Tests for sensor #74 (NWS forecasts/alerts + U.S. Drought Monitor) — stdlib unittest.

Fixture-based; no network is touched by these tests. Fixtures are trimmed
captures of the live NWS and USDM responses (2026-11-26): the point lookup
for Roma, TX, the 7-day and hourly forecasts, an empty zone-alerts result,
one real Texas Freeze Warning, and USDM CountyStatistics rows (categorical
+ traditional) for Starr County FIPS 48427.
"""
import io
import json
import os
import sys
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import nws_drought  # noqa: E402

RETRIEVED = "2026-11-26T19:00:00Z"


def load_fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


def fixture_bytes(name):
    with open(os.path.join(HERE, "fixtures", name), "rb") as fh:
        return fh.read()


class StubFetcher:
    """Return fixture bytes keyed on URL substring; record calls."""

    def __init__(self, mapping, fail_on=()):
        self.mapping = mapping  # list of (substring, fixture_name)
        self.fail_on = fail_on
        self.calls = []

    def __call__(self, url, params=None, timeout=90, headers=None):
        self.calls.append(url)
        hay = url
        if params:
            import urllib.parse
            hay = url + "?" + urllib.parse.urlencode(params)
        for needle in self.fail_on:
            if needle in hay:
                raise urllib.error.HTTPError(url, 503, "Service Unavailable",
                                             {}, io.BytesIO(b""))
        for needle, fixture in self.mapping:
            if needle in hay:
                return fixture_bytes(fixture)
        raise AssertionError(f"unexpected URL in stub fetcher: {hay}")


FULL_MAPPING = [
    ("points/26.4073", "nws_drought_point.json"),
    ("forecast/hourly", "nws_drought_hourly.json"),
    ("forecast", "nws_drought_forecast.json"),
    ("alerts/active?area=TX", "nws_drought_alerts_tx.json"),
    ("alerts/active", "nws_drought_alerts_zone.json"),
    ("statisticsType=2", "nws_drought_usdm_categorical.json"),
    ("statisticsType=1", "nws_drought_usdm_traditional.json"),
]


class TestPointParsing(unittest.TestCase):
    def setUp(self):
        self.payload = load_fixture("nws_drought_point.json")
        self.point = nws_drought.parse_point(self.payload, RETRIEVED)

    def test_resolves_gridpoint_and_zone(self):
        self.assertEqual(self.point["cwa"], "BRO")
        self.assertEqual(self.point["grid_id"], "BRO")
        self.assertEqual(self.point["grid_x"], 20)
        self.assertEqual(self.point["grid_y"], 29)
        self.assertEqual(self.point["forecast_zone"], "TXZ252")
        self.assertEqual(self.point["county_zone"], "TXC427")
        self.assertEqual(self.point["status"], "VERIFIED")

    def test_forecast_urls_come_from_point_response(self):
        self.assertEqual(
            self.point["forecast_url"],
            "https://api.weather.gov/gridpoints/BRO/20,29/forecast")
        self.assertEqual(
            self.point["forecast_hourly_url"],
            "https://api.weather.gov/gridpoints/BRO/20,29/forecast/hourly")

    def test_nearest_place_recorded(self):
        self.assertEqual(self.point["nearest_place"], "Escobares")
        self.assertEqual(self.point["nearest_place_state"], "TX")

    def test_missing_forecast_zone_is_unknown_not_invented(self):
        props = dict(self.payload["properties"])
        props.pop("forecastZone")
        props.pop("forecast")
        point = nws_drought.parse_point({"properties": props}, RETRIEVED)
        self.assertIsNone(point["forecast_zone"])
        self.assertIsNone(point["forecast_url"])
        self.assertEqual(point["status"], "UNKNOWN")


class TestForecastParsing(unittest.TestCase):
    def setUp(self):
        self.payload = load_fixture("nws_drought_forecast.json")
        self.periods = [nws_drought.parse_forecast_period(p, RETRIEVED)
                        for p in self.payload["properties"]["periods"]]

    def test_first_period_fields(self):
        p = self.periods[0]
        self.assertEqual(p["name"], "Thanksgiving Day")
        self.assertEqual(p["temperature"], 63)
        self.assertEqual(p["temperature_unit"], "F")
        self.assertEqual(p["short_forecast"], "Mostly Cloudy")
        self.assertEqual(p["precipitation_probability_percent"], 0)
        self.assertEqual(p["status"], "VERIFIED")

    def test_empty_wind_direction_becomes_none(self):
        # 'Tonight' has windDirection '' in the live payload.
        p = self.periods[1]
        self.assertEqual(p["name"], "Tonight")
        self.assertIsNone(p["wind_direction"])

    def test_missing_temperature_is_unknown_not_zero(self):
        period = dict(self.payload["properties"]["periods"][0])
        period.pop("temperature")
        p = nws_drought.parse_forecast_period(period, RETRIEVED)
        self.assertIsNone(p["temperature"])
        self.assertEqual(p["status"], "UNKNOWN")


class TestHourlyParsing(unittest.TestCase):
    def setUp(self):
        self.payload = load_fixture("nws_drought_hourly.json")
        self.periods = [nws_drought.parse_forecast_period(
            p, RETRIEVED, kind="forecast_hourly")
            for p in self.payload["properties"]["periods"]]

    def test_hourly_fields_include_humidity(self):
        p = self.periods[0]
        self.assertEqual(p["metric"], "forecast_hourly")
        self.assertEqual(p["temperature"], 61)
        self.assertEqual(p["relative_humidity_percent"], 42)
        self.assertEqual(p["wind_speed"], "3 mph")
        self.assertEqual(p["precipitation_probability_percent"], 0)

    def test_missing_humidity_stays_none(self):
        period = dict(self.payload["properties"]["periods"][0])
        period.pop("relativeHumidity")
        p = nws_drought.parse_forecast_period(period, RETRIEVED,
                                              kind="forecast_hourly")
        self.assertIsNone(p["relative_humidity_percent"])


class TestAlertParsing(unittest.TestCase):
    def setUp(self):
        self.payload = load_fixture("nws_drought_alerts_tx.json")
        self.alert = nws_drought.parse_alert(
            self.payload["features"][0], RETRIEVED)

    def test_freeze_warning_fields(self):
        self.assertEqual(self.alert["event"], "Freeze Warning")
        self.assertEqual(self.alert["severity"], "Severe")
        self.assertEqual(self.alert["certainty"], "Likely")
        self.assertEqual(self.alert["urgency"], "Expected")
        self.assertEqual(self.alert["sender_name"], "NWS Lake Charles LA")
        self.assertEqual(self.alert["status"], "VERIFIED")

    def test_affected_zones_are_codes_not_urls(self):
        self.assertIn("TXZ180", self.alert["affected_zones"])
        self.assertNotIn(
            "https://api.weather.gov/zones/forecast/TXZ180",
            self.alert["affected_zones"])

    def test_empty_zone_alerts_is_zero_not_failure(self):
        zone = load_fixture("nws_drought_alerts_zone.json")
        self.assertEqual(zone["features"], [])


class TestUsdmParsing(unittest.TestCase):
    def test_categorical_row_latest_release(self):
        rows = load_fixture("nws_drought_usdm_categorical.json")
        obs = nws_drought.parse_usdm_row(rows[0], RETRIEVED, "categorical")
        self.assertEqual(obs["map_date"], "2026-11-24")
        self.assertEqual(obs["valid_end"], "2026-11-30")
        self.assertEqual(obs["fips"], "48427")
        self.assertEqual(obs["county"], "Starr County")
        self.assertEqual(obs["area_sq_mi"]["d0"], 1214.95)
        self.assertEqual(obs["area_sq_mi"]["d1"], 0.00)
        self.assertEqual(obs["area_sq_mi"]["d4"], 0.00)
        self.assertEqual(obs["area_percent"]["d0"], 100.0)
        self.assertEqual(obs["area_percent"]["d1"], 0.0)
        self.assertEqual(obs["county_total_sq_mi"], 1214.95)
        self.assertEqual(obs["status"], "VERIFIED")

    def test_categorical_row_prior_week_had_d1(self):
        rows = load_fixture("nws_drought_usdm_categorical.json")
        obs = nws_drought.parse_usdm_row(rows[1], RETRIEVED, "categorical")
        self.assertEqual(obs["map_date"], "2026-11-17")
        self.assertEqual(obs["area_sq_mi"]["d0"], 911.69)
        self.assertEqual(obs["area_sq_mi"]["d1"], 303.26)
        self.assertAlmostEqual(obs["area_percent"]["d0"], 75.04, places=2)
        self.assertAlmostEqual(obs["area_percent"]["d1"], 24.96, places=2)

    def test_traditional_row_is_cumulative(self):
        rows = load_fixture("nws_drought_usdm_traditional.json")
        obs = nws_drought.parse_usdm_row(rows[0], RETRIEVED, "traditional")
        # Traditional D0 includes D1-D4, so it equals the county total here.
        self.assertEqual(obs["area_sq_mi"]["d0"], 1214.95)
        self.assertEqual(obs["statistic_format"], "traditional")

    def test_wrong_fips_is_unknown(self):
        rows = load_fixture("nws_drought_usdm_categorical.json")
        row = dict(rows[0])
        row["fips"] = "99999"
        obs = nws_drought.parse_usdm_row(row, RETRIEVED, "categorical")
        self.assertEqual(obs["status"], "UNKNOWN")

    def test_missing_category_stays_none_not_zero(self):
        rows = load_fixture("nws_drought_usdm_categorical.json")
        row = dict(rows[0])
        row.pop("d2")
        obs = nws_drought.parse_usdm_row(row, RETRIEVED, "categorical")
        self.assertIsNone(obs["area_sq_mi"]["d2"])
        self.assertIsNone(obs["area_percent"]["d2"])
        self.assertIsNone(obs["county_total_sq_mi"])


class TestCollect(unittest.TestCase):
    def test_full_collect_with_stub_fetcher(self):
        fetcher = StubFetcher(FULL_MAPPING)
        doc = nws_drought.collect(fetcher=fetcher)
        self.assertEqual(doc["sensor_id"], 74)
        self.assertEqual(doc["summary"]["nws_forecast_zone"], "TXZ252")
        self.assertEqual(doc["summary"]["nws_forecast_periods"], 4)
        self.assertEqual(doc["summary"]["nws_hourly_periods_kept"], 3)
        self.assertEqual(doc["summary"]["nws_active_alerts_starr_zone"], 0)
        self.assertEqual(doc["summary"]["nws_active_alerts_tx"], 1)
        self.assertEqual(doc["summary"]["usdm_latest_map_date"], "2026-11-24")
        self.assertEqual(
            doc["summary"]["usdm_starr_drought_categorical_percent"]["d0"],
            100.0)
        self.assertEqual(doc["summary"]["usdm_status"], "VERIFIED")
        self.assertEqual(doc["summary"]["usdm_week_count"], 2)
        # Observations carry the point + periods + latest drought rows.
        metrics = [o["metric"] for o in doc["observations"]]
        self.assertIn("nws_point", metrics)
        self.assertIn("usdm_county_drought", metrics)

    def test_collect_survives_failed_legs(self):
        fetcher = StubFetcher(FULL_MAPPING, fail_on=("usdm", "alerts/active"))
        doc = nws_drought.collect(fetcher=fetcher)
        self.assertEqual(doc["summary"]["nws_forecast_zone"], "TXZ252")
        self.assertEqual(doc["summary"]["nws_forecast_periods"], 4)
        self.assertEqual(doc["summary"]["nws_alerts_status"], "UNKNOWN")
        self.assertEqual(doc["summary"]["usdm_status"], "UNKNOWN")
        self.assertIsNone(doc["summary"]["usdm_latest_map_date"])
        self.assertIsNone(
            doc["summary"]["usdm_starr_drought_categorical_percent"])

    def test_usdm_window_is_five_weeks(self):
        start, end = nws_drought._usdm_window()
        from datetime import datetime, timezone
        s = datetime.strptime(start, "%m/%d/%Y").date()
        e = datetime.strptime(end, "%m/%d/%Y").date()
        self.assertEqual((e - s).days, 35)
        self.assertEqual(e, datetime.now(timezone.utc).date())


if __name__ == "__main__":
    unittest.main()
