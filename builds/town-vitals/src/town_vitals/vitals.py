"""Vitals assembly: raw ACS variable values -> the vitals record.

Contract (from the build brief):
  {town, state, fips, acs_vintage,
   figures: {population, median_household_income, median_age,
             poverty_rate, unemployment_rate, owner_occupied_rate,
             median_home_value,
             composition: {hispanic_or_latino_pct, white_alone_pct,
                           black_alone_pct, other_pct}},
   growth: {prior_vintage, prior_population, pct_change} | null,
   provenance: {source_url, retrieved_at_utc, api_query}}

Unknown figures stay null — never 0, never interpolated, never
borrowed from county data. Rates are computed from raw counts; every
formula is stored on the record. Growth is computed ONLY when both
vintages' populations exist, and both vintages are named.
"""
from __future__ import annotations

from .census_client import VARIABLES as V

FORMULAS = {
    "poverty_rate": "B17001_002E / B17001_001E * 100",
    "unemployment_rate": "B23025_005E / B23025_003E * 100 "
                         "(unemployed / civilian labor force)",
    "owner_occupied_rate": "B25003_002E / B25003_001E * 100",
    "hispanic_or_latino_pct": "B03002_012E / B03002_001E * 100",
    "white_alone_pct": "(B03002_003E + B03002_013E) / B03002_001E * 100 "
                       "(white alone, any ethnicity)",
    "black_alone_pct": "(B03002_004E + B03002_014E) / B03002_001E * 100 "
                       "(Black or African American alone, any ethnicity)",
    "other_pct": "(B03002_001E - white_alone_all - black_alone_all) "
                 "/ B03002_001E * 100 (all other races / two or more races)",
    "growth_pct_change": "(population[latest] - population[prior]) "
                         "/ population[prior] * 100",
}


def _pct(numerator, denominator):
    """Percentage from raw counts; null when either side is unknown
    or the denominator is zero/missing."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


def _add(a, b):
    if a is None or b is None:
        return None
    return a + b


def assemble_vitals(place, latest_values: dict, acs_vintage: int,
                    provenance: dict, prior_values: dict | None = None,
                    prior_vintage: int | None = None) -> dict:
    """Build the vitals record for one place from parsed ACS values.

    latest_values / prior_values map variable id -> int/float/None
    (sentinels already converted to None by the client layer).
    """
    g = latest_values.get
    white_alone = _add(g(V["white_alone_nh"]), g(V["white_alone_h"]))
    black_alone = _add(g(V["black_alone_nh"]), g(V["black_alone_h"]))
    comp_total = g(V["comp_total"])
    other_count = None
    if comp_total is not None and white_alone is not None and black_alone is not None:
        other_count = comp_total - white_alone - black_alone

    figures = {
        "population": g(V["population"]),
        "median_household_income": g(V["median_household_income"]),
        "median_age": g(V["median_age"]),
        "poverty_rate": _pct(g(V["poverty_below"]), g(V["poverty_universe"])),
        "unemployment_rate": _pct(g(V["unemployed"]), g(V["civilian_labor_force"])),
        "owner_occupied_rate": _pct(g(V["owner_occupied"]), g(V["tenure_total"])),
        "median_home_value": g(V["median_home_value"]),
        "composition": {
            "hispanic_or_latino_pct": _pct(g(V["hispanic_or_latino"]), comp_total),
            "white_alone_pct": _pct(white_alone, comp_total),
            "black_alone_pct": _pct(black_alone, comp_total),
            "other_pct": _pct(other_count, comp_total),
        },
    }

    growth = None
    if prior_values is not None and prior_vintage is not None:
        prior_pop = prior_values.get(V["population"])
        latest_pop = figures["population"]
        if prior_pop is not None and latest_pop is not None and prior_pop != 0:
            growth = {
                "prior_vintage": prior_vintage,
                "prior_population": prior_pop,
                "pct_change": round((latest_pop - prior_pop) / prior_pop * 100, 2),
            }

    return {
        "town": place.name,
        "state": place.state_name or place.state_fips,
        "state_fips": place.state_fips,
        "place_fips": place.place_fips,
        "fips": place.geoid,
        "acs_vintage": acs_vintage,
        "figures": figures,
        "growth": growth,
        "formulas": dict(FORMULAS),
        "raw_counts": {k: latest_values.get(v) for k, v in V.items()},
        "provenance": provenance,
    }


def to_item(record: dict) -> dict:
    """items()-style feed dict for later wiring (category PLACES)."""
    town, state = record["town"], record["state"]
    return {
        "title": f"Town Vitals — {town}, {state}",
        "category": "PLACES",
        "source": f"US Census Bureau, ACS 5-year {record['acs_vintage']}",
        "action": "Review the one-page town brief before visiting, scouting, "
                  "or evaluating this town.",
        "est_value": None,
        "risk": "Planning signal, not an official statistic: ACS figures are "
                "survey estimates with margins of error.",
        "location": f"{town}, {state}",
        "url": record["provenance"]["source_url"],
        "confidence": 0.8,
    }
