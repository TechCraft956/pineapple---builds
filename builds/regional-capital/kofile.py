#!/usr/bin/env python3
"""Sensor #81 — Starr County deeds, liens & DBAs (KoFile deed index 1848-1984).

Read-only collector, standard library only. No accounts, no API keys, no
spending, no signups, no contacting anyone. Three legs, plus two logged
non-legs:

1. KoFile QuickLink historical deed index (VERIFIED reachable, keyless) —
   ``https://kofilequicklinks.com/StarrTX/Default.aspx``. The Starr County
   Clerk's own page links this portal as the Deed / Deed of Trust index
   books. The landing page states the books run "from 1848 to 1984" and
   offers a name-keyed search form: Type (Deed of Trust / Deeds), Year
   ranges (1884-1926, 1926-1971, 1971-1979, 1979-1984), then cascading
   Parties / Last Name / First Name dropdowns populated by ASP.NET
   postbacks, then SEARCH. The collector fetches the landing page, parses
   the coverage metadata, and (with ``--attempt-search``) walks the
   postback chain as far as the form allows without inventing a name: it
   posts Type, then Year, and records whatever dropdown values each
   postback returns. A full SEARCH needs a real last name, which the
   collector does not invent; supply one with ``--last-name`` (plus
   ``--first-name`` / ``--parties``) to run a targeted name search. Search
   execution from this environment is UNVERIFIED: a single probe postback
   on 2026-11-26 timed out at 30 s (recorded in the evidence file, not
   retried in a loop). The collector records the step reached and the
   failure, and never fabricates results.

2. Modern official-records portal (environment-blocked from here) —
   ``https://starr.tx.publicsearch.us/`` (KoFile search platform, same
   host family as ``https://starrtx.search.kofile.com/``). The landing
   page renders (verified via a text fetch on 2026-11-26: "Official
   Records Search", "Certified through 11/20/2026", Property Records,
   search by grantor/grantee, subdivision, doc type or doc number, date
   range). From this environment direct requests fail: HTTP 403 from
   curl/urllib for starr.tx.publicsearch.us, and the connection is closed
   without a response for starrtx.search.kofile.com. The collector
   attempts both and records the exact outcome; it does not work around
   the block. The Clerk's fee schedule lists a $10.00 official-records
   search fee (REPORTED, from the published fee schedule) — copies are
   $1.00/page, certification $5.00 — so even a working search may carry
   a fee; no payment is ever attempted.

3. TexasFile modern index (BLOCKED-spend, not built) — TexasFile
   advertises a Starr County deed index "1880 to 2026" with free name
   searches only after registration; full records are a paid service.
   Owner step: register / subscribe at texasfile.com. No fetch is
   attempted and no account is created.

4. DBA / assumed-name leg (UNKNOWN — no online source located) — Assumed
   Name Certificates are filed with the County Clerk ($23.00 filing fee,
   per the Clerk's fee schedule) but no online DBA search portal was
   found for Starr County. No DBA data is collected; the leg stays
   UNKNOWN rather than zero-filled.

Every observation carries ``status`` (VERIFIED / REPORTED / UNKNOWN /
BLOCKED), ``source_url`` and ``retrieved_at_utc``. Missing values stay
``null`` — never zero-filled, never invented.

Relevance to sensor #27 (lien/foreclosure feed): the QuickLink index
covers Deeds and Deeds of Trust only — it is not a lien feed. Liens,
releases and foreclosure notices are document types in the modern
official-records portal (leg 2), which is the leg that is blocked from
here. So #81 as built covers the historical deed leg and proves the
portal addresses; it does not by itself close the #27 gap.

Usage:
    python3 kofile.py [--out FILE] [--attempt-search] [--type Deeds]
        [--year 1884-1926] [--parties ...] [--last-name ...]
        [--first-name ...] [--timeout SECONDS]

Exit code is 0 whenever an output document was written, even if a leg is
blocked or unknown — leg status is recorded in the document itself.
Exit code 2 only if no output could be produced at all.
"""
from __future__ import annotations

import argparse
import html as html_mod
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SENSOR_ID = 81
SENSOR_NAME = "kofile-starr-deeds-liens-dbas"

