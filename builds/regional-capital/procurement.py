#!/usr/bin/env python3
"""TX procurement & DIR contracts collector — Pineapple sensor #82
(regional capital).

Read-only collector over three public, keyless legs, all focused on
procurement activity relevant to Starr County, TX (FIPS 48427) and the
Rio Grande Valley:

Leg A — TxSmartBuy ESBD (Electronic State Business Daily)
    https://www.txsmartbuy.gov/esbd
    State solicitations over $25k, plus postings from Texas SmartBuy
    member governments. The listing page is server-rendered HTML
    (newest first, 24 rows/page, ~2,531 pages at build time) and is
    parsed directly. There is NO reachable machine-readable API: the
    site's filter is JavaScript-only and its backing Suitelet
    (``services/ESBD.Service.ss``) answers HTTP 404 from this
    environment at every resolvable path, and ``?keyword=`` /
    ``?agency=`` query params are ignored server-side (verified live
    2026-11-26). The collector therefore scans the newest N pages
    (default 5) and keyword-matches titles / member agency numbers
    itself. Coverage is explicitly partial — recorded in the leg
    report, never presented as a full search. Also verified live:
    the member-agency dropdown (427 options) contains NO Starr
    County entity — Starr County government is not a TxSmartBuy
    member poster; Starr-relevant ESBD postings would come from
    state agencies (e.g. TxDOT) mentioning Starr in the title.

Leg B — TX DIR (Dept. of Information Resources), data.texas.gov
    Socrata, keyless JSON, no signup, $0:
    * ``vipt-h4ye`` — Official DIR Current Active Cooperative
      Contracts (5,214 rows at build time). Statewide register, no
      county field; the collector records the register size plus a
      sample of the most recently started contracts.
    * ``a743-wj72`` — Official VSR Data for Cooperative & Tele
      Contracts FY2026 to Present (2,243,367 rows). The Starr
      angle: purchases by Starr County customers
      (``upper(customer_name) like '%STARR%'`` — 287 rows,
      $311k at build time) are fetched in full.
    Human browse UI for the same register: https://dir.texas.gov/contracts

Leg C — TxDOT current lettings, data.texas.gov Socrata ``qh8x-rm8r``
    ("Official and Unofficial Bid Items", bid line items, keyless).
    Filtered to county = 'Starr' (0 open lettings at build time —
    a real finding, not an error) with Pharr-district / Hidalgo /
    Cameron context counts. Rows are bid LINE ITEMS, so observations
    are deduplicated to one per distinct controlling project id.

Labels
------
VERIFIED  record present in the source with its key fields
          (id + title/name + date) all present.
REPORTED  record present but a key field is missing/unparseable.
          The value stays null, never zero-filled.
UNKNOWN   not emitted by this collector's legs as built; reserved
          for a future weak-match leg (see README_PROCUREMENT.md).

Every observation records its source URL and a UTC retrieval
timestamp. Missing values stay ``None``.

Privacy
-------
DIR datasets carry personal contact data (vendor/contract-manager
emails and phone numbers, customer contacts). Those columns are
never read into an observation and never appear in any output file.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ESBD_URL = "https://www.txsmartbuy.gov/esbd"
ESBD_SERVICE_URL = "https://www.txsmartbuy.gov/services/ESBD.Service.ss"
DIR_CONTRACTS_URL = "https://dir.texas.gov/contracts"

SOCRATA_BASE = "https://data.texas.gov/resource"
DIR_ACTIVE_DATASET = "vipt-h4ye"   # DIR Current Active Cooperative Contracts
DIR_SALES_DATASET = "a743-wj72"    # DIR Cooperative & Tele Contract Sales FY2026+
TXDOT_LETTINGS_DATASET = "qh8x-rm8r"  # TxDOT Official/Unofficial Bid Items

FIPS_STARR_COUNTY_TX = "48427"

# Title keywords that mark an ESBD posting Starr-relevant.
STARR_TERMS = (
    "starr", "rio grande city", "roma", "la grulla", "sullivan city",
    "escobares", "falcon heights", "garceno", "san isidro", "la rosita",
    "el sauz", "fronton",
)
# Title keywords / member agency numbers that mark a posting RGV-relevant.
RGV_TERMS = (
    "hidalgo", "cameron", "pharr", "mcallen", "edinburg", "harlingen",
    "brownsville", "weslaco", "mission", "rio grande valley", "utrgv",
    "willacy", "raymondville",
)
# Texas SmartBuy member numbers of RGV entities, from the ESBD agency
# dropdown (verified live 2026-11-26). No Starr County member exists.
RGV_AGENCY_NUMBERS = {
    "C0311",  # Cameron County
    "K2017",  # Cameron County Regional Mobility Authority
    "M1083",  # City of Pharr
    "K3392",  # Hidalgo Co. Regional Mobility Authority
    "C1080",  # Hidalgo County
    "S1080",  # McAllen ISD
    "746",    # UT Rio Grande Valley
    "K0012",  # Workforce Solutions (McAllen)
    "K2223",  # Workforce Solutions Cameron
}

DEFAULT_ESBD_PAGES = 5
DEFAULT_DIR_SAMPLE_LIMIT = 50
DEFAULT_MAX_DIR_SALES_ROWS = 1000

USER_AGENT = "Pineapple-sensor-82/1.0 (read-only public-data collector)"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value):
    """Strip whitespace; empty strings become None (never zero-filled)."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


