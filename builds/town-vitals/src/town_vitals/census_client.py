"""Stdlib-only client for the US Census Bureau ACS 5-year API.

Primary endpoint (per build brief):
    https://api.census.gov/data/<vintage>/acs/acs5

IMPORTANT API BEHAVIOUR CHANGE (found at build time, 2026-11-17):
    As of 2026-05-12 the Census Bureau requires a free API key for ALL
    data queries. A keyless data query is answered with a 302 redirect
    to https://api.census.gov/data/missing_key.html and returns no data.
    The brief assumed keyless access; that is no longer true for the
    data endpoint. This client therefore:
      * reads an optional key from the CENSUS_API_KEY environment
        variable (never hard-coded, never written to provenance/cache),
      * detects the missing-key redirect and raises
        CensusKeyRequiredError loudly instead of returning zeros.
    The variables/metadata endpoint still answered keyless at build
    time, so variable verification works without a key.
    A keyless live path over the *same* ACS tables is provided by
    table_api.py (Census Bureau's own data.census.gov table access).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone

API_BASE = "https://api.census.gov/data"
USER_AGENT = "TownVitals/1.0 (Pineapple research; python-urllib)"
KEY_SIGNUP_URL = "https://api.census.gov/data/key_signup.html"

# Census ACS negative sentinels: values the API uses for
# suppressed / not-available / not-applicable estimates. They must
# become null, never a number. (e.g. -666666666)
SENTINELS = {
    -111111111, -222222222, -333333333, -555555555,
    -666666666, -888888888, -999999999,
}

# Variable map for the vitals contract. Every id here was verified
# against the API's own variables endpoint for vintage 2024 at build
# time (see BUILD_REPORT.md); verify_variables() re-checks at runtime.
VARIABLES = {
    "population": "B01003_001E",
    "median_household_income": "B19013_001E",
    "median_age": "B01002_001E",
    "poverty_below": "B17001_002E",
    "poverty_universe": "B17001_001E",
    "unemployed": "B23025_005E",
    "civilian_labor_force": "B23025_003E",
    "tenure_total": "B25003_001E",
    "owner_occupied": "B25003_002E",
    "median_home_value": "B25077_001E",
    "comp_total": "B03002_001E",
    "hispanic_or_latino": "B03002_012E",
    "white_alone_nh": "B03002_003E",        # white alone, not Hispanic
    "white_alone_h": "B03002_013E",         # white alone, Hispanic
    "black_alone_nh": "B03002_004E",        # black alone, not Hispanic
    "black_alone_h": "B03002_014E",         # black alone, Hispanic
}
ALL_VARIABLE_IDS = sorted(set(VARIABLES.values()))


class CensusError(Exception):
    pass


class CensusKeyRequiredError(CensusError):
    """Raised when the API redirects a keyless data query to missing_key."""


class VariableVerificationError(CensusError):
    """Raised when a variable id is absent from the vintage's variables list."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_value(raw):
    """Parse one ACS estimate value.

    Returns int/float, or None for missing values and negative
    sentinels (suppressed estimates). Never returns a sentinel as a
    number, and never coerces missing to 0.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        num = raw
    else:
        text = str(raw).strip()
        if text in ("", "null", "None", "-", "(X)", "N"):
            return None
        try:
            num = float(text)
        except ValueError:
            return None
    if isinstance(num, float) and num.is_integer():
        num = int(num)
    if isinstance(num, int) and (num in SENTINELS or num <= -111111111):
        return None
    if num < 0:
        # No contract variable can legitimately be negative; any other
        # negative is a sentinel variant, not data.
        return None
    return num


def _default_fetch(url: str):
    """Fetch URL, return (final_url, body_text). Follows redirects."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.geturl(), resp.read().decode("utf-8", errors="replace")