USER_AGENT = "PineappleSensor81/1.0 (research; public Starr County Clerk data, no key)"

QUICKLINK_URL = "https://kofilequicklinks.com/StarrTX/Default.aspx"
MODERN_PORTAL_URL = "https://starr.tx.publicsearch.us/"
SEARCH_HOST_URL = "https://starrtx.search.kofile.com/"
CLERK_PAGE_URL = "https://www.co.starr.tx.us/page/County.Clerk"
TEXASFILE_URL = "https://www.texasfile.com/texas-land-records/"
TSLAC_STARR_URL = "https://www.tsl.texas.gov/arc/local/starr.html"

# Coverage as claimed on the QuickLink welcome text (REPORTED until a
# search confirms a book range); the year menu itself starts at 1884.
COVERAGE_CLAIM = "1848-1984"
INDEX_BOOK_TYPES = ["Deed of Trust", "Deeds"]
YEAR_RANGES = ["1884-1926", "1926-1971", "1971-1979", "1979-1984"]

# ASP.NET control names on the QuickLink search form (stable part after
# the last '$'; the full unique IDs are built from the page at runtime).
CTL_TYPE = "ddlIndexBookType"
CTL_YEAR = "ddlYear"
CTL_PARTIES = "ddlParties"
CTL_LAST = "ddlLastName"
CTL_FIRST = "ddlFirstName"
CTL_SEARCH = "cmdSearch"
FORM_PREFIX = "ctl00$ctl00$ImageContent$MainContent$SearchIndexBookSection$"

ALLOWED_STATUSES = ("VERIFIED", "REPORTED", "UNKNOWN", "BLOCKED")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# HTTP (default fetcher; injectable in tests)
# ---------------------------------------------------------------------------

_OPENER = None


def _default_opener():
    """One opener per process so ASP.NET session cookies persist across
    the landing GET and the postback chain."""
    global _OPENER
    if _OPENER is None:
        jar = http.cookiejar.CookieJar()
        _OPENER = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))
    return _OPENER


def http_request(url: str, data: dict | None = None,
                 timeout: int = 30) -> bytes:
    """GET (data None) or form POST. Returns raw bytes.

    Raises urllib.error.HTTPError (with .code) on non-2xx, URLError /
    TimeoutError / ConnectionError on transport failure. No retries.
    """
    headers = {"User-Agent": USER_AGENT,
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers)
    with _default_opener().open(req, timeout=timeout) as resp:
        return resp.read()


def fetch_text(url: str, fetcher=http_request, timeout: int = 30) -> tuple[int | None, str, str | None]:
    """Fetch a URL, returning (http_status, body_text, error).

    http_status is None when no HTTP response was received at all.
    A non-2xx response is returned as (code, body, None) only when the
    fetcher surfaces it; the default fetcher raises HTTPError, which is
    converted here so legs can record the status instead of crashing.
    """
    try:
        raw = fetcher(url, None, timeout)
        return 200, raw.decode("utf-8", "replace"), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
        return exc.code, body, None
    except Exception as exc:  # noqa: BLE001 — transport failure, no HTTP status
        return None, "", f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# QuickLink landing-page parsing (pure)
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_select_options(html: str, control_suffix: str) -> list[dict]:
    """Options of the <select> whose name ends with control_suffix.

    Returns [{value, label, selected}] in page order. Empty list when
    the control is absent or has no options (the Parties / Last Name /
    First Name dropdowns are empty on the initial landing page).
    """
    pattern = re.compile(
        r'<select[^>]*name="[^"]*' + re.escape(control_suffix) +
        r'"[^>]*>(.*?)</select>', re.S | re.I)
    match = pattern.search(html)
    if not match:
        return []
    options = []
    for opt in re.finditer(
            r'<option([^>]*)value="([^"]*)"[^>]*>([^<]*)</option>',
            match.group(1), re.I):
        attrs, value, label = opt.group(1), opt.group(2), opt.group(3)
        options.append({"value": html_mod.unescape(value),
                        "label": _clean_text(label),
                        "selected": "selected" in attrs.lower()})
    return options