# ---------------------------------------------------------------- ESBD leg

_ESBD_ROW_RE = re.compile(
    r'<div class="esbd-result-row">(.*?)</div>\s*</div>\s*</div>',
    re.S)
_ESBD_TITLE_RE = re.compile(
    r'esbd-result-title"><a href="([^"]+)">\s*([^<]+?)\s*</a>', re.S)
_ESBD_FIELD_RE = re.compile(
    r'<strong>([^<]+?):\s*</strong>\s*([^<]*?)\s*</p>', re.S)
_ESBD_TOTAL_PAGES_RE = re.compile(r'Page \d+ of ([\d,]+) Pages')


def parse_esbd_listing(html_text: str) -> tuple[list[dict], int | None]:
    """Parse one ESBD listing page.

    Returns (rows, total_pages). Each row carries the raw fields as
    printed on the official listing; missing fields stay None.
    ``total_pages`` is None when the pagination line is absent.
    """
    rows: list[dict] = []
    for block in _ESBD_ROW_RE.findall(html_text):
        title_m = _ESBD_TITLE_RE.search(block)
        fields = {k.strip(): _clean(v)
                  for k, v in _ESBD_FIELD_RE.findall(block)}
        rows.append({
            "url_path": title_m.group(1) if title_m else None,
            "title": html_lib.unescape(title_m.group(2).strip())
            if title_m else None,
            "solicitation_id": fields.get("Solicitation ID"),
            "due_date": fields.get("Due Date"),
            "due_time": fields.get("Due Time"),
            "agency_number": fields.get(
                "Agency/Texas SmartBuy Member Number"),
            "status": fields.get("Status"),
            "posting_date": fields.get("Posting Date"),
            "created_date": fields.get("Created Date"),
            "last_updated": fields.get("Last Updated"),
        })
    pages_m = _ESBD_TOTAL_PAGES_RE.search(html_text)
    total_pages = int(pages_m.group(1).replace(",", "")) if pages_m else None
    return rows, total_pages


def match_esbd_row(row: dict) -> tuple[str, str, str] | None:
    """Return (scope, match_method, match_term) for a parsed ESBD row.

    Title-keyword match wins over agency-number match. Starr terms
    beat RGV terms. Terms match on whole words only — a plain
    substring test would false-positive on e.g. "mission" inside
    "transmission". Returns None when nothing matches.
    """
    title = (row.get("title") or "").lower()
    for term in STARR_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", title):
            return ("starr", "title_keyword", term)
    for term in RGV_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", title):
            return ("rgv", "title_keyword", term)
    agency = _clean(row.get("agency_number"))
    if agency and agency in RGV_AGENCY_NUMBERS:
        return ("rgv", "agency_number", agency)
    return None


def label_esbd_row(obs: dict) -> str:
    if obs.get("solicitation_id") is not None \
            and obs.get("title") is not None \
            and obs.get("due_date") is not None \
            and obs.get("status") is not None:
        return "VERIFIED"
    return "REPORTED"


