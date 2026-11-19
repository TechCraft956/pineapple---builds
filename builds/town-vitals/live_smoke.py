#!/usr/bin/env python3
"""Live smoke for Town Vitals — NOT part of the offline test suite.

Pulls real ACS figures for Roma city, TX and McAllen, TX:
  * variable ids verified against api.census.gov variables endpoint,
  * places resolved from the Census Bureau Gazetteer place file,
  * figures pulled keyless via the Census Bureau's data.census.gov
    table-access endpoint (same ACS tables/variables; api.census.gov
    data queries have required a free API key since 2026-05-12 — the
    direct-API attempt below records that behaviour),
  * latest vintage 2024 + prior vintage 2019 for growth.

Writes records + briefs to evidence/, raw responses to cache/.
Run:  python3 live_smoke.py
"""
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from town_vitals.census_client import (ALL_VARIABLE_IDS, CensusClient,  # noqa: E402
                                       CensusKeyRequiredError, USER_AGENT)
from town_vitals.resolver import PlaceResolver, load_gazetteer_places  # noqa: E402
from town_vitals.table_api import TableApiProvider  # noqa: E402
from town_vitals.vitals import assemble_vitals, to_item  # noqa: E402
from town_vitals.renderer import render_brief  # noqa: E402

LATEST_VINTAGE = 2024
PRIOR_VINTAGE = 2019
STATE_FIPS = "48"
TOWNS = ["Roma", "McAllen"]


def main():
    evidence = ROOT / "evidence"
    cache = ROOT / "cache"
    evidence.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)

    client = CensusClient(cache_dir=str(cache))
    labels = client.verify_variables(LATEST_VINTAGE)
    client.verify_variables(PRIOR_VINTAGE)
    print(f"[ok] verified {len(labels)} variable ids against the "
          f"{LATEST_VINTAGE} variables endpoint; {PRIOR_VINTAGE} also verified")

    # Record the direct-API behaviour (key requirement) as evidence.
    try:
        client.fetch_place(LATEST_VINTAGE, STATE_FIPS, "63020", ["B01003_001E"])
        print("[note] direct api.census.gov data query succeeded without a key")
        direct_api = "succeeded keyless"
    except CensusKeyRequiredError as exc:
        print(f"[note] direct api.census.gov data query: {exc}")
        direct_api = "key required (302 -> missing_key.html); keyless table-access transport used"

    # Gazetteer place list (cached zip), Texas only.
    gaz_zip = cache / "2024_Gaz_place_national.zip"
    if not gaz_zip.exists():
        req = urllib.request.Request(
            "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
            "2024_Gazetteer/2024_Gaz_place_national.zip",
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            gaz_zip.write_bytes(resp.read())
    places = load_gazetteer_places(
        year=2024, state_fips=STATE_FIPS,
        fetch_bytes=lambda url: gaz_zip.read_bytes())
    resolver = PlaceResolver(places)
    print(f"[ok] gazetteer loaded {len(places)} Texas places")

    provider = TableApiProvider()
    summaries = {"direct_api_census_gov": direct_api, "towns": {}}
    for town_query in TOWNS:
        place = resolver.resolve(town_query, state_fips=STATE_FIPS)
        latest, provenance = provider.fetch_place(
            LATEST_VINTAGE, place.state_fips, place.place_fips, ALL_VARIABLE_IDS)
        prior, _ = provider.fetch_place(
            PRIOR_VINTAGE, place.state_fips, place.place_fips, ["B01003_001E"])
        record = assemble_vitals(place, latest, LATEST_VINTAGE, provenance,
                                 prior_values=prior, prior_vintage=PRIOR_VINTAGE)
        slug = place.name.replace(" ", "_")
        (evidence / f"{slug}_record.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8")
        (evidence / f"{slug}_item.json").write_text(
            json.dumps(to_item(record), indent=2), encoding="utf-8")
        brief_path = evidence / f"{slug}_brief.md"
        brief_path.write_text(render_brief(record), encoding="utf-8")
        f = record["figures"]
        summaries["towns"][place.name] = {
            "fips": record["fips"], "figures": f, "growth": record["growth"],
            "brief": str(brief_path.relative_to(ROOT)),
        }
        print(f"[ok] {place.name}, TX (FIPS {record['fips']}): "
              f"pop={f['population']} income={f['median_household_income']} "
              f"growth={record['growth']}")

    (cache / "live_raw_responses.json").write_text(
        json.dumps(provider.raw_responses, indent=2), encoding="utf-8")
    (evidence / "live_smoke_summary.json").write_text(
        json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"[done] briefs + records in {evidence}; raw responses in {cache}")


if __name__ == "__main__":
    main()