def extract_hidden_fields(html: str) -> dict:
    """ASP.NET hidden fields (__VIEWSTATE, __EVENTVALIDATION, ...)."""
    fields = {}
    for name, value in re.findall(
            r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
            html, re.I):
        fields[name] = html_mod.unescape(value)
    # Attribute order varies; catch value-before-name as well.
    for value, name in re.findall(
            r'<input[^>]*type="hidden"[^>]*value="([^"]*)"[^>]*name="([^"]+)"',
            html, re.I):
        fields.setdefault(name, html_mod.unescape(value))
    return fields


def _select_full_name(html: str, control_suffix: str) -> str | None:
    match = re.search(r'<select[^>]*name="([^"]*' + re.escape(control_suffix) +
                      r')"[^>]*>', html, re.I)
    return html_mod.unescape(match.group(1)) if match else None


def parse_quicklink_landing(html: str, retrieved_at: str) -> dict:
    """Parse the QuickLink Default.aspx landing page.

    VERIFIED when the page is recognisably the Starr County QuickLink
    search page (title + welcome text). Coverage years come from the
    welcome text; the year menu and book-type menu are parsed, not
    assumed. Anything absent stays None.
    """
    title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, re.S | re.I)
    title = _clean_text(title_match.group(1)) if title_match else None

    coverage = None
    cov = re.search(r"Index\s+Books\s+from\s+(\d{4})\s+to\s+(\d{4})",
                    _clean_text(html), re.I)
    if cov:
        coverage = f"{cov.group(1)}-{cov.group(2)}"

    clerk = None
    if re.search(r"Humberto\s+Gonzalez", html):
        clerk = "Humberto Gonzalez"

    types = [o["value"] for o in parse_select_options(html, CTL_TYPE)
             if o["value"]]
    years = [o["value"] for o in parse_select_options(html, CTL_YEAR)
             if o["value"]]
    parties = parse_select_options(html, CTL_PARTIES)
    last_names = parse_select_options(html, CTL_LAST)
    first_names = parse_select_options(html, CTL_FIRST)

    is_quicklink = bool(title and "QuickLink" in title and "Starr" in title)
    status = "VERIFIED" if is_quicklink else "UNKNOWN"
    note = None
    if not is_quicklink:
        note = ("Landing page did not contain the expected QuickLink / "
                "Starr County title; parsed fields are unreliable.")
    elif coverage != COVERAGE_CLAIM:
        note = (f"Welcome text coverage is {coverage!r}, not the "
                f"expected {COVERAGE_CLAIM!r}; recorded as found.")
    return {
        "metric": "quicklink_landing",
        "title": title,
        "clerk": clerk,
        "coverage_claimed": coverage,
        "index_book_types": types,
        "year_ranges": years,
        "parties_option_count": len(parties),
        "last_name_option_count": len(last_names),
        "first_name_option_count": len(first_names),
        "parties_options": [o["value"] for o in parties if o["value"]],
        "status": status,
        "note": note,
        "source": "KoFile QuickLink — Starr County, Texas",
        "source_url": QUICKLINK_URL,
        "retrieved_at_utc": retrieved_at,
    }


# ---------------------------------------------------------------------------
# Modern portal landing-page parsing (pure)
# ---------------------------------------------------------------------------

def parse_modern_portal_landing(html: str, retrieved_at: str,
                                source_url: str) -> dict:
    """Parse the publicsearch.us / search.kofile.com landing page.

    VERIFIED when the page identifies itself as the Starr County
    Official Records Search. The "Certified through" date is the live
    freshness signal; absent -> None, never guessed.
    """
    text = _clean_text(html)
    certified = None
    cert = re.search(r"Certified through\s+([0-9]{2}/[0-9]{2}/[0-9]{4})",
                     text, re.I)
    if cert:
        certified = cert.group(1)
    is_portal = ("Official Records Search" in text
                 and "Starr" in text)
    search_hint = None
    if "grantor" in text.lower() or "grantee" in text.lower():
        search_hint = ("Search for grantor/grantee, subdivision, "
                       "doc type, or doc number")
    status = "VERIFIED" if is_portal else "UNKNOWN"
    return {
        "metric": "modern_portal_landing",
        "title": "Official Records Search" if is_portal else None,
        "certified_through": certified,
        "search_hint": search_hint,
        "status": status,
        "note": None if is_portal else (
            "Landing page did not contain the expected Official Records "
            "Search heading; parsed fields are unreliable."),
        "source": "Starr County Official Records Search (KoFile search platform)",
        "source_url": source_url,
        "retrieved_at_utc": retrieved_at,
    }