def build_esbd_observation(row: dict, scope: str, match_method: str,
                           match_term: str, source_url: str,
                           retrieved_at: str) -> dict:
    obs = {
        "leg": "esbd",
        "kind": "solicitation",
        "scope": scope,
        "match_method": match_method,
        "match_term": match_term,
        "solicitation_id": row.get("solicitation_id"),
        "title": row.get("title"),
        "due_date": row.get("due_date"),
        "due_time": row.get("due_time"),
        "agency_number": row.get("agency_number"),
        "status": row.get("status"),
        "posting_date": row.get("posting_date"),
        "created_date": row.get("created_date"),
        "last_updated": row.get("last_updated"),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs["label"] = label_esbd_row(obs)
    return obs


def _http_get_text(url: str, opener) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def _http_get_json(url: str, opener):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with opener(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_esbd(page_count: int = DEFAULT_ESBD_PAGES,
               opener=None) -> tuple[list[dict], dict]:
    """Scan the newest ``page_count`` ESBD listing pages.

    Returns (observations, leg_report). The report records total
    pages, pages actually scanned, rows scanned and the explicit
    partial-coverage caveat: this is a newest-first slice, not the
    site's own search (which is JS-only and unreachable from here).
    """
    open_fn = opener or urllib.request.urlopen
    retrieved_at = utcnow_iso()
    observations: list[dict] = []
    pages_scanned = 0
    rows_scanned = 0
    total_pages: int | None = None
    status = "OK"
    for page in range(1, page_count + 1):
        url = ESBD_URL if page == 1 else f"{ESBD_URL}?page={page}"
        try:
            text = _http_get_text(url, open_fn)
        except Exception as exc:  # network error: recorded, not raised
            status = f"ERROR: {type(exc).__name__}: {exc}"
            break
        rows, pages = parse_esbd_listing(text)
        if total_pages is None:
            total_pages = pages
        pages_scanned += 1
        rows_scanned += len(rows)
        for row in rows:
            match = match_esbd_row(row)
            if match is None:
                continue
            scope, method, term = match
            detail_url = (urllib.parse.urljoin(ESBD_URL + "/", row["url_path"])
                          if row.get("url_path") else ESBD_URL)
            observations.append(build_esbd_observation(
                row, scope, method, term, detail_url, retrieved_at))
    return observations, {
        "leg": "esbd",
        "source": "TxSmartBuy ESBD (Electronic State Business Daily)",
        "listing_url": ESBD_URL,
        "json_api": None,
        "json_api_note": "No machine API reachable: the ESBD.Service.ss "
                         "Suitelet answers HTTP 404 at every resolvable "
                         "path from this environment and ?keyword= / "
                         "?agency= params are ignored server-side "
                         "(verified 2026-11-26). Listing HTML parsed.",
        "status": status,
        "retrieved_at": retrieved_at,
        "total_pages": total_pages,
        "pages_scanned": pages_scanned,
        "rows_scanned": rows_scanned,
        "coverage": "partial: newest-first slice only, not a full search",
        "observations": len(observations),
    }


# ------------------------------------------------------------- Socrata legs

def _socrata_url(dataset: str, query: str) -> str:
    return f"{SOCRATA_BASE}/{dataset}.json?{query}"


def _socrata_count(dataset: str, where: str | None, opener) -> int | None:
    where_q = ("&$where=" + urllib.parse.quote(where)) if where else ""
    url = _socrata_url(
        dataset, "$select=count(*)" + where_q)
    try:
        rows = _http_get_json(url, opener)
        return int(rows[0]["count"])
    except Exception:
        return None


def label_dir_contract_row(obs: dict) -> str:
    if obs.get("contract_number") is not None \
            and obs.get("vendor_name") is not None \
            and obs.get("contract_start") is not None:
        return "VERIFIED"
    return "REPORTED"


def build_dir_contract_observation(row: dict, source_url: str,
                                   retrieved_at: str) -> dict:
    """Project one vipt-h4ye row. Contact emails/phones are dropped."""
    obs = {
        "leg": "dir",
        "kind": "active_cooperative_contract",
        "scope": "statewide_register",
        "rfo_number": _clean(row.get("rfo_number")),
        "rfo_description": _clean(row.get("rfo_description")),
        "contract_number": _clean(row.get("contract_number")),
        "vendor_name": _clean(row.get("primary_vendor_name")),
        "vendor_hub_status": _clean(row.get("primary_vendor_hub_status")),
        "reseller_name": _clean(row.get("reseller_name")),
        "reseller_hub_status": _clean(row.get("reseller_hub_status")),
        "contract_start": _clean(row.get("contract_start")),
        "contract_termination_date": _clean(
            row.get("contract_termination_date")),
        "contract_type": _clean(row.get("contract_type")),
        "contract_subtype": _clean(row.get("contract_subtype")),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs["label"] = label_dir_contract_row(obs)
    return obs


def label_dir_sale_row(obs: dict) -> str:
    if obs.get("customer_name") is not None \
            and obs.get("vendor_name") is not None \
            and obs.get("purchase_amount") is not None \
            and obs.get("contract_number") is not None:
        return "VERIFIED"
    return "REPORTED"


def build_dir_sale_observation(row: dict, source_url: str,
                               retrieved_at: str) -> dict:
    """Project one a743-wj72 Starr-customer purchase row.

    Customer contact names are dropped; only the customer entity,
    vendor, amounts and contract refs are emitted.
    """
    obs = {
        "leg": "dir",
        "kind": "starr_customer_purchase_fy2026",
        "scope": "starr",
        "fiscal_year": _clean(row.get("fiscal_year")),
        "customer_name": _clean(row.get("customer_name")),
        "customer_state": _clean(row.get("customer_state")),
        "customer_type": _clean(row.get("customer_type")),
        "vendor_name": _clean(row.get("vendor_name")),
        "purchase_amount": _to_float(row.get("purchase_amount")),
        "contract_number": _clean(row.get("contract_number")),
        "contract_category": _clean(row.get("contract_category")),
        "rfo_number": _clean(row.get("rfo_number")),
        "rfo_description": _clean(row.get("rfo_description")),
        "contract_type": _clean(row.get("contract_type")),
        "contract_subtype": _clean(row.get("contract_subtype")),
        "reporting_month": _clean(row.get("reporting_month")),
        "order_date": _clean(row.get("order_date")),
        "invoice_date": _clean(row.get("invoice_date")),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs["label"] = label_dir_sale_row(obs)
    return obs


def fetch_dir(sample_limit: int = DEFAULT_DIR_SAMPLE_LIMIT,
              max_sales_rows: int = DEFAULT_MAX_DIR_SALES_ROWS,
              opener=None) -> tuple[list[dict], dict]:
    """Fetch the DIR Socrata legs.

    Returns (observations, leg_report). The active-contracts leg
    records the full register size plus a sample of the most
    recently started contracts; the Starr-sales leg fetches every
    FY2026 purchase row whose customer name contains 'STARR'.
    """
    open_fn = opener or urllib.request.urlopen
    retrieved_at = utcnow_iso()
    observations: list[dict] = []
    report: dict = {
        "leg": "dir",
        "source": "TX Dept. of Information Resources via data.texas.gov "
                  "(Socrata, keyless)",
        "datasets": {
            "active_contracts": DIR_ACTIVE_DATASET,
            "fy2026_sales": DIR_SALES_DATASET,
        },
        "retrieved_at": retrieved_at,
        "status": "OK",
    }
    # --- active cooperative contracts register: size + recent sample
    active_count = _socrata_count(DIR_ACTIVE_DATASET, None, open_fn)
    report["active_contracts_total"] = active_count
    sample_url = _socrata_url(
        DIR_ACTIVE_DATASET,
        "$limit=" + str(sample_limit)
        + "&$order=" + urllib.parse.quote("contract_start DESC"))
    try:
        rows = _http_get_json(sample_url, open_fn)
        for row in rows:
            observations.append(build_dir_contract_observation(
                row, sample_url, retrieved_at))
        report["active_contracts_sampled"] = len(rows)
    except Exception as exc:
        report["status"] = f"ERROR: {type(exc).__name__}: {exc}"
        report["active_contracts_sampled"] = 0
    # --- FY2026 purchases by Starr County customers, full fetch
    starr_where = "upper(customer_name) like '%STARR%'"
    starr_count = _socrata_count(DIR_SALES_DATASET, starr_where, open_fn)
    report["starr_sales_total"] = starr_count
    sales_rows: list[dict] = []
    try:
        offset = 0
        while offset < max_sales_rows:
            page_url = _socrata_url(
                DIR_SALES_DATASET,
                "$limit=1000&$offset=" + str(offset)
                + "&$where=" + urllib.parse.quote(starr_where))
            page = _http_get_json(page_url, open_fn)
            if not page:
                break
            sales_rows.extend(page)
            offset += len(page)
            if len(page) < 1000:
                break
        for row in sales_rows:
            observations.append(build_dir_sale_observation(
                row, f"https://data.texas.gov/d/{DIR_SALES_DATASET}",
                retrieved_at))
        report["starr_sales_fetched"] = len(sales_rows)
        report["starr_sales_truncated"] = (
            starr_count is not None and len(sales_rows) < starr_count)
    except Exception as exc:
        report["status"] = f"ERROR: {type(exc).__name__}: {exc}"
        report["starr_sales_fetched"] = len(sales_rows)
    # per-customer totals, computed only from fetched rows
    by_customer: dict[str, dict] = {}
    for obs in observations:
        if obs["kind"] != "starr_customer_purchase_fy2026":
            continue
        name = obs["customer_name"] or "UNKNOWN"
        entry = by_customer.setdefault(
            name, {"rows": 0, "total_purchase_amount": 0.0})
        entry["rows"] += 1
        if obs["purchase_amount"] is not None:
            entry["total_purchase_amount"] += obs["purchase_amount"]
    report["starr_sales_by_customer"] = {
        name: {"rows": e["rows"],
               "total_purchase_amount": round(e["total_purchase_amount"], 2)}
        for name, e in sorted(by_customer.items())}
    report["observations"] = len(observations)
    return observations, report


# ------------------------------------------------------------ TxDOT lettings

def label_txdot_project_row(obs: dict) -> str:
    if obs.get("project_id") is not None \
            and obs.get("county") is not None \
            and obs.get("bids_open_date") is not None:
        return "VERIFIED"
    return "REPORTED"


def build_txdot_project_observation(project: dict, source_url: str,
                                    retrieved_at: str) -> dict:
    """Project one deduplicated TxDOT letting (one per project id)."""
    obs = {
        "leg": "txdot_lettings",
        "kind": "open_letting_project",
        "scope": "starr",
        "project_id": _clean(project.get("controlling_project_id_ccsj")),
        "county": _clean(project.get("county")),
        "highway": _clean(project.get("highway")),
        "project_classification": _clean(
            project.get("project_classification")),
        "let_type": _clean(project.get("let_type")),
        "district": _clean(project.get("district_division")),
        "bids_open_date": _clean(project.get("bids_will_be_opened_date")),
        "bid_receipt_until": _clean(
            project.get("bid_recieved_until_date_and")),
        "engineer_estimate": _to_float(
            project.get("sealed_engineer_s_estimate")),
        "bid_item_rows": project.get("_bid_item_rows"),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    obs["label"] = label_txdot_project_row(obs)
    return obs


def fetch_txdot_lettings(opener=None) -> tuple[list[dict], dict]:
    """Fetch TxDOT current lettings for Starr County + RGV context.

    Rows are bid line items; observations are deduplicated to one
    per distinct controlling project id. A zero Starr result is a
    real finding (no open Starr lettings in the rolling window),
    recorded as such — not an error.
    """
    open_fn = opener or urllib.request.urlopen
    retrieved_at = utcnow_iso()
    report: dict = {
        "leg": "txdot_lettings",
        "source": "TxDOT Official and Unofficial Bid Items via "
                  "data.texas.gov (Socrata, keyless)",
        "dataset": TXDOT_LETTINGS_DATASET,
        "retrieved_at": retrieved_at,
        "status": "OK",
    }
    observations: list[dict] = []
    try:
        total_projects = _socrata_count_distinct_projects(open_fn)
        report["distinct_projects_statewide"] = total_projects
        starr_rows = _http_get_json(_socrata_url(
            TXDOT_LETTINGS_DATASET,
            "$limit=5000&$where=" + urllib.parse.quote("county='Starr'")),
            open_fn)
        projects = _dedupe_txdot_projects(starr_rows)
        for project in projects:
            observations.append(build_txdot_project_observation(
                project,
                f"https://data.texas.gov/d/{TXDOT_LETTINGS_DATASET}",
                retrieved_at))
        report["starr_bid_item_rows"] = len(starr_rows)
        report["starr_projects"] = len(projects)
        # RGV context counts (line-item rows, not projects)
        context: dict[str, int | None] = {}
        for county in ("Hidalgo", "Cameron", "Willacy"):
            context[county] = _socrata_count(
                TXDOT_LETTINGS_DATASET, f"county='{county}'", open_fn)
        context["pharr_district_projects"] = \
            _socrata_count_distinct_projects(
                open_fn, where="district_division='Pharr'")
        report["rgv_context"] = context
    except Exception as exc:
        report["status"] = f"ERROR: {type(exc).__name__}: {exc}"
    report["observations"] = len(observations)
    return observations, report


def _socrata_count_distinct_projects(opener, where: str | None = None
                                     ) -> int | None:
    where_q = ("&$where=" + urllib.parse.quote(where)) if where else ""
    url = _socrata_url(
        TXDOT_LETTINGS_DATASET,
        "$select=" + urllib.parse.quote(
            "count(distinct controlling_project_id_ccsj)") + where_q)
    try:
        rows = _http_get_json(url, opener)
        return int(rows[0]["count_distinct_controlling_project_id_ccsj"])
    except Exception:
        return None


def _dedupe_txdot_projects(rows: list[dict]) -> list[dict]:
    """Collapse bid line-item rows to one dict per project id."""
    projects: dict[str, dict] = {}
    for row in rows:
        pid = _clean(row.get("controlling_project_id_ccsj")) \
            or _clean(row.get("project_id")) or "UNKNOWN"
        entry = projects.setdefault(pid, dict(row))
        entry["_bid_item_rows"] = entry.get("_bid_item_rows", 0) + 1
        # Keep the largest engineer estimate seen across line items.
        est = _to_float(row.get("sealed_engineer_s_estimate"))
        cur = _to_float(entry.get("sealed_engineer_s_estimate"))
        if est is not None and (cur is None or est > cur):
            entry["sealed_engineer_s_estimate"] = row.get(
                "sealed_engineer_s_estimate")
    return [projects[k] for k in sorted(projects)]


# ------------------------------------------------------------------- driver

def fetch_observations(esbd_pages: int = DEFAULT_ESBD_PAGES,
                       dir_sample_limit: int = DEFAULT_DIR_SAMPLE_LIMIT,
                       max_dir_sales_rows: int = DEFAULT_MAX_DIR_SALES_ROWS,
                       opener=None) -> dict:
    """Run all three legs and return the full result document."""
    retrieved_at = utcnow_iso()
    observations: list[dict] = []
    legs: list[dict] = []
    for obs, leg in (fetch_esbd(esbd_pages, opener=opener),
                     fetch_dir(dir_sample_limit, max_dir_sales_rows,
                               opener=opener),
                     fetch_txdot_lettings(opener=opener)):
        observations.extend(obs)
        legs.append(leg)
    by_label = {lab: sum(1 for o in observations if o["label"] == lab)
                for lab in ("VERIFIED", "REPORTED", "UNKNOWN")}
    by_leg = {}
    for leg in legs:
        by_leg[leg["leg"]] = leg.get("observations", 0)
    return {
        "sensor": "procurement-82",
        "source": "TxSmartBuy ESBD + TX DIR (data.texas.gov Socrata) + "
                  "TxDOT lettings (data.texas.gov Socrata)",
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": FIPS_STARR_COUNTY_TX,
        "esbd_listing_url": ESBD_URL,
        "dir_contracts_url": DIR_CONTRACTS_URL,
        "datasets": {
            "dir_active_contracts": DIR_ACTIVE_DATASET,
            "dir_fy2026_sales": DIR_SALES_DATASET,
            "txdot_lettings": TXDOT_LETTINGS_DATASET,
        },
        "legs": legs,
        "summary": {
            "observations_total": len(observations),
            "by_label": by_label,
            "by_leg": by_leg,
            "starr_scope": sum(1 for o in observations
                               if o.get("scope") == "starr"),
            "rgv_scope": sum(1 for o in observations
                             if o.get("scope") == "rgv"),
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch TX procurement & DIR contract data, "
                    "Starr County / RGV (sensor #82).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--esbd-pages", type=int, default=DEFAULT_ESBD_PAGES,
                    help="Newest ESBD listing pages to scan (default 5).")
    ap.add_argument("--dir-sample-limit", type=int,
                    default=DEFAULT_DIR_SAMPLE_LIMIT,
                    help="DIR active-contract sample rows (default 50).")
    ap.add_argument("--max-dir-sales-rows", type=int,
                    default=DEFAULT_MAX_DIR_SALES_ROWS,
                    help="Cap on DIR FY2026 Starr sales rows (default 1000).")
    args = ap.parse_args(argv)
    result = fetch_observations(
        esbd_pages=args.esbd_pages,
        dir_sample_limit=args.dir_sample_limit,
        max_dir_sales_rows=args.max_dir_sales_rows)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['summary']['starr_scope']} Starr scope) "
              f"across {len(result['legs'])} legs")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
