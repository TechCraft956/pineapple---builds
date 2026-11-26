"""Tests for laus.py (sensor #101) — offline fixtures, no network calls."""

import io
import json
import unittest

import laus


FAKE_PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {"series": [
        {"seriesID": "LAUCN484270000000003", "data": [
            {"year": "2026", "period": "M08", "periodName": "August",
             "value": "9.3", "footnotes": [{}]},
            {"year": "2026", "period": "M09", "periodName": "September",
             "value": "8.3", "footnotes": [{"code": "P",
                                             "text": "Preliminary."}]},
        ]},
        {"seriesID": "LAUCN484270000000006", "data": [
            {"year": "2026", "period": "M09", "periodName": "September",
             "value": "28765", "footnotes": [{"code": "P",
                                               "text": "Preliminary."}]},
        ]},
        {"seriesID": "LAUST480000000000003", "data": [
            {"year": "2026", "period": "M09", "periodName": "September",
             "value": "4.1", "footnotes": [{}]},
        ]},
    ]},
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestSeriesIds(unittest.TestCase):
    def test_county_id(self):
        self.assertEqual(laus.series_id("CN", "48427", "03"),
                         "LAUCN484270000000003")
        self.assertEqual(laus.series_id("CN", "48427", "06"),
                         "LAUCN484270000000006")

    def test_msa_id(self):
        self.assertEqual(laus.series_id("MT", "32580", "03"),
                         "LAUMT483258000000003")

    def test_state_id(self):
        self.assertEqual(laus.series_id("ST", "48", "03"),
                         "LAUST480000000000003")

    def test_series_list_counts(self):
        wanted = laus.build_series_list()
        self.assertEqual(len(wanted), 12)  # 3 areas x 4 measures
        ids = {w["series_id"] for w in wanted}
        self.assertIn("LAUCN484270000000003", ids)
        self.assertIn("LAUMT483258000000005", ids)
        rgv = laus.build_series_list(include_rgv=True)
        self.assertEqual(len(rgv), 24)  # + 3 counties x 4 measures


class TestParsePayload(unittest.TestCase):
    def setUp(self):
        self.meta = {w["series_id"]: w
                     for w in laus.build_series_list()}

    def test_values_and_preliminary_flag(self):
        obs = laus.parse_series_payload(FAKE_PAYLOAD, self.meta,
                                        "2026-11-26T00:00:00Z")
        self.assertEqual(len(obs), 4)
        rate = [o for o in obs if o["measure"] == "unemployment_rate"
                and o["scope"] == "starr"]
        self.assertEqual(len(rate), 2)
        latest = rate[-1]
        self.assertEqual(latest["value"], 8.3)
        self.assertTrue(latest["preliminary"])
        self.assertEqual(latest["label"], "VERIFIED")
        self.assertEqual(latest["month"], "M09")
        self.assertEqual(latest["year"], 2026)

    def test_labor_force_and_state_context(self):
        obs = laus.parse_series_payload(FAKE_PAYLOAD, self.meta,
                                        "2026-11-26T00:00:00Z")
        lf = [o for o in obs if o["measure"] == "labor_force"][0]
        self.assertEqual(lf["value"], 28765.0)
        tx = [o for o in obs if o["scope"] == "texas"][0]
        self.assertEqual(tx["value"], 4.1)
        self.assertFalse(tx["preliminary"])

    def test_missing_value_is_reported_not_zero(self):
        payload = {"status": "REQUEST_SUCCEEDED",
                   "Results": {"series": [
                       {"seriesID": "LAUCN484270000000003", "data": [
                           {"year": "2026", "period": "M09",
                            "periodName": "September", "value": "",
                            "footnotes": []}]}]}}
        obs = laus.parse_series_payload(payload, self.meta,
                                        "2026-11-26T00:00:00Z")
        self.assertEqual(len(obs), 1)
        self.assertIsNone(obs[0]["value"])
        self.assertEqual(obs[0]["label"], "REPORTED")

    def test_unknown_series_ignored(self):
        payload = {"status": "REQUEST_SUCCEEDED",
                   "Results": {"series": [
                       {"seriesID": "LAUCN999990000000003", "data": [
                           {"year": "2026", "period": "M09",
                            "periodName": "September", "value": "1.0",
                            "footnotes": []}]}]}}
        obs = laus.parse_series_payload(payload, self.meta,
                                        "2026-11-26T00:00:00Z")
        self.assertEqual(obs, [])


class TestFetchDocumentShape(unittest.TestCase):
    def test_api_error_recorded_not_raised(self):
        doc = laus.fetch_observations(
            opener=lambda req, timeout=None: (_ for _ in ()).throw(
                RuntimeError("no network in tests")), pause=0)
        self.assertIn("0/12 series OK", doc["fetch_status"])
        self.assertIn("failures:", doc["fetch_status"])
        self.assertEqual(doc["sensor"], "bls-laus-101")
        json.dumps(doc)

    def test_fake_live_payload(self):
        # The collector posts one series at a time; the fake opener
        # answers the Starr rate series with the fixture and every
        # other series with an empty successful payload.
        def opener(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("LAUCN484270000000003"):
                return FakeResponse(json.dumps(FAKE_PAYLOAD).encode("utf-8"))
            return FakeResponse(json.dumps(
                {"status": "REQUEST_SUCCEEDED",
                 "Results": {"series": []}}).encode("utf-8"))

        doc = laus.fetch_observations(opener=opener, pause=0)
        self.assertEqual(doc["fetch_status"], "OK")
        self.assertEqual(doc["summary"]["observations_total"], 4)
        self.assertEqual(doc["summary"]["starr_latest_rate_value"], 8.3)
        self.assertEqual(doc["summary"]["starr_latest_rate_month"],
                         "2026-M09")


if __name__ == "__main__":
    unittest.main()
