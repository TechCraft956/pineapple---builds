"""Panopticon v1.1 test suite — fully offline (injected fetch / fixtures)."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panopticon import brief as brief_mod  # noqa: E402
from panopticon import planner  # noqa: E402
from panopticon.ethics import (EthicsViolation, PurposeRequiredError,  # noqa: E402
                               assert_record_clean, assert_text_clean)
from panopticon.normalize import normalize, normalize_all  # noqa: E402
from panopticon.registry import load_registry, validate_registry  # noqa: E402
from panopticon.runners import http_util  # noqa: E402
from panopticon.runners import place as place_runner  # noqa: E402
from panopticon.runners import stubs  # noqa: E402
from panopticon.runners import username as username_runner  # noqa: E402

_spec = importlib.util.spec_from_file_location("panopticon_cli", ROOT / "panopticon.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

FIXTURE = ROOT / "tests" / "fixtures" / "nominatim_roma.json"
PURPOSE = "user-owned account audit (v1.1 test)"

GH_BODY = ("<html><head><title>alice (Alice Liddell) · GitHub</title></head>"
           "<body>profile</body></html>")
HN_BODY = ("<html><head><title>Profile: ghost | Hacker News</title></head>"
           "<body>user: ghost</body></html>")


def fake_fetch(mapping):
    def _fetch(url, user_agent=None):
        for key, val in mapping.items():
            if key in url:
                return val
        return (None, "")
    return _fetch


class FakeClock:
    """Monotonic clock + sleep that advances it (no real waiting)."""

    def __init__(self):
        self.t = 1000.0
        self.slept = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.slept += s
        self.t += s


def _mk_finding(subject, detail, source_id, url, verification="VERIFIED",
                confidence=0.9):
    return {
        "subject": subject, "subject_type": "place",
        "claim": "synthetic %s" % detail, "detail": detail,
        "verification": verification, "confidence": confidence,
        "field_confidence": {"lat": {"confidence": confidence,
                                     "retrieved_at_utc": "2026-11-18T05:00:00Z",
                                     "source_id": source_id}},
        "source_id": source_id, "source_url": url,
        "retrieved_at_utc": "2026-11-18T05:00:00Z", "method": "CODE",
    }


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load_registry()

    def test_registry_valid_and_unique(self):
        validate_registry(self.reg)
        ids = [s["id"] for s in self.reg["sources"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_catalog_categories_present(self):
        cats = {s["category"] for s in self.reg["sources"]}
        for expected in ("people_search", "username", "email", "phone",
                         "geoint", "search_documents", "technical",
                         "public_records", "archives"):
            self.assertIn(expected, cats)

    def test_excluded_entries_exist(self):
        excluded = [s for s in self.reg["sources"] if s["ethics"]["excluded"]]
        self.assertGreaterEqual(len(excluded), 2)


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load_registry()

    def test_excluded_never_planned_any_type(self):
        for stype in ("username", "person", "place", "organization", "email", "phone"):
            steps = planner.plan(stype, "x", self.reg, purpose="due diligence")
            ids = {s["source_id"] for s in steps}
            self.assertNotIn("grey_identity_generators", ids)
            self.assertNotIn("grey_shadow_libraries", ids)

    def test_username_plan_runner_first(self):
        steps = planner.plan("username", "someone", self.reg, purpose=PURPOSE)
        self.assertTrue(steps[0]["runnable"])
        self.assertEqual(steps[0]["source_id"], "runner:username_presence")

    def test_place_plan_has_geocode_runner(self):
        steps = planner.plan("place", "Roma, Texas", self.reg)
        self.assertIn("runner:place_geocode", {s["source_id"] for s in steps})

    def test_purpose_required_absent_without_purpose(self):
        steps = planner.plan("person", "Jane Public", self.reg)
        self.assertNotIn("truepeoplesearch", {s["source_id"] for s in steps})
        sk = planner.skipped(self.reg, "person")
        self.assertIn("truepeoplesearch", {s["source_id"] for s in sk})

    def test_purpose_required_browser_only_with_purpose(self):
        steps = planner.plan("person", "Jane Public", self.reg,
                             purpose="due diligence before contracting")
        tp = [s for s in steps if s["source_id"] == "truepeoplesearch"]
        self.assertEqual(len(tp), 1)
        self.assertEqual(tp[0]["method"], "BROWSER")
        self.assertFalse(tp[0]["runnable"])

    def test_no_code_step_for_purpose_required_email(self):
        steps = planner.plan("email", "a@b.example", self.reg,
                             purpose="owner-controlled address check")
        self.assertNotIn("emailrep", {s["source_id"] for s in steps})
        sk = planner.skipped(self.reg, "email", purpose="x")
        self.assertIn("emailrep", {s["source_id"] for s in sk})


class PurposeTests(unittest.TestCase):
    """Gate 1 (acceptance test 7): username plans need a purpose."""

    @classmethod
    def setUpClass(cls):
        cls.reg = load_registry()

    def test_username_plan_refused_without_purpose(self):
        with self.assertRaises(PurposeRequiredError) as cm:
            planner.plan("username", "someone", self.reg)
        self.assertIn("purpose", str(cm.exception).lower())

    def test_username_plan_allowed_with_purpose(self):
        steps = planner.plan("username", "someone", self.reg, purpose=PURPOSE)
        self.assertIn("runner:username_presence", {s["source_id"] for s in steps})

    def test_username_runner_refuses_without_purpose(self):
        with self.assertRaises(PurposeRequiredError):
            username_runner.run("alice", fetch=fake_fetch({"github": (200, GH_BODY)}))

    def test_cli_plan_refuses_without_purpose(self):
        self.assertEqual(cli.main(["plan", "username", "someone"]), 2)

    def test_cli_plan_accepts_with_purpose(self):
        self.assertEqual(
            cli.main(["plan", "username", "someone", "--purpose", PURPOSE]), 0)

    def test_cli_username_refuses_without_purpose(self):
        self.assertEqual(cli.main(["username", "alice"]), 2)


class UsernameRunnerTests(unittest.TestCase):
    def test_found_with_confirming_marker(self):
        f = username_runner.run("alice", fetch=fake_fetch({"github": (200, GH_BODY)}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "FOUND")
        self.assertEqual(f[0]["verification"], "VERIFIED")
        self.assertGreaterEqual(f[0]["confidence"], 0.8)

    def test_bare_200_is_candidate_not_found(self):
        f = username_runner.run("alice", fetch=fake_fetch({"github": (200, "ok")}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "CANDIDATE")
        self.assertEqual(f[0]["verification"], "REPORTED")

    def test_not_found(self):
        f = username_runner.run("alice", fetch=fake_fetch({"github": (404, "")}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "NOT_FOUND")
        self.assertEqual(f[0]["verification"], "VERIFIED")  # checked-and-absent is a fact

    def test_walled_is_unknown_never_guessed(self):
        for status in (403, 429, 500, None):
            f = username_runner.run("alice", fetch=fake_fetch({"github": (status, "")}),
                                    sites=[username_runner.SITES[0]], purpose=PURPOSE)
            self.assertEqual(f[0]["detail"]["result"], "UNKNOWN")
            self.assertEqual(f[0]["verification"], "UNKNOWN")

    def test_hn_absent_marker(self):
        hn = [s for s in username_runner.SITES if s[0] == "Hacker News"][0]
        f = username_runner.run("ghost", fetch=fake_fetch({"news.ycombinator": (200, "No such user.")}),
                                sites=[hn], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "NOT_FOUND")

    def test_hn_confirm_marker_is_found(self):
        hn = [s for s in username_runner.SITES if s[0] == "Hacker News"][0]
        f = username_runner.run("ghost", fetch=fake_fetch({"news.ycombinator": (200, HN_BODY)}),
                                sites=[hn], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "FOUND")

    def test_soft404_body_is_not_found(self):
        gl = [s for s in username_runner.SITES if s[0] == "GitLab"][0]
        f = username_runner.run("alice", fetch=fake_fetch({"gitlab": (200, "User not found")}),
                                sites=[gl], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "NOT_FOUND")
        self.assertEqual(f[0]["verification"], "VERIFIED")

    def test_false_identity_marker_is_not_found(self):
        # Page carries the confirming marker for a DIFFERENT username.
        f = username_runner.run("bob", fetch=fake_fetch({"github": (200, GH_BODY)}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "CANDIDATE")
        self.assertNotEqual(f[0]["verification"], "VERIFIED")

    def test_markerless_site_200_is_candidate(self):
        # Reddit returns 200 even for nonexistent users (JS challenge page);
        # a username string in a form action is not a confirming marker.
        rd = [s for s in username_runner.SITES if s[0] == "Reddit"][0]
        body = '<form hidden method="GET" action="/user/alice/"></form>'
        f = username_runner.run("alice", fetch=fake_fetch({"reddit": (200, body)}),
                                sites=[rd], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "CANDIDATE")
        self.assertEqual(f[0]["verification"], "REPORTED")

    def test_findings_carry_provenance(self):
        f = username_runner.run("alice", fetch=fake_fetch({"github": (200, GH_BODY)}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)[0]
        for key in ("source_url", "retrieved_at_utc", "method", "source_id", "confidence"):
            self.assertIn(key, f)
        self.assertIn("presence", f["field_confidence"])
        self.assertEqual(f["detail"]["http_status"], 200)

    def test_http_status_recorded_on_unknown(self):
        f = username_runner.run("alice", fetch=fake_fetch({"github": (429, "")}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)[0]
        self.assertEqual(f["detail"]["http_status"], 429)

    def test_injection_subject_rejected(self):
        for bad in ("a/b", "a?b=c", "a#b", "a b", "../x", "a%2F", "", "a'b", "a\"b"):
            with self.assertRaises(ValueError, msg=bad):
                username_runner.run(bad, fetch=fake_fetch({}), purpose=PURPOSE)
        # a legal username passes validation (fetch then decides)
        f = username_runner.run("john_doe-1.2", fetch=fake_fetch({"github": (404, "")}),
                                sites=[username_runner.SITES[0]], purpose=PURPOSE)
        self.assertEqual(f[0]["detail"]["result"], "NOT_FOUND")


class PlaceRunnerTests(unittest.TestCase):
    def setUp(self):
        place_runner.clear_cache()
        place_runner._CACHE_LOADED = False
        # Every test below passes its own cache dict, so the real on-disk
        # cache is never read or written by the suite (except the one
        # disk round-trip test, which points _CACHE_PATH at a temp dir).
        self.cache = {}

    def test_fixture_parses(self):
        payload = json.loads(FIXTURE.read_text())
        url = place_runner.build_url("Roma, Texas")
        findings = place_runner.parse_results("Roma, Texas", payload, url)
        self.assertEqual(findings[0]["detail"]["result"], "FOUND")
        self.assertEqual(findings[0]["detail"]["lat"], "26.4052451")
        self.assertEqual(findings[0]["verification"], "VERIFIED")
        self.assertIn("OpenStreetMap", findings[0]["detail"]["attribution"])

    def test_empty_payload_is_unknown_not_invented(self):
        findings = place_runner.parse_results("Nowhere", [], "http://x")
        self.assertEqual(findings[0]["verification"], "UNKNOWN")

    def test_http_error_is_unknown(self):
        findings = place_runner.run("Roma", fetch=fake_fetch({"nominatim": (503, "")}),
                                    cache=self.cache)
        self.assertEqual(findings[0]["verification"], "UNKNOWN")

    def test_identifiable_user_agent_with_contact(self):
        ua = place_runner.NOMINATIM_USER_AGENT
        self.assertIn("Panopticon", ua)
        self.assertIn("github.com/TechCraft956", ua)
        seen = []
        payload = json.loads(FIXTURE.read_text())

        def cap(url, user_agent=None):
            seen.append(user_agent)
            return (200, json.dumps(payload))
        place_runner.run("Roma, Texas", fetch=cap, cache=self.cache)
        self.assertEqual(seen, [ua])

    def test_global_throttle_enforced(self):
        clock = FakeClock()
        payload = json.loads(FIXTURE.read_text())
        fetch = fake_fetch({"nominatim": (200, json.dumps(payload))})
        place_runner.run("Roma, Texas", fetch=fetch, cache=self.cache,
                         clock=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(clock.slept, 0.0)  # first request: nothing to wait for
        place_runner.run("Laredo, Texas", fetch=fetch, cache=self.cache,
                         clock=clock.monotonic, sleep=clock.sleep)
        self.assertGreaterEqual(clock.slept, 1.0)  # second request waited >=1s

    def test_repeated_identical_query_hits_cache(self):
        clock = FakeClock()
        payload = json.loads(FIXTURE.read_text())
        calls = []

        def counting(url, user_agent=None):
            calls.append(url)
            return (200, json.dumps(payload))
        kw = dict(cache=self.cache, clock=clock.monotonic, sleep=clock.sleep)
        first = place_runner.run("Roma, Texas", fetch=counting, **kw)
        second = place_runner.run("Roma, Texas", fetch=counting, **kw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first[0]["detail"]["lat"], second[0]["detail"]["lat"])
        self.assertTrue(second[0]["detail"]["from_cache"])
        self.assertEqual(clock.slept, 0.0)  # cache hit makes no request, no throttle

    def test_cache_key_is_case_insensitive(self):
        payload = json.loads(FIXTURE.read_text())
        calls = []

        def counting(url, user_agent=None):
            calls.append(url)
            return (200, json.dumps(payload))
        place_runner.run("Roma, Texas", fetch=counting, cache=self.cache)
        place_runner.run("roma, texas", fetch=counting, cache=self.cache)
        self.assertEqual(len(calls), 1)


    def test_disk_cache_round_trip(self):
        import tempfile
        payload = json.loads(FIXTURE.read_text())
        calls = []

        def counting(url, user_agent=None):
            calls.append(url)
            return (200, json.dumps(payload))
        with tempfile.TemporaryDirectory() as td:
            place_runner._CACHE_PATH = Path(td) / "cache.json"
            place_runner._CACHE_LOADED = False
            place_runner.clear_cache()
            first = place_runner.run("Roma, Texas", fetch=counting)
            self.assertEqual(len(calls), 1)
            self.assertTrue(place_runner._CACHE_PATH.exists())
            # Fresh in-memory state, same disk: the second run must not fetch.
            place_runner._CACHE.clear()
            place_runner._CACHE_LOADED = False
            second = place_runner.run("Roma, Texas", fetch=counting)
            self.assertEqual(len(calls), 1)
            self.assertTrue(second[0]["detail"]["from_cache"])
            self.assertEqual(first[0]["detail"]["lat"],
                             second[0]["detail"]["lat"])
            place_runner._CACHE_PATH = (Path(place_runner.__file__).resolve()
                                        .parent.parent.parent
                                        / ".cache" / "nominatim_cache.json")


class RedirectTests(unittest.TestCase):
    """Gate 4: redirect/host validation + SSRF guard (offline)."""

    def test_private_targets_refused(self):
        for url in ("http://127.0.0.1/x", "http://localhost/x",
                    "http://10.0.0.5/x", "http://192.168.1.1/x",
                    "http://169.254.1.1/x", "http://[::1]/x",
                    "http://0.0.0.0/x"):
            with self.assertRaises(http_util.RedirectRejected, msg=url):
                http_util.validate_fetch_url(url)

    def test_credentials_and_scheme_refused(self):
        for url in ("http://user:pass@github.com/x", "ftp://github.com/x",
                    "file:///etc/passwd"):
            with self.assertRaises(http_util.RedirectRejected, msg=url):
                http_util.validate_fetch_url(url)

    def test_public_url_accepted(self):
        http_util.validate_fetch_url("https://github.com/torvalds")

    def test_cross_host_redirect_rejected(self):
        import urllib.request
        h = http_util.ValidatingRedirectHandler()
        req = urllib.request.Request("https://github.com/torvalds")
        with self.assertRaises(http_util.RedirectRejected):
            h.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x")

    def test_private_ip_redirect_rejected(self):
        import urllib.request
        h = http_util.ValidatingRedirectHandler()
        req = urllib.request.Request("https://github.com/torvalds")
        with self.assertRaises(http_util.RedirectRejected):
            h.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/x")

    def test_same_host_redirect_allowed(self):
        import urllib.request
        h = http_util.ValidatingRedirectHandler()
        req = urllib.request.Request("https://github.com/torvalds")
        new = h.redirect_request(req, None, 302, "Found", {},
                                 "https://github.com/torvalds/")
        self.assertEqual(new.full_url, "https://github.com/torvalds/")

    def test_validating_handler_is_only_redirect_handler(self):
        op = http_util.build_opener()
        chain = op.handle_error["http"][302]
        self.assertEqual(len(chain), 1)
        self.assertIsInstance(chain[0], http_util.ValidatingRedirectHandler)

    def test_http_fetch_refuses_private_ip_without_network(self):
        with self.assertRaises(http_util.RedirectRejected):
            http_util.http_fetch("http://127.0.0.1/nope")


class NormalizeTests(unittest.TestCase):
    def _finding(self):
        return username_runner.run("alice", fetch=fake_fetch({"github": (200, GH_BODY)}),
                                   sites=[username_runner.SITES[0]],
                                   purpose=PURPOSE)[0]

    def test_feed_shape_and_provenance(self):
        item = normalize(self._finding())
        for key in ("title", "category", "source", "action", "est_value",
                    "risk", "location", "url", "confidence"):
            self.assertIn(key, item)
        for key in ("source_url", "retrieved_at_utc", "method", "verification"):
            self.assertIn(key, item["provenance"])
        self.assertIsNone(item["est_value"])

    def test_per_field_confidence_passes_through(self):
        item = normalize(self._finding())
        self.assertIn("presence", item["field_confidence"])
        fc = item["field_confidence"]["presence"]
        self.assertGreaterEqual(fc["confidence"], 0.8)
        self.assertIn("retrieved_at_utc", fc)

    def test_ethics_gate_rejects_pii_field(self):
        bad = {"title": "x", "detail": {"ssn": "000-00-0000"}}
        with self.assertRaises(EthicsViolation):
            assert_record_clean(bad)

    def test_ethics_gate_rejects_nested_pii(self):
        with self.assertRaises(EthicsViolation):
            assert_record_clean({"a": {"b": {"ssn": "000-00-0000"}}})
        with self.assertRaises(EthicsViolation):
            assert_record_clean({"records": [{"dob": "1990-01-01"}]})
        with self.assertRaises(EthicsViolation):
            assert_record_clean([{"outer": [{"personal_email": "a@b.c"}]}])

    def test_ethics_gate_accepts_clean(self):
        assert_record_clean(normalize(self._finding()))

    def test_output_text_gate(self):
        assert_text_clean("clean brief text, no labels here")
        with self.assertRaises(EthicsViolation):
            assert_text_clean("leaked field — ssn: 000-00-0000")


class BriefTests(unittest.TestCase):
    def _items(self):
        found = username_runner.run("alice", fetch=fake_fetch({"github": (200, GH_BODY)}),
                                    sites=[username_runner.SITES[0]], purpose=PURPOSE)
        walled = username_runner.run("alice", fetch=fake_fetch({"gitlab": (403, "")}),
                                     sites=[username_runner.SITES[1]], purpose=PURPOSE)
        return normalize_all(found + walled)

    def test_sections_and_separation(self):
        reg = load_registry()
        steps = planner.plan("username", "alice", reg, purpose=PURPOSE)
        text = brief_mod.render("alice", "username", self._items(), steps,
                                planner.skipped(reg, "username", purpose=PURPOSE))
        self.assertIn("## Verified", text)
        self.assertIn("## Reported (unconfirmed)", text)
        self.assertIn("## Unknown / gaps", text)
        # the walled GitLab check lands under Unknown, the GitHub hit under Verified
        self.assertLess(text.index("Profile page exists"), text.index("## Unknown"))
        self.assertGreater(text.index("could not be determined"), text.index("## Unknown"))

    def test_not_found_reported_as_fact_not_gap(self):
        nf = username_runner.run("alice", fetch=fake_fetch({"github": (404, "")}),
                                 sites=[username_runner.SITES[0]], purpose=PURPOSE)
        text = brief_mod.render("alice", "username", normalize_all(nf))
        self.assertLess(text.index("checked, absent"), text.index("## Unknown"))

    def test_candidate_lands_in_reported(self):
        cand = username_runner.run("alice", fetch=fake_fetch({"github": (200, "ok")}),
                                   sites=[username_runner.SITES[0]], purpose=PURPOSE)
        text = brief_mod.render("alice", "username", normalize_all(cand))
        self.assertLess(text.index("unconfirmed"), text.index("## Unknown"))
        self.assertIn("1 reported", text)

    def test_conflict_recorded_not_silently_picked(self):
        a = normalize(_mk_finding("Roma, Texas",
                                  {"result": "FOUND", "lat": "26.4052451",
                                   "lon": "-99.0240000"},
                                  "runner:place_geocode",
                                  "https://nominatim.openstreetmap.org/search?q=Roma"))
        b = normalize(_mk_finding("Roma, Texas",
                                  {"result": "FOUND", "lat": "26.5000000",
                                   "lon": "-99.0240000"},
                                  "runner:place_geocode_v2",
                                  "https://other-geocoder.example/search?q=Roma"))
        text = brief_mod.render("Roma, Texas", "place", [a, b])
        self.assertIn("## Conflicts between sources", text)
        self.assertIn("26.4052451", text)
        self.assertIn("26.5000000", text)
        self.assertIn("no value chosen", text)

    def test_same_source_alternatives_are_not_conflicts(self):
        a = normalize(_mk_finding("Roma, Texas",
                                  {"result": "FOUND", "lat": "26.4052451"},
                                  "runner:place_geocode", "https://nominatim.example/1"))
        b = normalize(_mk_finding("Roma, Texas",
                                  {"result": "FOUND", "lat": "26.5000000"},
                                  "runner:place_geocode", "https://nominatim.example/2"))
        text = brief_mod.render("Roma, Texas", "place", [a, b])
        self.assertNotIn("## Conflicts between sources", text)

    def test_all_unknown_brief_is_honest(self):
        walled = username_runner.run("alice", fetch=fake_fetch({"github": (403, "")}),
                                     sites=[username_runner.SITES[0]], purpose=PURPOSE)
        items = normalize_all(walled)
        text = brief_mod.render("alice", "username", items)
        self.assertIn("0 verified", text)
        verified_section = text.split("## Verified")[1].split("## Reported")[0]
        self.assertIn("(none)", verified_section)
        self.assertNotIn("Profile page exists", text)

    def test_brief_carries_fcra_notice(self):
        text = brief_mod.render("alice", "username", self._items())
        self.assertIn("Not a consumer report", text)
        self.assertIn("FCRA", text)

    def test_brief_regates_smuggled_pii(self):
        # A findings file that bypassed normalize must not leak PII into output.
        bad_item = {
            "title": "x", "category": "intelligence", "source": "panopticon:evil",
            "action": "review", "est_value": None, "risk": "MED",
            "location": None, "url": "https://example.com", "confidence": 0.5,
            "provenance": {"source_url": "https://example.com",
                           "retrieved_at_utc": "2026-11-18T05:00:00Z",
                           "method": "CODE", "verification": "VERIFIED",
                           "source_id": "evil"},
            "subject": "alice", "subject_type": "username",
            "detail": {"records": [{"dob": "1990-01-01"}]},
        }
        with self.assertRaises(EthicsViolation):
            brief_mod.render("alice", "username", [bad_item])


class ExcludedNeverRunTests(unittest.TestCase):
    def test_excluded_never_planned_or_runnable(self):
        reg = load_registry()
        excluded = {s["id"] for s in reg["sources"] if s["ethics"]["excluded"]}
        self.assertGreaterEqual(len(excluded), 2)
        for stype in ("username", "person", "place", "organization", "email", "phone"):
            steps = planner.plan(stype, "x", reg, purpose="due diligence")
            planned = {s["source_id"] for s in steps}
            self.assertFalse(planned & excluded)
            self.assertFalse(any(s["runnable"] and s["source_id"] in excluded
                                 for s in steps))
            sk = planner.skipped(reg, stype, purpose="due diligence")
            for eid in excluded:
                self.assertIn(eid, {s["source_id"] for s in sk})


class StubTests(unittest.TestCase):
    def test_stubs_raise_not_wired(self):
        for fn in (stubs.wayback_lookup, stubs.email_lookup,
                   stubs.public_records_lookup):
            with self.assertRaises(stubs.NotWired):
                fn("x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
