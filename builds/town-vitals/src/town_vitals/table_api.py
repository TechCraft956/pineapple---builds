"""Keyless live provider over the Census Bureau's own ACS tables.

Since 2026-05-12 the api.census.gov data endpoint requires a free API
key (see census_client.py). The Bureau's data.census.gov table-access
endpoint serves the *identical* ACS 5-year tables and variable ids
without a key, and each response names the underlying api.census.gov
query in its `dataAPIURI` field. This provider uses that endpoint so
the live smoke (and any keyless run) pulls real ACS figures with full
provenance. It is a fallback transport, not a different dataset:
same vintage, same tables (B01003, B19013, ...), same variable ids,
same sentinel handling (parse_value from census_client).
"""
from __future__ import annotations

import json
import urllib.request

from .census_client import USER_AGENT, CensusError, parse_value, utc_now_iso

TABLE_API_BASE = "https://data.census.gov/api/access/data/table"


def _default_fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def table_of(variable_id: str) -> str:
    return variable_id.split("_", 1)[0]


class TableApiProvider:
    def __init__(self, fetch=None, cache_dir=None):
        self._fetch = fetch or _default_fetch
        self.cache_dir = cache_dir
        self.raw_responses = []  # [{url, retrieved_at_utc, body}] for caching/evidence

    def build_table_url(self, vintage: int, table: str, state_fips: str,
                        place_fips: str) -> str:
        geoid = f"{state_fips}{place_fips}"
        return f"{TABLE_API_BASE}?id=ACSDT5Y{vintage}.{table}&g=160XX00US{geoid}"

    def fetch_table(self, vintage: int, table: str, state_fips: str,
                    place_fips: str) -> dict:
        """Return {variable_id: parsed value} for one ACS table + place."""
        url = self.build_table_url(vintage, table, state_fips, place_fips)
        body = self._fetch(url)
        self.raw_responses.append(
            {"url": url, "retrieved_at_utc": utc_now_iso(), "body": body})
        try:
            payload = json.loads(body)
            rows = payload["response"]["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CensusError(f"table API {table} {vintage} returned no data rows: {exc}")
        if len(rows) < 2:
            raise CensusError(f"table API {table} {vintage} returned header only "
                              f"for state {state_fips} place {place_fips}")
        raw = dict(zip(rows[0], rows[1]))
        return {k: parse_value(v) for k, v in raw.items()
                if "_" in k and k.rsplit("_", 1)[-1].endswith("E")}

    def fetch_place(self, vintage: int, state_fips: str, place_fips: str,
                    variable_ids):
        """Fetch the requested variables across their tables.

        Returns (values, provenance) in the same shape as
        CensusClient.fetch_place. provenance.api_query lists every
        table query URL used; source_url is the first (population)
        query and the record also carries all query URLs.
        """
        # B01003 (population) first so provenance.source_url is the
        # population query; the rest alphabetical.
        tables = sorted({table_of(v) for v in variable_ids},
                        key=lambda t: (t != "B01003", t))
        values, urls = {}, []
        for table in tables:
            urls.append(self.build_table_url(vintage, table, state_fips, place_fips))
            values.update(self.fetch_table(vintage, table, state_fips, place_fips))
        values = {vid: values.get(vid) for vid in variable_ids}
        provenance = {
            "source_url": urls[0],
            "retrieved_at_utc": utc_now_iso(),
            "api_query": " ; ".join(urls),
            "vintage": vintage,
            "transport": "data.census.gov table access (keyless); same ACS "
                         "tables/variables as api.census.gov, which has "
                         "required a free key for data queries since 2026-05-12",
            "query_urls": urls,
        }
        return values, provenance
