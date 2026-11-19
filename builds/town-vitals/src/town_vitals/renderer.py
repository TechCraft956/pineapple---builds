"""One-page Markdown brief renderer.

Renders from the vitals record alone — fully offline from a cached
record. Null figures render as "unknown": never 0, never interpolated.
"""
from __future__ import annotations

from . import hooks as hooks_module

UNKNOWN = "unknown"


def _num(value, fmt="{:,}"):
    if value is None:
        return UNKNOWN
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return fmt.format(value)


def _money(value):
    return UNKNOWN if value is None else "$" + _num(value)


def _pct(value):
    return UNKNOWN if value is None else f"{value:.1f}%"


def _age(value):
    return UNKNOWN if value is None else f"{value:.1f}"


def render_brief(record: dict, hook_results=None) -> str:
    if hook_results is None:
        hook_results = hooks_module.all_hooks()
    f = record["figures"]
    comp = f["composition"]
    prov = record["provenance"]
    town, state = record["town"], record["state"]
    vintage = record["acs_vintage"]

    lines = [
        f"# Town Vitals — {town}, {state}",
        "",
        f"**ACS vintage:** {vintage} (5-year)  ",
        f"**Retrieved:** {prov.get('retrieved_at_utc', UNKNOWN)}  ",
        f"**FIPS (state+place):** {record['fips']}",
        "",
        "_Planning signal, not an official statistic — ACS figures are "
        "survey estimates with margins of error._",
        "",
        "## Vitals",
        "",
        "| Figure | Value |",
        "|---|---|",
        f"| Population | {_num(f['population'])} |",
        f"| Median household income | {_money(f['median_household_income'])} |",
        f"| Median age | {_age(f['median_age'])} |",
        f"| Poverty rate | {_pct(f['poverty_rate'])} |",
        f"| Unemployment rate | {_pct(f['unemployment_rate'])} |",
        f"| Owner-occupied rate | {_pct(f['owner_occupied_rate'])} |",
        f"| Median home value | {_money(f['median_home_value'])} |",
        "",
        "## Growth",
        "",
    ]
    growth = record.get("growth")
    if growth:
        lines.append(
            f"Population {_num(growth['prior_population'])} in ACS "
            f"{growth['prior_vintage']} → {_num(f['population'])} in ACS "
            f"{vintage}: **{growth['pct_change']:+.1f}%** change between the "
            f"two named vintages.")
    else:
        lines.append("Growth unknown — single vintage pulled "
                     "(no prior-vintage population to compare).")
    lines += [
        "",
        "## Composition",
        "",
        f"Hispanic or Latino: {_pct(comp['hispanic_or_latino_pct'])} · "
        f"White alone: {_pct(comp['white_alone_pct'])} · "
        f"Black or African American alone: {_pct(comp['black_alone_pct'])} · "
        f"Other / two or more races: {_pct(comp['other_pct'])}.",
        "",
        "_Hispanic or Latino is an ethnicity and overlaps the race shares. "
        "Rates are computed from raw ACS counts; formulas are stored on the "
        "underlying record._",
        "",
        "## Provenance",
        "",
        f"- Source: US Census Bureau, American Community Survey 5-year {vintage}",
        f"- Source URL: {prov.get('source_url', UNKNOWN)}",
        f"- API query: {prov.get('api_query', UNKNOWN)}",
        f"- Retrieved (UTC): {prov.get('retrieved_at_utc', UNKNOWN)}",
        "",
        "## Not yet wired",
        "",
    ]
    for hook in hook_results:
        lines.append(f"- **{hook['hook']}: {hook['status']}** — {hook['note']}")
    lines += [
        "",
        "---",
        "Town Vitals v1 · Demographic core from public Census ACS data · "
        "Town-hall and economy-signal hooks are NOT WIRED in v1.",
        "",
    ]
    return "\n".join(lines)
