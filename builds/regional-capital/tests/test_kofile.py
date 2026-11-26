"""Tests for sensor #81 (KoFile Starr County deeds, liens & DBAs) — stdlib unittest.

Fixture-based; no network is touched by these tests.

- kofile_quicklink_landing.html: TRIMMED REAL CAPTURE of
  https://kofilequicklinks.com/StarrTX/Default.aspx (HTTP 200, 25,900
  bytes, 2026-11-26 ~19:00 UTC). The only change from the raw capture is
  none — it is the full page as fetched.
- kofile_quicklink_results_sample.html: SYNTHETIC results page (header
  comment says so). No real search has completed from here, so no real
  results page exists; names/book/pages/dates in it are invented.
- kofile_modern_portal_landing.html / kofile_search_host_landing.html:
  RECONSTRUCTED from rendered page text observed via text fetch
  2026-11-26 (direct requests fail from here: HTTP 403 / connection
  closed). They exercise the certified-through parser only.
"""
import json
import os
import sys
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import kofile  # noqa: E402

RETRIEVED = "2026-11-26T19:15:00Z"


def load_fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return fh.read()


def http_error(url, code, body=b""):
    import io
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


class TestQuicklinkLandingParsing(unittest.TestCase):
    def setUp(self):
        self.html = load_fixture("kofile_quicklink_landing.html")
        self.landing = kofile.parse_quicklink_landing(self.html, RETRIEVED)

    def test_landing_is_verified_starr_quicklink(self):
        self.assertEqual(self.landing["status"], "VERIFIED")
        self.assertIn("QuickLink", self.landing["title"])
        self.assertIn("Starr", self.landing["title"])
        self.assertEqual(self.landing["source_url"], kofile.QUICKLINK_URL)

    def test_coverage_claimed_1848_to_1984(self):
        self.assertEqual(self.landing["coverage_claimed"], "1848-1984")
        self.assertEqual(self.landing["clerk"], "Humberto Gonzalez")

    def test_index_book_types_parsed_not_assumed(self):
        self.assertEqual(self.landing["index_book_types"],
                         ["Deed of Trust", "Deeds"])

    def test_year_ranges_parsed_exactly(self):
        self.assertEqual(self.landing["year_ranges"],
                         ["1884-1926", "1926-1971", "1971-1979", "1979-1984"])

    def test_cascading_dropdowns_empty_on_landing(self):
        # Parties / Last / First name are populated only by postbacks.
        self.assertEqual(self.landing["parties_option_count"], 0)
        self.assertEqual(self.landing["last_name_option_count"], 0)
        self.assertEqual(self.landing["first_name_option_count"], 0)

    def test_every_observation_has_source_and_timestamp(self):
        self.assertEqual(self.landing["retrieved_at_utc"], RETRIEVED)
        self.assertTrue(self.landing["source_url"].startswith("https://"))
        self.assertIn(self.landing["status"], kofile.ALLOWED_STATUSES)

    def test_unrecognised_page_is_unknown(self):
        landing = kofile.parse_quicklink_landing(
            "<html><head><title>Something else</title></head></html>",
            RETRIEVED)
        self.assertEqual(landing["status"], "UNKNOWN")
        self.assertIsNone(landing["coverage_claimed"])
        self.assertEqual(landing["index_book_types"], [])
        self.assertIsNotNone(landing["note"])