class CensusClient:
    """Client for api.census.gov ACS 5-year data + metadata."""

    def __init__(self, api_key=None, cache_dir=None, fetch=None):
        # Key is optional; when present it is used for data queries but
        # redacted from every stored provenance URL / cache record.
        self.api_key = api_key if api_key is not None else os.environ.get("CENSUS_API_KEY")
        self.cache_dir = cache_dir
        self._fetch = fetch or _default_fetch

    # -- metadata ----------------------------------------------------
    def variables_url(self, vintage: int) -> str:
        return f"{API_BASE}/{vintage}/acs/acs5/variables.json"

    def verify_variables(self, vintage: int, variable_ids=None) -> dict:
        """Verify every variable id against the API's variables endpoint.

        Returns {variable_id: label}. Raises VariableVerificationError
        listing any id the vintage does not define — a wrong id fails
        loudly, never silently zero.
        """
        variable_ids = variable_ids or ALL_VARIABLE_IDS
        _, body = self._fetch(self.variables_url(vintage))
        try:
            catalog = json.loads(body)["variables"]
        except (ValueError, KeyError) as exc:
            raise CensusError(f"variables endpoint for {vintage} did not return JSON: {exc}")
        labels, missing = {}, []
        for vid in variable_ids:
            if vid in catalog:
                labels[vid] = catalog[vid].get("label", "")
            else:
                missing.append(vid)
        if missing:
            raise VariableVerificationError(
                f"variable id(s) not defined for ACS {vintage}: {', '.join(sorted(missing))}"
            )
        return labels

    # -- data --------------------------------------------------------
    def build_query_url(self, vintage: int, variable_ids, state_fips: str,
                        place_fips: str, include_key: bool = False) -> str:
        get = ",".join(["NAME"] + list(variable_ids))
        url = (f"{API_BASE}/{vintage}/acs/acs5?get={get}"
               f"&for=place:{place_fips}&in=state:{state_fips}")
        if include_key and self.api_key:
            url += f"&key={self.api_key}"
        return url

    def _check_key_redirect(self, final_url: str, body: str, query_url: str):
        if "missing_key" in (final_url or "") or body.lstrip().startswith("<"):
            raise CensusKeyRequiredError(
                "Census API data queries require a free API key since 2026-05-12; "
                f"keyless query was redirected to missing_key.html: {query_url} "
                f"Get a key at {KEY_SIGNUP_URL} and set CENSUS_API_KEY, or use "
                "the keyless table_api provider (same ACS tables)."
            )

    def fetch_place(self, vintage: int, state_fips: str, place_fips: str,
                    variable_ids=None):
        """Fetch raw estimates for one place. Returns (values, provenance).

        values: {variable_id: int/float/None} with sentinels -> None.
        provenance: {source_url, retrieved_at_utc, api_query} with the
        API key (if any) redacted.
        """
        variable_ids = variable_ids or ALL_VARIABLE_IDS
        public_url = self.build_query_url(vintage, variable_ids, state_fips, place_fips)
        final_url, body = self._fetch(
            self.build_query_url(vintage, variable_ids, state_fips, place_fips,
                                 include_key=True))
        self._check_key_redirect(final_url, body, public_url)
        try:
            rows = json.loads(body)
        except ValueError as exc:
            raise CensusError(f"ACS {vintage} query did not return JSON: {exc}")
        if not isinstance(rows, list) or len(rows) < 2:
            raise CensusError(f"ACS {vintage} query returned no rows for "
                              f"state {state_fips} place {place_fips}")
        header, data = rows[0], rows[1]
        raw = dict(zip(header, data))
        values = {vid: parse_value(raw.get(vid)) for vid in variable_ids}
        provenance = {
            "source_url": public_url,
            "retrieved_at_utc": utc_now_iso(),
            "api_query": public_url,
            "vintage": vintage,
        }
        self._cache(public_url, body, provenance)
        return values, provenance

    def fetch_place_list(self, vintage: int, state_fips: str):
        """All places in a state from the API's own geography list.

        Returns [{name, state_fips, place_fips}]. Subject to the same
        key requirement as other data queries.
        """
        public_url = (f"{API_BASE}/{vintage}/acs/acs5?get=NAME"
                      f"&for=place:*&in=state:{state_fips}")
        url = public_url + (f"&key={self.api_key}" if self.api_key else "")
        final_url, body = self._fetch(url)
        self._check_key_redirect(final_url, body, public_url)
        rows = json.loads(body)
        header = rows[0]
        out = []
        for row in rows[1:]:
            rec = dict(zip(header, row))
            out.append({"name": rec["NAME"].rsplit(",", 1)[0].strip(),
                        "state_fips": rec["state"], "place_fips": rec["place"]})
        return out

    # -- cache -------------------------------------------------------
    def _cache(self, query_url: str, body: str, provenance: dict):
        if not self.cache_dir:
            return
        import hashlib
        import pathlib
        cache = pathlib.Path(self.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(query_url.encode()).hexdigest()[:16] + ".json"
        record = {"provenance": provenance, "raw_response": body}
        (cache / name).write_text(json.dumps(record, indent=2), encoding="utf-8")