# ---------------------------------------------------------------------------
# QuickLink search results parsing (pure; results-page shape unverified)
# ---------------------------------------------------------------------------

def parse_quicklink_results(html: str, retrieved_at: str,
                            query: dict | None = None) -> dict:
    """Parse a QuickLink results page into rows.

    The results-page HTML shape has NOT been observed live (no search
    has completed from here), so this parser is deliberately generic:
    it takes the largest table whose rows have >= 3 cells and returns
    each row's cell text verbatim, labelled REPORTED — never VERIFIED.
    No table, or only a header row, means zero rows (a real result, not
    an error) with results_table_found False.
    """
    text = _clean_text(html)
    no_results = bool(re.search(r"no\s+(records|results|matches)\s+found",
                                text, re.I))
    rows: list[dict] = []
    best_table: list[list[str]] = []
    for table in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S | re.I):
        table_rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S | re.I):
            # Header rows (<th>) are not results; only rows with <td>
            # cells count.
            if not re.search(r"<td[\s>]", tr, re.I):
                continue
            cells = [_clean_text(c) for c in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            cells = [c for c in cells if c != ""]
            if len(cells) >= 3:
                table_rows.append(cells)
        if len(table_rows) > len(best_table):
            best_table = table_rows
    for cells in best_table:
        rows.append({
            "cells": cells,
            "grantor_or_party": cells[0] if len(cells) > 0 else None,
            "grantee_or_party": cells[1] if len(cells) > 1 else None,
            "instrument_or_book": cells[2] if len(cells) > 2 else None,
            "detail": cells[3] if len(cells) > 3 else None,
            "extra": cells[4:] if len(cells) > 4 else [],
            "status": "REPORTED",
            "note": ("Row cell order is positional (results-page layout "
                     "unverified live); fields are labelled by position, "
                     "not by a confirmed column header."),
            "source": "KoFile QuickLink — Starr County, Texas",
            "source_url": QUICKLINK_URL,
            "retrieved_at_utc": retrieved_at,
        })
    return {
        "results_table_found": bool(best_table),
        "no_results_message": no_results,
        "result_count": len(rows),
        "results": rows,
        "query": query or {},
        "status": "REPORTED" if rows else "UNKNOWN",
        "note": ("Results-page layout has not been observed live; rows "
                 "are positional parses of the largest >=3-cell table.")
        if rows else ("No >=3-cell results table found on the page; "
                      "zero rows is recorded, not zero-filled from "
                      "another source."),
    }


# ---------------------------------------------------------------------------
# Postback chain (QuickLink search)
# ---------------------------------------------------------------------------

def build_postback_form(hidden: dict, target_control_full_name: str,
                       values: dict) -> dict:
    """Build an ASP.NET __doPostBack form body.

    ``values`` maps full control names -> selected value; every other
    form control is sent empty so the server sees a complete postback.
    """
    form = dict(hidden)
    form["__EVENTTARGET"] = target_control_full_name
    form["__EVENTARGUMENT"] = ""
    form["__LASTFOCUS"] = ""
    for name, value in values.items():
        form[name] = value
    return form


def _post_form(url: str, form: dict, fetcher, timeout: int) -> str:
    raw = fetcher(url, form, timeout)
    return raw.decode("utf-8", "replace")


def search_quicklink(retrieved_at: str, fetcher=http_request,
                     timeout: int = 30, index_book_type: str = "Deeds",
                     year_range: str = "1884-1926",
                     parties: str | None = None,
                     last_name: str | None = None,
                     first_name: str | None = None) -> dict:
    """Walk the QuickLink postback chain; record how far it gets.

    Steps: GET landing -> post Type -> post Year -> (if parties given)
    post Parties -> (if last name given) post Last Name -> (if first
    name given) post First Name -> click SEARCH. Each step re-reads
    __VIEWSTATE/__EVENTVALIDATION from the page just returned. Any
    step may fail (timeout is the observed failure mode); the leg then
    reports status UNKNOWN with ``step_reached`` and the error, and no
    results are invented. Without a last name no SEARCH is possible —
    the chain stops after the Year postback and reports that honestly.
    """
    leg = {"name": "quicklink_search", "status": "UNKNOWN",
           "source_url": QUICKLINK_URL, "retrieved_at_utc": retrieved_at,
           "query": {"index_book_type": index_book_type,
                     "year_range": year_range,
                     "parties": parties, "last_name": last_name,
                     "first_name": first_name},
           "step_reached": None, "steps": [],
           "parties_options": [], "last_name_options": [],
           "first_name_options": [], "results": None,
           "result_count": None, "error": None}
    try:
        html = fetcher(QUICKLINK_URL, None, timeout).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        leg["error"] = f"QuickLink landing GET failed: {type(exc).__name__}: {exc}"
        return leg
    leg["steps"].append("landing_get")
    leg["step_reached"] = "landing_get"

    hidden = extract_hidden_fields(html)
    names = {}
    for suffix in (CTL_TYPE, CTL_YEAR, CTL_PARTIES, CTL_LAST, CTL_FIRST, CTL_SEARCH):
        full = _select_full_name(html, suffix)
        if full is None:
            # Search button is an <input>, not a <select>.
            m = re.search(r'<input[^>]*name="([^"]*' + re.escape(suffix) +
                          r')"[^>]*>', html, re.I)
            full = html_mod.unescape(m.group(1)) if m else None
        names[suffix] = full or (FORM_PREFIX + suffix)
    current_values = {names[CTL_TYPE]: index_book_type,
                      names[CTL_YEAR]: "",
                      names[CTL_PARTIES]: "",
                      names[CTL_LAST]: "",
                      names[CTL_FIRST]: ""}

    chain = [
        ("type_postback", names[CTL_TYPE],
         {names[CTL_TYPE]: index_book_type}),
        ("year_postback", names[CTL_YEAR],
         {**current_values, names[CTL_YEAR]: year_range}),
    ]
    if parties:
        chain.append(("parties_postback", names[CTL_PARTIES],
                      {**current_values, names[CTL_YEAR]: year_range,
                       names[CTL_PARTIES]: parties}))
    if last_name:
        chain.append(("last_name_postback", names[CTL_LAST],
                      {**current_values, names[CTL_YEAR]: year_range,
                       names[CTL_PARTIES]: parties or "",
                       names[CTL_LAST]: last_name}))
    if first_name:
        chain.append(("first_name_postback", names[CTL_FIRST],
                      {**current_values, names[CTL_YEAR]: year_range,
                       names[CTL_PARTIES]: parties or "",
                       names[CTL_LAST]: last_name or "",
                       names[CTL_FIRST]: first_name}))
    if last_name:
        chain.append(("search_click", None, None))  # handled below

    for step_name, target, values in chain:
        if step_name == "search_click":
            form = build_postback_form(hidden, "", {})
            form.update({k: v for k, v in current_values.items() if v})
            form[names[CTL_SEARCH]] = "SEARCH"
            try:
                html = _post_form(QUICKLINK_URL, form, fetcher, timeout)
            except Exception as exc:  # noqa: BLE001
                leg["error"] = (f"QuickLink SEARCH post failed at step "
                                f"'{step_name}': {type(exc).__name__}: {exc}")
                leg["step_reached"] = "search_click_failed"
                return leg
            parsed = parse_quicklink_results(html, retrieved_at,
                                             query=leg["query"])
            leg["results"] = parsed
            leg["result_count"] = parsed["result_count"]
            leg["status"] = "REPORTED" if parsed["result_count"] else "UNKNOWN"
            leg["steps"].append("search_click")
            leg["step_reached"] = "search_click"
            return leg
        form = build_postback_form(hidden, target, values)
        try:
            html = _post_form(QUICKLINK_URL, form, fetcher, timeout)
        except Exception as exc:  # noqa: BLE001
            leg["error"] = (f"QuickLink postback failed at step "
                            f"'{step_name}': {type(exc).__name__}: {exc}")
            leg["step_reached"] = step_name + "_failed"
            return leg
        hidden = extract_hidden_fields(html) or hidden
        current_values.update(values)
        leg["steps"].append(step_name)
        leg["step_reached"] = step_name
        if step_name == "year_postback":
            leg["parties_options"] = [o["value"] for o in
                                      parse_select_options(html, CTL_PARTIES)
                                      if o["value"]]
        if step_name == "parties_postback":
            leg["last_name_options"] = [o["value"] for o in
                                        parse_select_options(html, CTL_LAST)
                                        if o["value"]]
        if step_name == "last_name_postback":
            leg["first_name_options"] = [o["value"] for o in
                                         parse_select_options(html, CTL_FIRST)
                                         if o["value"]]
    if not last_name:
        leg["error"] = ("Chain stopped after the Year postback: a SEARCH "
                        "needs a real last name and none was supplied "
                        "(--last-name); no name was invented.")
        leg["status"] = "UNKNOWN"
    return leg


# ---------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------

def fetch_quicklink_landing(retrieved_at: str, fetcher=http_request,
                            timeout: int = 30) -> dict:
    leg = {"name": "quicklink_landing", "status": "UNKNOWN",
           "source_url": QUICKLINK_URL, "retrieved_at_utc": retrieved_at,
           "http_status": None, "bytes": None, "landing": None,
           "error": None}
    status, body, error = fetch_text(QUICKLINK_URL, fetcher, timeout)
    leg["http_status"] = status
    leg["bytes"] = len(body.encode("utf-8")) if body else 0
    if error is not None:
        leg["error"] = (f"QuickLink landing GET failed with no HTTP "
                        f"response: {error}")
        return leg
    if status != 200:
        leg["error"] = (f"QuickLink landing answered HTTP {status} "
                        f"instead of 200.")
        return leg
    landing = parse_quicklink_landing(body, retrieved_at)
    leg["landing"] = landing
    leg["status"] = landing["status"]
    if landing["note"]:
        leg["error"] = landing["note"]
    return leg


def fetch_modern_portal(retrieved_at: str, fetcher=http_request,
                        timeout: int = 30) -> dict:
    """Attempt the modern official-records portal (both hostnames)."""
    leg = {"name": "modern_portal", "status": "UNKNOWN",
           "source_url": MODERN_PORTAL_URL, "retrieved_at_utc": retrieved_at,
           "http_status": None, "bytes": None, "landing": None,
           "search_host": {"url": SEARCH_HOST_URL, "http_status": None,
                           "error": None},
           "error": None}
    status, body, error = fetch_text(MODERN_PORTAL_URL, fetcher, timeout)
    leg["http_status"] = status
    leg["bytes"] = len(body.encode("utf-8")) if body else 0
    if error is not None:
        leg["error"] = (f"Modern portal GET failed with no HTTP response "
                        f"from this environment: {error}. The landing page "
                        f"renders via a text fetch (verified 2026-11-26: "
                        f"'Official Records Search', 'Certified through "
                        f"11/20/2026'), so this is an environment block, "
                        f"not proof the portal is down.")
    elif status != 200:
        leg["error"] = (f"Modern portal answered HTTP {status} from this "
                        f"environment (no body search attempted). The "
                        f"landing page renders via a text fetch, so this "
                        f"is an environment block, not proof the portal "
                        f"is down.")
    else:
        landing = parse_modern_portal_landing(body, retrieved_at,
                                              MODERN_PORTAL_URL)
        leg["landing"] = landing
        leg["status"] = landing["status"]
        if landing["note"]:
            leg["error"] = landing["note"]

    status2, body2, error2 = fetch_text(SEARCH_HOST_URL, fetcher, timeout)
    leg["search_host"]["http_status"] = status2
    if error2 is not None:
        leg["search_host"]["error"] = (
            f"No HTTP response from this environment: {error2}. The page "
            f"renders via a text fetch (verified 2026-11-26: 'Search', "
            f"'Certified through 04/18/2025').")
    elif status2 != 200:
        leg["search_host"]["error"] = f"Answered HTTP {status2}."
    else:
        landing2 = parse_modern_portal_landing(body2, retrieved_at,
                                               SEARCH_HOST_URL)
        leg["search_host"]["landing"] = landing2
        leg["search_host"]["error"] = None
    return leg


def texasfile_leg(retrieved_at: str) -> dict:
    """Static BLOCKED-spend record. No fetch, no account, no workaround."""
    return {
        "name": "texasfile_modern_index",
        "status": "BLOCKED",
        "source_url": TEXASFILE_URL,
        "retrieved_at_utc": retrieved_at,
        "coverage_claimed": "1880-2026",
        "coverage_label": "REPORTED",
        "coverage_source": ("TexasFile county table (texasfile.com): "
                            "Starr 1880 to 2026; free name searches only "
                            "after registration, full records paid."),
        "owner_step": ("Register / subscribe at texasfile.com for Starr "
                       "County access (TexasFile account + subscription); "
                       "no signup has been performed by this collector."),
        "error": ("Modern index via TexasFile is a paid service "
                  "(registration required for free name search; full "
                  "records paid). Not built, per the build plan."),
    }


def dba_leg(retrieved_at: str) -> dict:
    """Static UNKNOWN record: no online DBA portal was located."""
    return {
        "name": "dba_assumed_names",
        "status": "UNKNOWN",
        "source_url": CLERK_PAGE_URL,
        "retrieved_at_utc": retrieved_at,
        "filing_fee_reported": "$23.00",
        "fee_source": ("Starr County Clerk fee schedule (REPORTED): "
                       "Assumed Name Certificate / Withdrawal $23.00."),
        "error": ("No online assumed-name (DBA) search portal was found "
                  "for Starr County; certificates are filed with the "
                  "County Clerk. No DBA data collected; value stays "
                  "unknown, not zero."),
    }


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------

def collect(fetcher=http_request, timeout: int = 30,
            attempt_search: bool = False,
            search_kwargs: dict | None = None) -> dict:
    """Run all legs and assemble the sensor document."""
    retrieved_at = utc_now_iso()
    quicklink = fetch_quicklink_landing(retrieved_at, fetcher, timeout)
    modern = fetch_modern_portal(retrieved_at, fetcher, timeout)
    search = None
    if attempt_search:
        search = search_quicklink(retrieved_at, fetcher, timeout,
                                  **(search_kwargs or {}))
    texasfile = texasfile_leg(retrieved_at)
    dba = dba_leg(retrieved_at)

    observations = []
    if quicklink.get("landing"):
        observations.append(quicklink["landing"])
    if quicklink["status"] != "VERIFIED":
        observations.append({
            "metric": "quicklink_landing",
            "value": None,
            "status": quicklink["status"],
            "note": quicklink.get("error"),
            "source": "KoFile QuickLink — Starr County, Texas",
            "source_url": QUICKLINK_URL,
            "retrieved_at_utc": retrieved_at,
        })
    if modern.get("landing"):
        observations.append(modern["landing"])
    else:
        observations.append({
            "metric": "modern_portal_landing",
            "value": None,
            "status": "UNKNOWN",
            "note": modern.get("error"),
            "source": "Starr County Official Records Search (KoFile search platform)",
            "source_url": MODERN_PORTAL_URL,
            "retrieved_at_utc": retrieved_at,
        })
    if search is not None:
        observations.append({
            "metric": "quicklink_search",
            "value": search.get("result_count"),
            "status": search["status"],
            "query": search["query"],
            "step_reached": search["step_reached"],
            "steps": search["steps"],
            "note": search.get("error"),
            "source": "KoFile QuickLink — Starr County, Texas",
            "source_url": QUICKLINK_URL,
            "retrieved_at_utc": retrieved_at,
        })
        if search.get("results"):
            observations.extend(search["results"]["results"])
    observations.append({
        "metric": "texasfile_modern_index",
        "value": None,
        "status": "BLOCKED",
        "note": texasfile["error"],
        "owner_step": texasfile["owner_step"],
        "source": "TexasFile — Texas County Clerk Records",
        "source_url": TEXASFILE_URL,
        "retrieved_at_utc": retrieved_at,
    })
    observations.append({
        "metric": "dba_assumed_names",
        "value": None,
        "status": "UNKNOWN",
        "note": dba["error"],
        "source": "Starr County Clerk — Assumed Name Certificates",
        "source_url": CLERK_PAGE_URL,
        "retrieved_at_utc": retrieved_at,
    })

    legs = {
        "quicklink_landing": {k: v for k, v in quicklink.items()
                              if k != "landing"},
        "modern_portal": {k: v for k, v in modern.items()
                          if k != "landing"},
        "texasfile_modern_index": texasfile,
        "dba_assumed_names": dba,
    }
    if search is not None:
        legs["quicklink_search"] = {k: v for k, v in search.items()
                                    if k != "results"}

    return {
        "sensor_id": SENSOR_ID,
        "sensor": SENSOR_NAME,
        "area": "Starr County, Texas (FIPS 48427)",
        "county_clerk": "Starr County Clerk, 401 N. Britton Ave, Room 201, Rio Grande City, TX 78582",
        "retrieved_at_utc": retrieved_at,
        "legs": legs,
        "summary": {
            "quicklink_http_status": quicklink["http_status"],
            "quicklink_bytes": quicklink["bytes"],
            "quicklink_status": quicklink["status"],
            "quicklink_coverage_claimed": (
                quicklink["landing"]["coverage_claimed"]
                if quicklink.get("landing") else None),
            "quicklink_year_ranges": (
                quicklink["landing"]["year_ranges"]
                if quicklink.get("landing") else None),
            "quicklink_index_book_types": (
                quicklink["landing"]["index_book_types"]
                if quicklink.get("landing") else None),
            "modern_portal_http_status": modern["http_status"],
            "modern_portal_status": modern["status"],
            "modern_portal_certified_through": (
                modern["landing"]["certified_through"]
                if modern.get("landing") else None),
            "search_host_http_status": modern["search_host"]["http_status"],
            "quicklink_search_status": search["status"] if search else None,
            "quicklink_search_step_reached": (
                search["step_reached"] if search else None),
            "quicklink_search_result_count": (
                search["result_count"] if search else None),
            "texasfile_status": "BLOCKED",
            "dba_status": "UNKNOWN",
        },
        "observations": observations,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None,
                        help="Write the JSON document to this file as well as stdout.")
    parser.add_argument("--attempt-search", action="store_true",
                        help="Walk the QuickLink postback chain (Type, Year, "
                             "then Parties/Last/First name if given, then SEARCH). "
                             "Without --last-name the chain stops after Year.")
    parser.add_argument("--type", default="Deeds", dest="index_book_type",
                        help="Index book type: Deeds or Deed of Trust (default Deeds).")
    parser.add_argument("--year", default="1884-1926", dest="year_range",
                        help="Year range, e.g. 1884-1926 (default).")
    parser.add_argument("--parties", default=None,
                        help="Parties value, if known from a prior step.")
    parser.add_argument("--last-name", default=None,
                        help="Last name to search (required for SEARCH; never invented).")
    parser.add_argument("--first-name", default=None,
                        help="First name to search (optional).")
    parser.add_argument("--timeout", type=int, default=30,
                        help="Per-request timeout in seconds (default 30).")
    args = parser.parse_args(argv)

    doc = collect(timeout=args.timeout, attempt_search=args.attempt_search,
                  search_kwargs={
                      "index_book_type": args.index_book_type,
                      "year_range": args.year_range,
                      "parties": args.parties,
                      "last_name": args.last_name,
                      "first_name": args.first_name,
                  } if args.attempt_search else None)

    text = json.dumps(doc, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    sys.stderr.write(
        f"[sensor #{SENSOR_ID}] QuickLink: {doc['summary']['quicklink_status']} "
        f"(HTTP {doc['summary']['quicklink_http_status']}, "
        f"{doc['summary']['quicklink_bytes']} bytes, coverage "
        f"{doc['summary']['quicklink_coverage_claimed']}) | "
        f"Modern portal: {doc['summary']['modern_portal_status']} "
        f"(HTTP {doc['summary']['modern_portal_http_status']}) | "
        f"Search: {doc['summary']['quicklink_search_status']} "
        f"(step {doc['summary']['quicklink_search_step_reached']}) | "
        f"TexasFile: BLOCKED | DBA: UNKNOWN\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