class TestHiddenFieldsAndPostback(unittest.TestCase):
    def setUp(self):
        self.html = load_fixture("kofile_quicklink_landing.html")
        self.hidden = kofile.extract_hidden_fields(self.html)

    def test_viewstate_present_and_nonempty(self):
        self.assertIn("__VIEWSTATE", self.hidden)
        self.assertTrue(len(self.hidden["__VIEWSTATE"]) > 100)
        self.assertIn("__EVENTVALIDATION", self.hidden)
        self.assertIn("__VIEWSTATEGENERATOR", self.hidden)

    def test_postback_form_sets_eventtarget_and_value(self):
        target = ("ctl00$ctl00$ImageContent$MainContent$"
                  "SearchIndexBookSection$ddlIndexBookType")
        form = kofile.build_postback_form(
            self.hidden, target, {target: "Deeds"})
        self.assertEqual(form["__EVENTTARGET"], target)
        self.assertEqual(form["__EVENTARGUMENT"], "")
        self.assertEqual(form[target], "Deeds")
        self.assertEqual(form["__VIEWSTATE"], self.hidden["__VIEWSTATE"])

    def test_select_options_include_selected_flag(self):
        opts = kofile.parse_select_options(self.html, "ddlIndexBookType")
        self.assertEqual([o["value"] for o in opts],
                         ["", "Deed of Trust", "Deeds"])
        selected = [o for o in opts if o["selected"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["value"], "Deed of Trust")

    def test_missing_select_returns_empty_list(self):
        self.assertEqual(kofile.parse_select_options(self.html, "ddlNope"), [])


class TestQuicklinkResultsParsing(unittest.TestCase):
    def test_synthetic_results_fixture_parses_three_rows(self):
        html = load_fixture("kofile_quicklink_results_sample.html")
        parsed = kofile.parse_quicklink_results(
            html, RETRIEVED,
            query={"index_book_type": "Deeds", "year_range": "1884-1926"})
        self.assertTrue(parsed["results_table_found"])
        self.assertEqual(parsed["result_count"], 3)
        self.assertEqual(parsed["status"], "REPORTED")  # never VERIFIED
        first = parsed["results"][0]
        self.assertEqual(first["cells"][0], "EXAMPLE GRANTOR")
        self.assertEqual(first["cells"][2], "Deed")
        self.assertEqual(first["cells"][3], "Vol 12 Pg 345")
        self.assertEqual(first["status"], "REPORTED")
        self.assertIn("positional", first["note"])

    def test_no_results_message_gives_zero_rows(self):
        html = ("<html><body><p>No records found for the search "
                "criteria.</p></body></html>")
        parsed = kofile.parse_quicklink_results(html, RETRIEVED)
        self.assertFalse(parsed["results_table_found"])
        self.assertTrue(parsed["no_results_message"])
        self.assertEqual(parsed["result_count"], 0)

    def test_page_with_no_table_gives_zero_rows_not_error(self):
        parsed = kofile.parse_quicklink_results(
            "<html><body><p>Welcome</p></body></html>", RETRIEVED)
        self.assertEqual(parsed["result_count"], 0)
        self.assertEqual(parsed["status"], "UNKNOWN")


class TestModernPortalParsing(unittest.TestCase):
    def test_publicsearch_landing_parses_certified_date(self):
        html = load_fixture("kofile_modern_portal_landing.html")
        parsed = kofile.parse_modern_portal_landing(
            html, RETRIEVED, kofile.MODERN_PORTAL_URL)
        self.assertEqual(parsed["status"], "VERIFIED")
        self.assertEqual(parsed["certified_through"], "11/20/2026")
        self.assertIsNotNone(parsed["search_hint"])

    def test_search_host_landing_parses_older_certified_date(self):
        # Rendered text for starrtx.search.kofile.com has no "Official
        # Records Search" heading, so it parses as UNKNOWN — but the
        # certified-through date is still extracted.
        html = load_fixture("kofile_search_host_landing.html")
        parsed = kofile.parse_modern_portal_landing(
            html, RETRIEVED, kofile.SEARCH_HOST_URL)
        self.assertEqual(parsed["certified_through"], "04/18/2025")
        self.assertEqual(parsed["status"], "UNKNOWN")

    def test_missing_certified_date_stays_none(self):
        parsed = kofile.parse_modern_portal_landing(
            "<html><body><h2>Official Records Search</h2><p>Starr</p>"
            "</body></html>", RETRIEVED, kofile.MODERN_PORTAL_URL)
        self.assertIsNone(parsed["certified_through"])
        self.assertEqual(parsed["status"], "VERIFIED")


class TestFetchLegs(unittest.TestCase):
    def test_quicklink_landing_fetch_verified(self):
        body = load_fixture("kofile_quicklink_landing.html").encode("utf-8")

        def fetcher(url, data, timeout):
            self.assertEqual(url, kofile.QUICKLINK_URL)
            self.assertIsNone(data)  # landing is a GET
            return body

        leg = kofile.fetch_quicklink_landing(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "VERIFIED")
        self.assertEqual(leg["http_status"], 200)
        self.assertEqual(leg["bytes"], len(body))
        self.assertEqual(leg["landing"]["coverage_claimed"], "1848-1984")

    def test_quicklink_403_is_unknown_with_status(self):
        def fetcher(url, data, timeout):
            raise http_error(url, 403, b"Forbidden")

        leg = kofile.fetch_quicklink_landing(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertEqual(leg["http_status"], 403)
        self.assertIn("403", leg["error"])
        self.assertIsNone(leg["landing"])

    def test_quicklink_timeout_is_unknown_no_status(self):
        def fetcher(url, data, timeout):
            raise TimeoutError("The read operation timed out")

        leg = kofile.fetch_quicklink_landing(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertIsNone(leg["http_status"])
        self.assertIn("TimeoutError", leg["error"])

    def test_modern_portal_403_and_search_host_disconnect(self):
        def fetcher(url, data, timeout):
            if "publicsearch.us" in url:
                raise http_error(url, 403, b"Forbidden")
            raise ConnectionResetError("Remote end closed connection "
                                      "without response")

        leg = kofile.fetch_modern_portal(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertEqual(leg["http_status"], 403)
        self.assertIn("environment block", leg["error"])
        self.assertIsNone(leg["search_host"]["http_status"])
        self.assertIn("ConnectionResetError",
                      leg["search_host"]["error"])

    def test_modern_portal_success_path(self):
        body = load_fixture("kofile_modern_portal_landing.html").encode("utf-8")
        host_body = load_fixture(
            "kofile_search_host_landing.html").encode("utf-8")

        def fetcher(url, data, timeout):
            if "search.kofile.com" in url:
                return host_body
            return body

        leg = kofile.fetch_modern_portal(RETRIEVED, fetcher=fetcher)
        self.assertEqual(leg["status"], "VERIFIED")
        self.assertEqual(leg["landing"]["certified_through"], "11/20/2026")
        self.assertEqual(leg["search_host"]["http_status"], 200)


class TestStaticLegs(unittest.TestCase):
    def test_texasfile_is_blocked_spend_with_owner_step(self):
        leg = kofile.texasfile_leg(RETRIEVED)
        self.assertEqual(leg["status"], "BLOCKED")
        self.assertEqual(leg["coverage_claimed"], "1880-2026")
        self.assertIn("texasfile.com", leg["owner_step"])
        self.assertIn("Register", leg["owner_step"])

    def test_dba_leg_is_unknown_not_zero(self):
        leg = kofile.dba_leg(RETRIEVED)
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertEqual(leg["filing_fee_reported"], "$23.00")
        self.assertIn("No online", leg["error"])


class TestSearchChain(unittest.TestCase):
    def _landing_with_options(self, parties=(), last=(), first=()):
        hidden = ('<input type="hidden" name="__VIEWSTATE" '
                  'value="vs1" /><input type="hidden" '
                  'name="__EVENTVALIDATION" value="ev1" />')
        def sel(name, options, selected=""):
            opts = "".join(
                f'<option value="{v}">{v}</option>' for v in options)
            return (f'<select name="ctl00$ctl00$ImageContent$MainContent$'
                    f'SearchIndexBookSection${name}">{opts}</select>')
        return ("<html><head><title>QuickLink - Starr County, Texas"
                "</title></head><body>" + hidden
                + sel("ddlIndexBookType", ["", "Deed of Trust", "Deeds"])
                + sel("ddlYear", ["", "1884-1926", "1926-1971"])
                + sel("ddlParties", parties)
                + sel("ddlLastName", last)
                + sel("ddlFirstName", first)
                + '<input type="submit" name="ctl00$ctl00$ImageContent$'
                'MainContent$SearchIndexBookSection$cmdSearch" '
                'value="SEARCH" /></body></html>')

    def test_chain_stops_after_year_without_a_name(self):
        landing = load_fixture("kofile_quicklink_landing.html")
        calls = []

        def fetcher(url, data, timeout):
            calls.append(data.get("__EVENTTARGET") if data else None)
            if data is None:
                return landing.encode("utf-8")
            # Year postback populates Parties.
            return self._landing_with_options(
                parties=["Grantor", "Grantee"]).encode("utf-8")

        leg = kofile.search_quicklink(RETRIEVED, fetcher=fetcher, timeout=30)
        self.assertEqual(leg["step_reached"], "year_postback")
        self.assertEqual(leg["steps"], ["landing_get", "type_postback",
                                        "year_postback"])
        self.assertEqual(leg["parties_options"], ["Grantor", "Grantee"])
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertIn("last name", leg["error"])
        self.assertIsNone(leg["result_count"])
        self.assertEqual(len(calls), 3)  # GET + 2 postbacks, no SEARCH

    def test_chain_with_name_reaches_search_and_parses_results(self):
        landing = load_fixture("kofile_quicklink_landing.html")
        results = load_fixture("kofile_quicklink_results_sample.html")

        def fetcher(url, data, timeout):
            if data is None:
                return landing.encode("utf-8")
            target = data.get("__EVENTTARGET", "")
            if "ddlLastName" in target:
                return self._landing_with_options(
                    parties=["Grantor"], last=["EXAMPLE GRANTOR"],
                    first=["JOHN"]).encode("utf-8")
            if "ddlParties" in target:
                return self._landing_with_options(
                    parties=["Grantor"],
                    last=["EXAMPLE GRANTOR"]).encode("utf-8")
            if "cmdSearch" in str(data):
                return results.encode("utf-8")
            return self._landing_with_options(
                parties=["Grantor"]).encode("utf-8")

        leg = kofile.search_quicklink(
            RETRIEVED, fetcher=fetcher, timeout=30,
            index_book_type="Deeds", year_range="1884-1926",
            parties="Grantor", last_name="EXAMPLE GRANTOR")
        self.assertEqual(leg["step_reached"], "search_click")
        self.assertEqual(leg["status"], "REPORTED")
        self.assertEqual(leg["result_count"], 3)
        self.assertEqual(len(leg["results"]["results"]), 3)

    def test_postback_timeout_records_step_and_stops(self):
        landing = load_fixture("kofile_quicklink_landing.html")

        def fetcher(url, data, timeout):
            if data is None:
                return landing.encode("utf-8")
            raise TimeoutError("The read operation timed out")

        leg = kofile.search_quicklink(RETRIEVED, fetcher=fetcher, timeout=30)
        self.assertEqual(leg["step_reached"], "type_postback_failed")
        self.assertEqual(leg["status"], "UNKNOWN")
        self.assertIn("TimeoutError", leg["error"])
        self.assertIsNone(leg["result_count"])


class TestCollectEndToEnd(unittest.TestCase):
    def test_collect_with_stubbed_fetchers(self):
        landing = load_fixture("kofile_quicklink_landing.html").encode("utf-8")
        portal = load_fixture("kofile_modern_portal_landing.html").encode("utf-8")

        def fetcher(url, data, timeout):
            if "kofilequicklinks.com" in url:
                return landing
            if "publicsearch.us" in url:
                return portal
            if "search.kofile.com" in url:
                raise http_error(url, 403, b"Forbidden")
            raise AssertionError(f"unexpected URL {url}")

        doc = kofile.collect(fetcher=fetcher)
        self.assertEqual(doc["sensor_id"], 81)
        self.assertEqual(doc["summary"]["quicklink_status"], "VERIFIED")
        self.assertEqual(doc["summary"]["quicklink_coverage_claimed"],
                         "1848-1984")
        self.assertEqual(doc["summary"]["quicklink_year_ranges"],
                         ["1884-1926", "1926-1971", "1971-1979", "1979-1984"])
        self.assertEqual(doc["summary"]["modern_portal_status"], "VERIFIED")
        self.assertEqual(doc["summary"]["modern_portal_certified_through"],
                         "11/20/2026")
        self.assertEqual(doc["summary"]["search_host_http_status"], 403)
        self.assertEqual(doc["summary"]["texasfile_status"], "BLOCKED")
        self.assertEqual(doc["summary"]["dba_status"], "UNKNOWN")
        self.assertIsNone(doc["summary"]["quicklink_search_status"])
        # Observations: landing + portal + TexasFile BLOCKED + DBA UNKNOWN.
        self.assertEqual(len(doc["observations"]), 4)
        by_metric = {o["metric"]: o for o in doc["observations"]}
        self.assertEqual(by_metric["texasfile_modern_index"]["status"],
                         "BLOCKED")
        self.assertIsNone(by_metric["texasfile_modern_index"]["value"])
        self.assertEqual(by_metric["dba_assumed_names"]["status"], "UNKNOWN")
        for obs in doc["observations"]:
            self.assertIn(obs["status"], kofile.ALLOWED_STATUSES)
            self.assertIn("source_url", obs)
            self.assertIn("retrieved_at_utc", obs)

    def test_collect_with_search_attempt_records_chain(self):
        landing = load_fixture("kofile_quicklink_landing.html").encode("utf-8")

        def fetcher(url, data, timeout):
            if data is None:
                return landing
            raise TimeoutError("The read operation timed out")

        doc = kofile.collect(fetcher=fetcher, attempt_search=True)
        self.assertEqual(doc["summary"]["quicklink_search_status"], "UNKNOWN")
        self.assertEqual(doc["summary"]["quicklink_search_step_reached"],
                         "type_postback_failed")
        search_obs = [o for o in doc["observations"]
                      if o["metric"] == "quicklink_search"]
        self.assertEqual(len(search_obs), 1)
        self.assertIsNone(search_obs[0]["value"])


if __name__ == "__main__":
    unittest.main()
