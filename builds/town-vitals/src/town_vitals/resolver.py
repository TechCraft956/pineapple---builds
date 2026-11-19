"""Place resolver: town name -> state + place FIPS.

State-generic (seed scope Texas, state FIPS 48). Place lists can come
from:
  * the Census API's own place list for the state (CensusClient.
    fetch_place_list — needs an API key since 2026-05-12), or
  * the Census Bureau's Gazetteer place file (keyless, official), or
  * any injected list of dicts (tests / fixtures).

Ambiguity NEVER resolves silently: multiple normalized matches raise
AmbiguousPlaceError carrying the full candidate list.
"""
from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass

from .census_client import USER_AGENT

GAZETTEER_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
                 "{year}_Gazetteer/{year}_Gaz_place_national.zip")

# Legal-status suffixes stripped for matching ("Roma city" -> "roma").
_SUFFIXES = {
    "city", "town", "village", "borough", "municipality", "cdp",
    "city and borough", "census designated place", "municipio",
}
_STATE_NAMES = {"48": "Texas"}


class PlaceNotFoundError(LookupError):
    pass


class AmbiguousPlaceError(LookupError):
    def __init__(self, query, candidates):
        self.query = query
        self.candidates = candidates
        listing = "; ".join(
            f"{c.name} (state {c.state_fips}, place {c.place_fips})" for c in candidates)
        super().__init__(f"ambiguous place name '{query}': {listing}")


@dataclass(frozen=True)
class Place:
    name: str            # official name, e.g. "Roma city"
    state_fips: str      # e.g. "48"
    place_fips: str      # e.g. "63020"
    state_name: str = ""

    @property
    def geoid(self) -> str:
        return f"{self.state_fips}{self.place_fips}"

    @property
    def fips(self) -> str:
        return self.geoid

    @property
    def display_name(self) -> str:
        return self.name


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation/state suffix, strip legal suffix."""
    text = name.split(",", 1)[0].strip().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    changed = True
    while changed:
        changed = False
        for suffix in sorted(_SUFFIXES, key=len, reverse=True):
            if text.endswith(" " + suffix):
                text = text[: -len(suffix)].strip()
                changed = True
    return text


def places_from_dicts(rows, state_name=""):
    return [Place(name=r["name"], state_fips=str(r["state_fips"]),
                  place_fips=str(r["place_fips"]),
                  state_name=r.get("state_name", state_name)) for r in rows]


def load_gazetteer_places(year: int = 2024, state_fips: str | None = None,
                          fetch_bytes=None):
    """Load places from the Census Bureau Gazetteer national place file."""
    url = GAZETTEER_URL.format(year=year)
    if fetch_bytes is None:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            blob = resp.read()
    else:
        blob = fetch_bytes(url)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
    places = []
    lines = text.splitlines()
    for line in lines[1:]:
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 4:
            continue
        usps, geoid, _ansi, name = parts[0], parts[1], parts[2], parts[3]
        if len(geoid) != 7:
            continue
        st, pl = geoid[:2], geoid[2:]
        if state_fips and st != state_fips:
            continue
        places.append(Place(name=name, state_fips=st, place_fips=pl,
                            state_name=_STATE_NAMES.get(st, usps)))
    return places


class PlaceResolver:
    def __init__(self, places):
        self.places = list(places)

    @classmethod
    def from_api(cls, client, vintage: int, state_fips: str):
        rows = client.fetch_place_list(vintage, state_fips)
        return cls(places_from_dicts(rows, _STATE_NAMES.get(state_fips, "")))

    @classmethod
    def from_gazetteer(cls, year: int = 2024, state_fips: str | None = None):
        return cls(load_gazetteer_places(year=year, state_fips=state_fips))

    def resolve(self, query: str, state_fips: str | None = None) -> Place:
        """Resolve a town name to exactly one Place.

        Exact normalized match first; a unique prefix match is accepted
        only when exactly one candidate exists. Multiple candidates at
        any stage raise AmbiguousPlaceError with the candidate list.
        """
        pool = [p for p in self.places
                if state_fips is None or p.state_fips == state_fips]
        target = normalize_name(query)
        exact = [p for p in pool if normalize_name(p.name) == target]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise AmbiguousPlaceError(query, exact)
        prefix = [p for p in pool if normalize_name(p.name).startswith(target)]
        if len(prefix) == 1:
            return prefix[0]
        if len(prefix) > 1:
            raise AmbiguousPlaceError(query, prefix)
        raise PlaceNotFoundError(
            f"no place matching '{query}'"
            + (f" in state {state_fips}" if state_fips else ""))
