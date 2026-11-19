#!/usr/bin/env python3
"""
Patent Radar — live-data adapter (BUILD-20261117-001, Task 2; ODP wiring
added 2026-11-17, adapter v1.1.0; vintage/golden-era profile added
2026-11-17, adapter v1.2.0).

Pulls granted US utility patents, computes each patent's status itself
(expiration = filing date + 20 years; "expiring" = expires within 24 months),
maps results onto the exact record contract in data/sample_patents.json, and
writes data/live_patents.json in the same file shape so the module
(with only the PATENT_RADAR_DATA env switch) can rank live data.

LIVE SOURCE — USPTO Open Data Portal (ODP), WIRED AND VERIFIED 2026-11-17:
  * The legacy PatentsView PatentSearch API (search.patentsview.org) is
    RETIRED (migrated to ODP 2026-03-20; old keys incompatible). The legacy
    query path below is kept only so the old failure mode stays explicit.
  * ODP Patent File Wrapper search: POST
    https://api.uspto.gov/api/v1/patent/applications/search
    Auth: the account's ODP API key in the X-API-KEY header. In this build
    the key is NEVER handled directly: requests go through the registered
    connector's surrogate credential exchange
    (dynamic_credentials.add_surrogate_to_request, connection
    custom.uspto-odp), which places the key on the outgoing request.
  * SEARCH SYNTAX (solved 2026-11-17; the Getting Started example body with
    "q" as an OBJECT returns HTTP 400 — "q" must be a STRING):
        {
          "q": "applicationMetaData.inventionTitle:garden",
          "filters": [{"name": "applicationMetaData.applicationTypeCode",
                       "value": ["UTL"]},
                      {"name": "applicationMetaData.applicationStatusDescriptionText",
                       "value": ["Patented Case"]}],
          "rangeFilters": [{"field": "applicationMetaData.filingDate",
                            "valueFrom": "2000-01-01",
                            "valueTo": "2006-11-16"}],
          "sort": [{"field": "applicationMetaData.filingDate", "order": "asc"}],
          "pagination": {"offset": 0, "limit": 4}
        }
    Response: {"count": N, "patentFileWrapperDataBag": [wrapper, ...]} where
    each wrapper carries applicationNumberText, applicationMetaData
    (patentNumber, inventionTitle, filingDate, grantDate,
    applicationTypeLabelName/Code, applicationStatusDescriptionText,
    cpcClassificationBag) and eventDataBag (prosecution/maintenance events).
    GET with a free-text ?q= parameter also works. ODP throttling: burst 1 —
    requests must be sequential.
  * Maintenance-fee lapse: applications whose status description is
    "Patent Expired Due to NonPayment of Maintenance Fees Under 37 CFR 1.362",
    or whose eventDataBag carries a patent-expired event, are EXPIRED by
    evidence even when filing+20y is still in the future.

GPT review patches applied (RESULT-BUILD-20261117-001-GPT):
  * Filing date + 20y is a PROVISIONAL US utility-term estimate only
    (35 U.S.C. 154), labeled "filing+20y provisional". PTA/PTE, terminal
    disclaimers, continuations and priority dates are NOT accounted for.
    Maintenance-fee events ARE now read from the ODP file wrapper (above).
  * Uncertain => REVIEW_REQUIRED, never "expired". Non-US jurisdiction,
    non-utility patent type, missing/invalid filing date, or an application
    (not a grant) all land in the safe "filing" bucket with review_required.
  * Provenance: versioned raw -> normalized record, source URL,
    retrieved_at UTC, jurisdiction, status_method, uncertainty.
  * Idempotent atomic writes (temp file + os.replace), --dry-run, and no
    outbound call in offline/fixture mode.
  * Scores are heuristics, never legal clearance. This radar is an IDEA
    ENGINE, not a legal-status authority.

VINTAGE PROFILE (--profile vintage, v1.2.0): a DESIGN hunt over golden-era
grants (grant dates 1920–1989), not a lapse hunt — everything of that era
is expired by term. The ODP file-wrapper index carries NO filing dates
before 2001 and holds pre-1990 grants only as sparse "old case" tracking
records (measured 2026-11-17: 0 records with grant dates in the
1920s–1950s or 1990s; 35 in the 1960s, 1,417 in the 1970s, 18 in the
1980s; only 2 design patents in 1960–1989). The pull therefore pages
through EVERY old-case record in the grant-date range and screens titles
locally against vintage consumer-product categories. Era is keyed to
GRANT date (the only reliable date on these records); expiration is a
term estimate — filing+20y (utility) / filing+14y (design) when a filing
date is on record, else grant+17y (utility, the pre-1995 term ran 17
years from grant) / grant+14y (design). status_method says so verbatim:
"term (vintage, pre-1990 filing)".

Usage:
    python patent_radar_live.py --source odp            # real live pull (ODP)
    python patent_radar_live.py --source odp --profile vintage --out data/live_patents_vintage.json
    python patent_radar_live.py --source odp --dry-run  # pull + print, no write
    python patent_radar_live.py --odp-fixture tests/fixtures/odp_search_response.json
    python patent_radar_live.py --fixture tests/fixtures/patentsview_response.json
    PATENT_RADAR_OFFLINE=1 python patent_radar_live.py --source odp   # refused

Env: PATENT_RADAR_OFFLINE=1 (refuse any network fetch),
     PATENTSVIEW_API_KEY (legacy, retired — no longer used for live data).
     The ODP key itself is held by the connector vault and is never read
     from the environment or written anywhere by this adapter.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ADAPTER_VERSION = "1.2.0"
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "data" / "live_patents.json"
LEGACY_API_URL = "https://search.patentsview.org/api/v1/patent/"
LEGACY_DOCS_URL = "https://search.patentsview.org/docs/"
ODP_TRANSITION_URL = "https://data.uspto.gov/support/transition-guide/patentsview"
ODP_GETTING_STARTED_URL = "https://data.uspto.gov/apis/getting-started"
ODP_SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
ODP_APP_URL = "https://api.uspto.gov/api/v1/patent/applications/"
ODP_CONNECTOR = "custom.uspto-odp"
ODP_ALLOWED_HOSTS = ["api.uspto.gov", "data.uspto.gov"]
LAPSED_STATUS_PREFIX = "Patent Expired Due to NonPayment of Maintenance Fees"

STATUS_METHOD = (
    "provisional US utility term: expiration = filing_date + 20 years "
    "(35 U.S.C. 154). PTA/PTE, terminal disclaimers, maintenance-fee events, "
    "continuations and priority dates NOT accounted for. 'expiring' = expires "
    "within 24 months of the run date. NOT a legal determination."
)
ODP_STATUS_METHOD = (
    "filing+20y provisional (USPTO ODP Patent File Wrapper): expiration = "
    "filing_date + 20 years (35 U.S.C. 154); a maintenance-fee lapse "
    "evidenced by the ODP application status or an expiration event in "
    "eventDataBag overrides to 'expired'. 'expiring' = expiration within "
    "24 months of the run date. PTA/PTE, terminal disclaimers, continuations "
    "and priority dates NOT checked. NOT a legal determination."
)
VINTAGE_STATUS_METHOD = (
    "term (vintage, pre-1990 filing): every patent of this era is expired "
    "by term today — utility patents ran 20 years from filing (17 years "
    "from grant under the pre-1995 rule), design patents 14 years. "
    "expiration_date is a term ESTIMATE: filing+20y (utility) / filing+14y "
    "(design) when a filing date is on record; for ODP old-case records "
    "without one, grant+17y (utility) / grant+14y (design) from the grant "
    "date. Era is keyed to grant date 1920–1989 because the ODP "
    "file-wrapper index carries no filing dates before 2001. NOT a legal "
    "determination."
)
VINTAGE_GRANT_FROM = "1920-01-01"
VINTAGE_GRANT_TO = "1989-12-31"
EXPIRING_WINDOW_MONTHS = 24

# CPC prefix -> owner-facing domain (heuristic label only). Longer prefixes
# are matched first (see _domain_for).
_CPC_DOMAIN = {
    "A01G": "garden / horticulture",
    "A01K": "pet / animal care",
    "A01": "agriculture",
    "A21": "food processing",
    "A23": "food / agriculture",
    "A45": "personal gear / carriers",
    "A46": "home / brushes",
    "A47L": "cleaning appliances",
    "A47": "home / furniture",
    "A63": "toys / games",
    "B05": "spraying / dispensing",
    "B08": "cleaning",
    "B25": "workshop tools",
    "B26": "cutting tools",
    "B65": "packaging / containers",
    "D06": "laundry",
    "E03": "plumbing / water",
    "E04": "building / fencing",
    "F16": "mechanical hardware",
    "F21": "lighting",
    "F24": "heating / cooking",
    "F25": "cooling / refrigeration",
}

# Title keyword -> domain fallback when no CPC matches.
_TITLE_DOMAIN = [
    ("garden", "garden / horticulture"), ("planter", "garden / horticulture"),
    ("irrigation", "garden / irrigation"), ("sprinkler", "garden / irrigation"),
    ("feeder", "pet / outdoor"), ("kitchen", "home / kitchen"),
    ("storage", "home / storage"), ("organizer", "home / storage"),
    ("shower", "plumbing / bath"), ("faucet", "plumbing / bath"),
    ("lamp", "lighting"), ("tool", "workshop tools"),
    # Marketable-smalls pull (2026-11-17): vintage-lighter class of goods.
    ("lighter", "smoking accessories"), ("ashtray", "smoking accessories"),
    ("cigar", "smoking accessories"), ("cigarette", "smoking accessories"),
    ("smoking", "smoking accessories"), ("incense", "home / fragrance"),
    ("candle", "home / fragrance"), ("corkscrew", "bar / kitchen smalls"),
    ("opener", "bar / kitchen smalls"), ("flask", "personal gear / carriers"),
    ("keychain", "personal gear / carriers"), ("clip", "personal gear / carriers"),
    ("multitool", "workshop tools"),
    # Vintage / golden-era pull (2026-11-17): old-case records carry no CPC
    # bag, so title keywords do all the domain work for that profile.
    ("clock", "home / timepieces"), ("radio", "vintage home electronics"),
    ("television", "vintage home electronics"), ("phonograph", "vintage home electronics"),
    ("fan", "home appliances"), ("toaster", "home / kitchen"),
    ("coffee", "home / kitchen"), ("mixer", "home / kitchen"),
    ("blender", "home / kitchen"), ("kettle", "home / kitchen"),
    ("stove", "home / kitchen"), ("teapot", "home / kitchen"),
    ("shaver", "personal care appliances"), ("dryer", "personal care appliances"),
    ("camera", "photo / optics"), ("projector", "photo / optics"),
    ("binocular", "photo / optics"), ("typewriter", "vintage office machines"),
    ("calculator", "vintage office machines"), ("telephone", "vintage communications"),
    ("game", "toys / games"), ("toy", "toys / games"), ("doll", "toys / games"),
    ("puzzle", "toys / games"), ("lantern", "lighting"),
    ("sewing", "home / sewing"), ("vacuum", "cleaning appliances"),
    ("chair", "furniture"), ("sofa", "furniture"), ("cabinet", "furniture"),
    ("barometer", "instruments"), ("bicycle", "personal gear / carriers"),
]

REQUIRED_KEYS = {
    "patent_number", "title", "status", "expiration_date", "domain",
    "printable_3d", "demand_signal", "manufacture_profile",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_date(s) -> date | None:
    if not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28 in a non-leap target year
        return d.replace(year=d.year + years, day=28)


def _months_between(a: date, b: date) -> float:
    """Approximate months from a to b (b after a => positive)."""
    return (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.44


def compute_status(filing: date | None, patent_type: str, jurisdiction: str,
                   today: date) -> tuple[str, date | None, str | None]:
    """Return (status, expiration_date, uncertainty_note).

    Uncertain inputs never yield 'expired'/'expiring' — they land in the safe
    'filing' bucket with review_required (GPT patch).
    """
    if (jurisdiction or "").upper() not in ("US", "USA", "UNITED STATES"):
        return "filing", None, (
            "non-US jurisdiction %r: US 20-year term rule does not apply; "
            "status not computed" % jurisdiction)
    if (patent_type or "").lower() not in ("utility", "utility patent"):
        return "filing", None, (
            "patent type %r is not a US utility patent; 20-year term rule "
            "does not apply" % patent_type)
    if filing is None:
        return "filing", None, (
            "filing date missing or unparseable; expiration could not be computed")
    expiry = _add_years(filing, 20)
    if expiry < today:
        return "expired", expiry, None
    if _months_between(today, expiry) <= EXPIRING_WINDOW_MONTHS:
        return "expiring", expiry, None
    return "in-force", expiry, "expires in more than 24 months; not an opportunity window"


def _filing_date(rec: dict) -> date | None:
    """Filing date, trying the field names the legacy API used.

    NOTE: the exact legacy field name could not be re-verified 2026-11-17
    (docs offline, endpoint retired). Lookup order is documented here so a
    future re-check against the ODP reintroduced API can correct it.
    """
    for key in ("filing_date", "app_date", "application_date"):
        d = _parse_date(rec.get(key))
        if d is not None:
            return d
    app = rec.get("application") or {}
    if isinstance(app, dict):
        d = _parse_date(app.get("filing_date") or app.get("app_date"))
        if d is not None:
            return d
    apps = rec.get("applications") or []
    if isinstance(apps, list) and apps and isinstance(apps[0], dict):
        d = _parse_date(apps[0].get("filing_date") or apps[0].get("app_date"))
        if d is not None:
            return d
    return None


def _cpc_domain(rec: dict) -> str:
    for key in ("cpc_section_id", "cpc_class", "cpc_subsection_id"):
        v = (rec.get(key) or "").upper()
        for prefix, domain in _CPC_DOMAIN.items():
            if v.startswith(prefix):
                return domain
    cpcs = rec.get("cpcs") or []
    if isinstance(cpcs, list) and cpcs:
        first = cpcs[0] if isinstance(cpcs[0], dict) else {}
        v = str(first.get("cpc_section_id") or first.get("cpc_group_id") or "").upper()
        for prefix, domain in _CPC_DOMAIN.items():
            if v.startswith(prefix):
                return domain
    return "general product"


def _domain_for(cpc_codes: list[str], title: str) -> str:
    """Domain from the first matching CPC prefix, else title keywords."""
    cleaned = [str(c).replace(" ", "").upper() for c in cpc_codes or []]
    for code in cleaned:
        for prefix in sorted(_CPC_DOMAIN, key=len, reverse=True):
            if code.startswith(prefix):
                return _CPC_DOMAIN[prefix]
    t = (title or "").lower()
    for kw, domain in _TITLE_DOMAIN:
        if kw in t:
            return domain
    return "general product"


def normalize_record(raw: dict, today: date,
                     source_url: str = LEGACY_API_URL) -> tuple[dict | None, str | None]:
    """Map one raw (legacy-shaped) API record onto the radar's contract record.

    Returns (record, error). Invalid records are rejected with a reason,
    never silently coerced (GPT negative-test patch).
    """
    num = (raw.get("patent_number") or "").strip()
    if not num:
        return None, "missing patent_number"
    title = (raw.get("patent_title") or raw.get("title") or "").strip()
    if not title:
        return None, "missing patent_title for %s" % num
    jurisdiction = (raw.get("jurisdiction") or raw.get("country") or "US").strip()
    ptype = (raw.get("patent_type") or "utility").strip()
    is_application = str(raw.get("record_kind") or "").lower() in ("application", "app") \
        or str(raw.get("patent_type") or "").lower() in ("application",)
    if is_application:
        status, expiry, uncertainty = "filing", None, (
            "application, not a grant: trend/whitespace signal only, "
            "do not copy a live application")
        filing = _filing_date(raw)
    else:
        filing = _filing_date(raw)
        status, expiry, uncertainty = compute_status(filing, ptype, jurisdiction, today)
    if status == "in-force":
        return None, "in-force until %s (>24 months out); not an opportunity window" % expiry
    # Heuristic defaults for fields the API cannot supply; labeled as such.
    # demand_signal "steady" is the module's neutral keyword (0.6).
    # manufacture_profile "medium" forces a human look at the figures.
    # printable_3d False until the figures are checked.
    rec = {
        "patent_number": num,
        "title": title,
        "status": status,
        "expiration_date": expiry.isoformat() if expiry else None,
        "domain": _cpc_domain(raw),
        "printable_3d": False,
        "demand_signal": "steady (default — not measured live)",
        "manufacture_profile": "medium: verify from patent figures",
        "jurisdiction": jurisdiction.upper() if jurisdiction else "US",
        "patent_type": ptype,
        "filing_date": filing.isoformat() if filing else None,
        "grant_date": (raw.get("patent_date") or raw.get("grant_date") or None),
        "status_method": STATUS_METHOD,
        "status_uncertainty": uncertainty,
        "review_required": True,
        "review_reason": (
            "Verify legal status on USPTO Patent Center / Google Patents "
            "before building or licensing. Status computed provisionally "
            "from filing date + 20 years; PTA/PTE, terminal disclaimers, "
            "maintenance-fee events and continuations NOT checked."
            + ((" Uncertainty: %s" % uncertainty) if uncertainty else "")),
        "provenance": {
            "adapter_version": ADAPTER_VERSION,
            "source": "PatentsView PatentSearch API (legacy)" if not is_application
                      else "PatentsView PatentSearch API, application record (legacy)",
            "source_url": source_url,
            "record_kind": "application" if is_application else "grant",
        },
    }
    missing = REQUIRED_KEYS - set(rec.keys())
    if missing:
        return None, "record %s missing contract keys %s" % (num, sorted(missing))
    return rec, None


# ----------------------------------------------------------------------------
# USPTO ODP (live) — fetch + normalize
# ----------------------------------------------------------------------------

def _lapse_evidence(wrapper: dict, status_text: str
                    ) -> tuple[bool, str | None, date | None]:
    """Maintenance-fee lapse evidence from the ODP wrapper.

    Returns (lapsed, evidence note, lapse date if an event carries one).
    Evidence = the application's own status description, or an expiration
    event in eventDataBag.
    """
    lapse_date = None
    event_note = None
    for ev in wrapper.get("eventDataBag") or []:
        desc = str(ev.get("eventDescriptionText") or "")
        low = desc.lower()
        code = str(ev.get("eventCode") or "")
        if code == "EXP." or "patent expired" in low or "expire patent" in low \
                or ("expired" in low and "maintenance" in low) or "lapse" in low:
            lapse_date = _parse_date(ev.get("eventDate"))
            event_note = "eventDataBag event %s (%s): %s" % (
                ev.get("eventCode") or "?", ev.get("eventDate") or "date unknown", desc)
            break
    if (status_text or "").startswith(LAPSED_STATUS_PREFIX):
        return True, "ODP application status: %s" % status_text, lapse_date
    if event_note:
        return True, event_note, lapse_date
    return False, None, None


# Title-keyword search also matches non-consumer fields (medical irrigation,
# data storage, telecom feeders). These title markers screen those out of the
# ODP pull; screened records land in _meta.rejected with the reason, never
# silently dropped. Heuristic, documented in BUILD_REPORT.md.
OFF_DOMAIN_TITLE_TERMS = [
    "surgical", "arthroscop", "aspiration", "catheter", "endoscop",
    "dialysis", "medical", "patient", "dental", "oscilloscope", "antenna",
    "optical line", "wafer", "semiconductor", "lithograph", "fuel cell",
    "storage device", "data storage", "memory access",
    "communication apparatus", "image processing", "stacked sheets",
    "compact disc", "bean line", "pharmaceutical",
]


def normalize_odp_record(wrapper: dict, today: date,
                         source_url: str = ODP_SEARCH_URL
                         ) -> tuple[dict | None, str | None]:
    """Map one ODP Patent File Wrapper record onto the contract record."""
    md = wrapper.get("applicationMetaData") or {}
    patent_number = str(md.get("patentNumber") or "").replace(",", "").strip()
    if not patent_number:
        return None, "missing patentNumber (application %s)" % (
            wrapper.get("applicationNumberText") or "?")
    num = "US" + patent_number
    title = str(md.get("inventionTitle") or "").strip()
    if not title:
        return None, "missing inventionTitle for %s" % num
    low_title = title.lower()
    for term in OFF_DOMAIN_TITLE_TERMS:
        if term in low_title:
            return None, ("off-domain title screen: %r in title (keyword "
                          "search pulled a non-consumer record)" % term)
    ptype = str(md.get("applicationTypeLabelName") or "").strip() or "utility"
    filing = _parse_date(md.get("filingDate"))
    status_text = str(md.get("applicationStatusDescriptionText") or "")
    lapsed, lapse_note, lapse_date = _lapse_evidence(wrapper, status_text)
    status, expiry, uncertainty = compute_status(filing, ptype, "US", today)
    if lapsed:
        # Evidence beats the term estimate: the patent died early for
        # non-payment even if filing+20y is still ahead. When the wrapper's
        # events date the lapse, that date is the effective expiration;
        # otherwise the term estimate stands and the note says so.
        status = "expired"
        term = _add_years(filing, 20) if filing is not None else None
        note = "Maintenance-fee lapse evidenced (%s)." % lapse_note
        if lapse_date is not None:
            expiry = lapse_date
            uncertainty = note + (
                " Effective expiration shown is the lapse event date; "
                "provisional term end was %s." % term if term else
                " Effective expiration shown is the lapse event date.")
        else:
            uncertainty = (note + (" Term estimate also computed: %s." % uncertainty)
                           if uncertainty else note)
            if expiry is None:
                expiry = term
    if status == "in-force":
        return None, "in-force until %s (>24 months out); not an opportunity window" % expiry
    cpcs = md.get("cpcClassificationBag") or []
    rec = {
        "patent_number": num,
        "title": title,
        "status": status,
        "expiration_date": expiry.isoformat() if expiry else None,
        "domain": _domain_for(cpcs, title),
        "printable_3d": False,
        "demand_signal": "steady (default — not measured live)",
        "manufacture_profile": "medium: verify from patent figures",
        "jurisdiction": "US",
        "patent_type": ptype,
        "filing_date": filing.isoformat() if filing else None,
        "grant_date": md.get("grantDate"),
        "application_number": wrapper.get("applicationNumberText"),
        "odp_status_text": status_text or None,
        "lapse_evidence": lapse_note,
        "status_method": ODP_STATUS_METHOD,
        "status_uncertainty": uncertainty,
        "review_required": True,
        "review_reason": (
            "Verify legal status on USPTO Patent Center / Google Patents "
            "before building or licensing. Status computed provisionally "
            "from filing date + 20 years (ODP file wrapper data); PTA/PTE, "
            "terminal disclaimers and continuations NOT checked."
            + ((" Uncertainty: %s" % uncertainty) if uncertainty else "")),
        "provenance": {
            "adapter_version": ADAPTER_VERSION,
            "source": "USPTO Open Data Portal — Patent File Wrapper API",
            "source_url": source_url,
            "record_kind": "grant",
            "application_number": wrapper.get("applicationNumberText"),
        },
    }
    missing = REQUIRED_KEYS - set(rec.keys())
    if missing:
        return None, "record %s missing contract keys %s" % (num, sorted(missing))
    return rec, None


# ----------------------------------------------------------------------------
# Vintage / golden-era profile (v1.2.0) — design hunt over 1920–1989 grants
# ----------------------------------------------------------------------------

# Title keyword -> vintage category. A record joins the vintage dataset only
# when its title names a consumer product of the era (the ODP old-case subset
# is mostly industrial/electronics records). Screened-out records are counted
# and listed in _meta.category_screen, never silently dropped.
VINTAGE_CATEGORY_KEYWORDS = [
    ("lighter", "lighters & smoking"), ("ashtray", "lighters & smoking"),
    ("cigarette", "lighters & smoking"), ("cigar", "lighters & smoking"),
    ("clock", "clocks & instruments"), ("barometer", "clocks & instruments"),
    ("radio", "radios & audio"), ("phonograph", "radios & audio"),
    ("television", "television"), ("telephone", "telephones"),
    ("lamp", "lamps & lighting"), ("lantern", "lamps & lighting"),
    ("fan", "fans & appliances"), ("toaster", "kitchen appliances"),
    ("coffee", "kitchen appliances"), ("mixer", "kitchen appliances"),
    ("blender", "kitchen appliances"), ("kettle", "kitchen appliances"),
    ("stove", "kitchen appliances"), ("teapot", "kitchen appliances"),
    ("iron", "kitchen appliances"), ("shaver", "personal care"),
    ("dryer", "personal care"), ("scale", "home & instruments"),
    ("camera", "cameras & optics"), ("projector", "cameras & optics"),
    ("binocular", "cameras & optics"), ("typewriter", "office machines"),
    ("calculator", "office machines"), ("game", "games & toys"),
    ("toy", "games & toys"), ("doll", "games & toys"),
    ("puzzle", "games & toys"), ("wrench", "hand tools"),
    ("drill", "hand tools"), ("tool", "hand tools"),
    ("sewing", "sewing"), ("chair", "furniture"), ("sofa", "furniture"),
    ("cabinet", "furniture"), ("table", "furniture"),
    ("mirror", "furniture & decor"), ("vacuum", "cleaning appliances"),
    ("heater", "fans & appliances"), ("bicycle", "bicycles & gear"),
    ("flask", "personal gear"), ("keychain", "personal gear"),
]

# Extra junk markers for the vintage screen: component/industrial titles
# that collide with category keywords (e.g. "TELEVISION ... CIRCUIT").
VINTAGE_OFF_DOMAIN_EXTRA = [
    "cathode", "circuit", "transistor", "zeolite", "catalyst",
    "electron tube", "semiconductor", "printed circuit", "waveguide",
    "implant",
]


def vintage_category(title: str) -> str | None:
    """Vintage category for a title, or None when it names no consumer
    product of the era (or names a component/industrial record).

    Keywords match on word boundaries: substring matching lets "lamp"
    fire on every industrial CLAMP and "table" on STABLE and TABLETS —
    the first live sweep's kept set was full of exactly those collisions.
    """
    t = (title or "").lower()
    for term in OFF_DOMAIN_TITLE_TERMS + VINTAGE_OFF_DOMAIN_EXTRA:
        if term in t:
            return None
    for kw, category in VINTAGE_CATEGORY_KEYWORDS:
        if re.search(r"\b%s\b" % re.escape(kw), t):
            return category
    return None


def normalize_odp_vintage_record(wrapper: dict, today: date,
                                 source_url: str = ODP_SEARCH_URL
                                 ) -> tuple[dict | None, str | None]:
    """Map one ODP old-case (grant-era 1920–1989) record onto the contract.

    Everything of this era is expired by term; the only questions are the
    patent TYPE (design vs utility — the look is the product for designs)
    and the term-estimate basis. `effectiveFilingDate` on old-case records
    is a file-tracking artifact (observed: 1986-01-27 on patents granted
    in 1978/1979) and is deliberately NOT used.
    """
    md = wrapper.get("applicationMetaData") or {}
    raw_number = str(md.get("patentNumber") or "").replace(",", "").strip()
    if not raw_number:
        return None, "missing patentNumber (application %s)" % (
            wrapper.get("applicationNumberText") or "?")
    num = "US" + raw_number
    title = str(md.get("inventionTitle") or "").strip()
    if not title:
        return None, "missing inventionTitle for %s" % num
    low_title = title.lower()
    for term in OFF_DOMAIN_TITLE_TERMS + VINTAGE_OFF_DOMAIN_EXTRA:
        if term in low_title:
            return None, ("off-domain title screen: %r in title (component/"
                          "industrial record, not a consumer product)" % term)
    type_code = str(md.get("applicationTypeCode") or "").strip().upper()
    # The patent number is authoritative for type: design patents carry a
    # "D" number even when an old-case record's type code disagrees
    # (observed in the UTL-filtered sweep).
    is_design = type_code == "DES" or raw_number.upper().startswith("D")
    if is_design:
        ptype = "design"
    elif type_code in ("UTL", ""):
        ptype = "utility"
    else:
        ptype = str(md.get("applicationTypeLabelName") or type_code).strip()
        return _vintage_uncertain_record(
            wrapper, md, num, title, ptype, type_code, source_url,
            "patent type code %r is neither utility nor design; term rule "
            "not applied" % type_code)
    filing = _parse_date(md.get("filingDate"))
    grant = _parse_date(md.get("grantDate"))
    uncertainty = None
    if filing is not None:
        years = 14 if is_design else 20
        expiry = _add_years(filing, years)
        term_basis = "filing+%dy (term estimate from the filing date on record)" % years
    elif grant is not None:
        years = 14 if is_design else 17
        expiry = _add_years(grant, years)
        term_basis = ("grant+%dy (pre-1995 term ran from grant; filing date "
                      "not on the ODP old-case record)" % years)
        uncertainty = (
            "Filing date not on record: the ODP file-wrapper index carries "
            "no pre-2001 filing dates, and the effectiveFilingDate on "
            "old-case records is a file-tracking artifact. Expiration is "
            "estimated from the grant date under the pre-1995 term rule.")
    else:
        return _vintage_uncertain_record(
            wrapper, md, num, title, ptype, type_code, source_url,
            "no filing or grant date on record; term cannot be estimated")
    if expiry >= today:
        return _vintage_uncertain_record(
            wrapper, md, num, title, ptype, type_code, source_url,
            "term estimate %s is not in the past; era assumption failed, "
            "verify manually" % expiry)
    cpcs = md.get("cpcClassificationBag") or []
    rec = {
        "patent_number": num,
        "title": title,
        "status": "expired",
        "expiration_date": expiry.isoformat(),
        "domain": _domain_for(cpcs, title),
        "printable_3d": False,
        "demand_signal": "steady (default — not measured live)",
        "manufacture_profile": "medium: verify from patent figures",
        "jurisdiction": "US",
        "patent_type": ptype,
        "application_type_code": type_code or None,
        "filing_date": filing.isoformat() if filing else None,
        "grant_date": md.get("grantDate"),
        "application_number": wrapper.get("applicationNumberText"),
        "odp_status_text": str(md.get("applicationStatusDescriptionText") or "") or None,
        "term_basis": term_basis,
        "status_method": VINTAGE_STATUS_METHOD,
        "status_uncertainty": uncertainty,
        "review_required": True,
        "review_reason": (
            "Verify legal status on USPTO Patent Center / Google Patents "
            "before building or selling. Vintage record: expired by term "
            "by construction of the era; expiration_date is a term "
            "estimate (%s). Pre-1990 ODP records are thin (bibliographic "
            "fields only, abstracts spotty). Trademark/trade-dress and "
            "later improvement patents are separate checks."
            % term_basis),
        "provenance": {
            "adapter_version": ADAPTER_VERSION,
            "source": "USPTO Open Data Portal — Patent File Wrapper API (old-case records)",
            "source_url": source_url,
            "record_kind": "grant",
            "application_number": wrapper.get("applicationNumberText"),
        },
    }
    missing = REQUIRED_KEYS - set(rec.keys())
    if missing:
        return None, "record %s missing contract keys %s" % (num, sorted(missing))
    return rec, None


def _vintage_uncertain_record(wrapper, md, num, title, ptype, type_code,
                              source_url, uncertainty):
    """Safe 'filing' bucket for a vintage record whose term cannot be
    computed — never labeled expired on a guess (GPT patch)."""
    cpcs = md.get("cpcClassificationBag") or []
    filing = _parse_date(md.get("filingDate"))
    rec = {
        "patent_number": num,
        "title": title,
        "status": "filing",
        "expiration_date": None,
        "domain": _domain_for(cpcs, title),
        "printable_3d": False,
        "demand_signal": "steady (default — not measured live)",
        "manufacture_profile": "medium: verify from patent figures",
        "jurisdiction": "US",
        "patent_type": ptype,
        "application_type_code": type_code or None,
        "filing_date": filing.isoformat() if filing else None,
        "grant_date": md.get("grantDate"),
        "application_number": wrapper.get("applicationNumberText"),
        "odp_status_text": str(md.get("applicationStatusDescriptionText") or "") or None,
        "term_basis": None,
        "status_method": VINTAGE_STATUS_METHOD,
        "status_uncertainty": uncertainty,
        "review_required": True,
        "review_reason": (
            "Verify legal status on USPTO Patent Center / Google Patents. "
            "Vintage record held in the review bucket: %s" % uncertainty),
        "provenance": {
            "adapter_version": ADAPTER_VERSION,
            "source": "USPTO Open Data Portal — Patent File Wrapper API (old-case records)",
            "source_url": source_url,
            "record_kind": "grant",
            "application_number": wrapper.get("applicationNumberText"),
        },
    }
    return rec, None


def fetch_odp_vintage(pause: float = 0.6, page: int = 50, cap: int = 1600,
                      today: date | None = None) -> tuple[list[dict], list[dict]]:
    """Page through EVERY ODP old-case record with a grant date in
    1920–1989 (the index holds only ~1.5k) and return (raw wrappers, log).

    Sequential requests only (ODP burst limit is 1 per key). The design
    query runs first; the utility sweep follows, ascending by grant date,
    with a descending top-up if pagination under-collects (sort stability
    on old-case records is not guaranteed).
    """
    if os.environ.get("PATENT_RADAR_OFFLINE") == "1":
        raise RuntimeError("PATENT_RADAR_OFFLINE=1: network fetch refused")
    rng = [{"field": "applicationMetaData.grantDate",
            "valueFrom": VINTAGE_GRANT_FROM, "valueTo": VINTAGE_GRANT_TO}]
    raw, seen, log = [], set(), []

    def run(label, body):
        try:
            payload = _odp_post_search(body)
        except RuntimeError as e:
            if "HTTP 404" in str(e):
                log.append({"label": label, "count": 0, "returned": 0,
                            "added": 0, "note": "no matching records (HTTP 404)"})
                time.sleep(pause)
                return 0, 0
            raise
        bag = payload.get("patentFileWrapperDataBag") or []
        added = 0
        for wrapper in bag:
            k = _odp_key(wrapper)
            if k and k not in seen:
                seen.add(k)
                raw.append(wrapper)
                added += 1
        log.append({"label": label, "count": payload.get("count"),
                    "returned": len(bag), "added": added})
        time.sleep(pause)
        return payload.get("count") or 0, len(bag)

    run("vintage:DES", {
        "filters": [{"name": "applicationMetaData.applicationTypeCode",
                     "value": ["DES"]}],
        "rangeFilters": rng,
        "pagination": {"offset": 0, "limit": 25}})
    total = None
    offset = 0
    while len(raw) < cap:
        count, returned = run("vintage:UTL@%d" % offset, {
            "filters": [{"name": "applicationMetaData.applicationTypeCode",
                         "value": ["UTL"]}],
            "rangeFilters": rng,
            "sort": [{"field": "applicationMetaData.grantDate", "order": "asc"}],
            "pagination": {"offset": offset, "limit": page}})
        if total is None:
            total = count
        offset += page
        if returned == 0 or (total and offset >= total):
            break
    if total and len(seen) < total:
        # Descending top-up for records the ascending pagination missed.
        offset = 0
        while len(raw) < cap and len(seen) < total:
            count, returned = run("vintage:UTL-desc@%d" % offset, {
                "filters": [{"name": "applicationMetaData.applicationTypeCode",
                             "value": ["UTL"]}],
                "rangeFilters": rng,
                "sort": [{"field": "applicationMetaData.grantDate", "order": "desc"}],
                "pagination": {"offset": offset, "limit": page}})
            offset += page
            if returned == 0 or offset >= total:
                break
    log.append({"label": "vintage:coverage", "index_count_utl": total,
                "unique_collected": len(seen)})
    return raw, log


def _odp_key(raw: dict) -> str:
    md = raw.get("applicationMetaData") or {}
    return str(md.get("patentNumber") or raw.get("applicationNumberText") or "").strip()


def build_live_file(raw_records: list[dict], query: dict, today: date,
                    source_label: str, source_url: str,
                    normalizer=None, key_fn=None, meta_extra: dict | None = None
                    ) -> tuple[dict, dict]:
    """Normalize raw records -> (live file blob, counts)."""
    normalizer = normalizer or normalize_record
    key_fn = key_fn or (lambda r: str(r.get("patent_number") or "").strip())
    records, rejected, seen = [], [], set()
    for raw in raw_records:
        num = key_fn(raw)
        if num and num in seen:
            rejected.append({"patent_number": num, "reason": "duplicate patent_number"})
            continue
        rec, err = normalizer(raw, today, source_url)
        if err is not None:
            rejected.append({"patent_number": num or "?", "reason": err})
            continue
        seen.add(num or rec["patent_number"])
        records.append(rec)
    records.sort(key=lambda r: r["patent_number"])
    n_review = sum(1 for r in records if r["review_required"])
    blob = {
        "_meta": {
            "data_status": "live",
            "adapter_version": ADAPTER_VERSION,
            "source": source_label,
            "source_url": source_url,
            "retrieved_at_utc": utcnow(),
            "query": query,
            "jurisdiction": "US",
            "status_method": STATUS_METHOD,
            "uncertainty": (
                "Filing+20y is a provisional estimate. PTA/PTE, terminal "
                "disclaimers, maintenance-fee lapses/reinstatement, "
                "continuations, claim scope and territorial scope NOT checked. "
                "Every record is REVIEW_REQUIRED until legal status is "
                "re-verified on USPTO Patent Center / Google Patents."),
            "counts": {
                "fetched": len(raw_records),
                "included": len(records),
                "rejected": len(rejected),
                "review_required": n_review,
            },
            "rejected": rejected,
            "defaults_applied": {
                "demand_signal": "steady (neutral default — not measured live)",
                "manufacture_profile": "medium: verify from patent figures",
                "printable_3d": False,
                "note": "Defaults are heuristics. Confirm manufacturability "
                        "and 3D-printability from the patent figures before acting.",
            },
            "odp_migration_note": (
                "Legacy PatentsView PatentSearch API retired 2026-03-20, "
                "migrating to USPTO Open Data Portal. ODP Patent File "
                "Wrapper search wired 2026-11-17 (adapter v1.1.0). "
                "See " + ODP_TRANSITION_URL),
        },
        "patents": records,
    }
    if meta_extra:
        blob["_meta"].update(meta_extra)
    counts = blob["_meta"]["counts"]
    return blob, counts


def fetch_legacy(cpcs: list[str], grant_from: str, grant_to: str,
                limit: int) -> list[dict]:
    """Query the legacy PatentsView PatentSearch API (RETIRED — expect failure)."""
    if os.environ.get("PATENT_RADAR_OFFLINE") == "1":
        raise RuntimeError("PATENT_RADAR_OFFLINE=1: network fetch refused")
    key = os.environ.get("PATENTSVIEW_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "No PATENTSVIEW_API_KEY in environment, and the legacy "
            "PatentsView PatentSearch API is RETIRED (migrating to USPTO ODP "
            "since 2026-03-20; old keys are incompatible with ODP). "
            "Use --source odp: the ODP Patent File Wrapper API is wired via "
            "the registered connector (no key in the environment). "
            "Docs: %s / %s" % (ODP_GETTING_STARTED_URL, ODP_TRANSITION_URL))
    body = json.dumps({
        "q": {"_and": [
            {"cpc_subgroup_id": c} for c in cpcs
        ] + [{"_gte": {"patent_date": grant_from}},
             {"_lte": {"patent_date": grant_to}}]},
        "f": ["patent_number", "patent_title", "patent_date", "patent_type",
              "cpc_section_id", "assignee_organization"],
        "o": {"per_page": limit},
    }).encode("utf-8")
    req = urllib.request.Request(
        LEGACY_API_URL, data=body,
        headers={"Content-Type": "application/json", "X-Api-Key": key},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise RuntimeError(
            "Legacy PatentsView API unreachable (%s). The API is retired / "
            "migrating to USPTO ODP since 2026-03-20. Use --source odp. "
            "See %s" % (e, ODP_TRANSITION_URL)) from e
    return payload.get("patents", [])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def _odp_post_search(body: dict) -> dict:
    """One ODP search POST through the connector surrogate exchange.

    The ODP API key is placed on the request by the credential exchange for
    the registered connection; this code never sees or stores the key.
    """
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import add_surrogate_to_request, read_json_response
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        ODP_SEARCH_URL, data=data, method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"})
    add_surrogate_to_request(req, ODP_CONNECTOR, allowed_hosts=ODP_ALLOWED_HOSTS)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=60) as resp:
            return read_json_response(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("ODP search HTTP %s: %s" % (e.code, detail)) from e


# Default live-pull plan: title keywords across the radar's domains
# (3D-printable consumer / home / garden / workshop products).
ODP_KEYWORDS = ["garden", "planter", "irrigation", "sprinkler", "feeder",
                "kitchen", "storage", "organizer", "shower", "faucet",
                "lamp", "toolbox"]


def odp_query_plan(today: date, keywords: list[str],
                   per_query: int) -> list[dict]:
    """Search bodies for the live pull: expired-term, expiring-window and
    maintenance-lapsed granted US utility patents, per title keyword."""
    expired_to = _add_years(today, -20).isoformat()
    expiring_from = _add_years(today, -20).isoformat()
    expiring_to = _add_years(today, -18).isoformat()
    plan = []
    # Lapsed first: maintenance-fee evidence is the strongest signal and the
    # fetch cap must not starve these queries (observed in the first pull).
    for kw in keywords[:6]:
        plan.append({
            "label": "lapsed:%s" % kw,
            "body": {
                "q": "applicationMetaData.inventionTitle:%s" % kw,
                "filters": [
                    {"name": "applicationMetaData.applicationTypeCode", "value": ["UTL"]},
                    {"name": "applicationMetaData.applicationStatusDescriptionText",
                     "value": [LAPSED_STATUS_PREFIX + " Under 37 CFR 1.362"]}],
                "pagination": {"offset": 0, "limit": max(2, per_query - 1)}}})
    for kw in keywords[:6]:
        plan.append({
            "label": "expiring:%s" % kw,
            "body": {
                "q": "applicationMetaData.inventionTitle:%s" % kw,
                "filters": [
                    {"name": "applicationMetaData.applicationTypeCode", "value": ["UTL"]},
                    {"name": "applicationMetaData.applicationStatusDescriptionText",
                     "value": ["Patented Case"]}],
                "rangeFilters": [{"field": "applicationMetaData.filingDate",
                                  "valueFrom": expiring_from, "valueTo": expiring_to}],
                "sort": [{"field": "applicationMetaData.filingDate", "order": "asc"}],
                "pagination": {"offset": 0, "limit": max(2, per_query - 1)}}})
    for kw in keywords:
        plan.append({
            "label": "expired-term:%s" % kw,
            "body": {
                "q": "applicationMetaData.inventionTitle:%s" % kw,
                "filters": [
                    {"name": "applicationMetaData.applicationTypeCode", "value": ["UTL"]},
                    {"name": "applicationMetaData.applicationStatusDescriptionText",
                     "value": ["Patented Case"]}],
                "rangeFilters": [{"field": "applicationMetaData.filingDate",
                                  "valueFrom": "2000-01-01", "valueTo": expired_to}],
                "sort": [{"field": "applicationMetaData.filingDate", "order": "asc"}],
                "pagination": {"offset": 0, "limit": per_query}}})
    return plan


def fetch_odp(keywords: list[str] | None = None, per_query: int = 3,
              today: date | None = None, cap: int = 48,
              pause: float = 0.6) -> tuple[list[dict], list[dict]]:
    """Run the ODP query plan; return (raw wrappers, per-query log).

    Sequential requests only (ODP burst limit is 1 per key). Stops early
    once `cap` unique patents are collected.
    """
    if os.environ.get("PATENT_RADAR_OFFLINE") == "1":
        raise RuntimeError("PATENT_RADAR_OFFLINE=1: network fetch refused")
    today = today or date.today()
    plan = odp_query_plan(today, keywords or ODP_KEYWORDS, per_query)
    raw, seen, log = [], set(), []
    for step in plan:
        if len(raw) >= cap:
            log.append({"label": step["label"], "skipped": "cap reached"})
            continue
        try:
            payload = _odp_post_search(step["body"])
        except RuntimeError as e:
            # ODP answers a zero-hit search with HTTP 404 ("No matching
            # records found"), not an empty bag. That is an empty result
            # for this query, not a failure of the pull.
            if "HTTP 404" in str(e):
                log.append({"label": step["label"], "count": 0, "returned": 0,
                            "added": 0, "note": "no matching records (HTTP 404)"})
                time.sleep(pause)
                continue
            raise
        bag = payload.get("patentFileWrapperDataBag") or []
        added = 0
        for wrapper in bag:
            k = _odp_key(wrapper)
            if k and k not in seen:
                seen.add(k)
                raw.append(wrapper)
                added += 1
        log.append({"label": step["label"], "count": payload.get("count"),
                    "returned": len(bag), "added": added})
        time.sleep(pause)
    return raw, log


def load_fixture(path: Path) -> list[dict]:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError("fixture %s is not valid JSON: %s" % (path, e)) from e
    recs = blob.get("patents")
    if not isinstance(recs, list):
        raise RuntimeError("fixture %s: expected top-level 'patents' list" % path)
    return recs


def load_odp_fixture(path: Path) -> list[dict]:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError("fixture %s is not valid JSON: %s" % (path, e)) from e
    recs = blob.get("patentFileWrapperDataBag")
    if not isinstance(recs, list):
        raise RuntimeError(
            "fixture %s: expected top-level 'patentFileWrapperDataBag' list" % path)
    return recs


def atomic_write(path: Path, blob: dict) -> None:
    """Idempotent atomic write: temp file in same dir + os.replace."""
    import hashlib
    data = json.dumps(blob, indent=2, sort_keys=False).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()[:12]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".live_patents_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print("wrote %s (%d records, sha256:%s)" % (path, len(blob["patents"]), digest))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Patent Radar live-data adapter.")
    ap.add_argument("--cpc", action="append", default=["A01B", "A01D", "A01G"],
                    help="CPC subgroup to query (repeatable; legacy source only)")
    ap.add_argument("--grant-from", default="2004-01-01")
    ap.add_argument("--grant-to", default="2010-12-31")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--source", choices=["legacy", "odp"], default="legacy",
                    help="odp = live USPTO Open Data Portal pull (default legacy "
                         "keeps the retired-API failure explicit; pass --source odp)")
    ap.add_argument("--keywords", default=None,
                    help="comma-separated title keywords for the ODP pull")
    ap.add_argument("--profile", choices=["standard", "vintage"], default="standard",
                    help="vintage = golden-era design hunt over grants "
                         "1920–1989 (ODP old-case records; see module docstring)")
    ap.add_argument("--per-query", type=int, default=3,
                    help="results per ODP search query")
    ap.add_argument("--fixture", type=Path,
                    help="saved legacy-shaped API response JSON; offline, no network")
    ap.add_argument("--odp-fixture", type=Path,
                    help="saved ODP search response JSON (patentFileWrapperDataBag); "
                         "offline, no network")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    ap.add_argument("--today", default=None,
                    help="reference date YYYY-MM-DD (default: today; tests pin this)")
    args = ap.parse_args(argv)

    today = _parse_date(args.today) if args.today else date.today()
    if today is None:
        print("ERROR: --today must be YYYY-MM-DD", file=sys.stderr)
        return 2
    query = {"cpc": args.cpc, "grant_from": args.grant_from,
             "grant_to": args.grant_to, "limit": args.limit,
             "source": args.source}
    normalizer, key_fn, meta_extra = normalize_record, None, None
    cat_by_key: dict[str, str] = {}

    if args.fixture is not None:
        try:
            raw = load_fixture(args.fixture)
        except RuntimeError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 1
        source_label = "fixture: %s (recorded PatentsView-shaped response)" % args.fixture
        source_url = str(args.fixture)
    elif args.odp_fixture is not None:
        try:
            raw = load_odp_fixture(args.odp_fixture)
        except RuntimeError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 1
        source_label = "fixture: %s (recorded ODP search response)" % args.odp_fixture
        source_url = str(args.odp_fixture)
        if args.profile == "vintage":
            normalizer, key_fn = normalize_odp_vintage_record, _odp_key
            meta_extra = {"status_method": VINTAGE_STATUS_METHOD}
        else:
            normalizer, key_fn = normalize_odp_record, _odp_key
            meta_extra = {"status_method": ODP_STATUS_METHOD}
        query = {"source": "odp-fixture", "fixture": str(args.odp_fixture),
                 "profile": args.profile}
    elif args.source == "odp" and args.profile == "vintage":
        try:
            raw, qlog = fetch_odp_vintage()
        except RuntimeError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 1
        source_label = ("USPTO Open Data Portal — Patent File Wrapper API "
                        "(live, vintage old-case sweep)")
        source_url = ODP_SEARCH_URL
        # Category screen: the old-case subset is mostly industrial /
        # electronics records. Only titles naming a consumer product of
        # the era join the dataset; the rest are counted + listed in _meta.
        kept, screened_out, cat_by_key = [], [], {}
        for w in raw:
            md = w.get("applicationMetaData") or {}
            cat = vintage_category(str(md.get("inventionTitle") or ""))
            if cat:
                kept.append(w)
                cat_by_key[_odp_key(w)] = cat
            else:
                screened_out.append(_odp_key(w) or "?")
        raw = kept
        normalizer, key_fn = normalize_odp_vintage_record, _odp_key
        meta_extra = {
            "status_method": VINTAGE_STATUS_METHOD,
            "search_syntax": (
                "POST /api/v1/patent/applications/search; era keyed to "
                "grantDate rangeFilters 1920-01-01..1989-12-31 (the index "
                "carries no pre-2001 filing dates); full old-case sweep "
                "paginated, titles screened locally by vintage category."),
            "query_log": qlog,
            "category_screen": {
                "swept": len(kept) + len(screened_out),
                "kept": len(kept),
                "screened_out": len(screened_out),
                "screened_out_numbers": screened_out,
                "note": "Screened-out records are the index's industrial/"
                        "electronics old cases whose titles name no vintage "
                        "consumer-product category.",
            },
            "uncertainty": (
                "VINTAGE pull. Status is expired-by-term by construction "
                "of the era; expiration_date is a term ESTIMATE (see "
                "status_method 'term (vintage, pre-1990 filing)'). The ODP "
                "file-wrapper index holds pre-1990 grants only as sparse "
                "old-case tracking records: measured 2026-11-17, ZERO "
                "records with grant dates in the 1920s–1950s, ~35 in the "
                "1960s, ~1,417 in the 1970s, ~18 in the 1980s, and only 2 "
                "design patents in 1960–1989 — this dataset is what the "
                "index actually holds, NOT a complete golden-era catalog. "
                "Pre-1990 records are thin: titles and grant dates are "
                "reliable, abstracts spotty, no CPC bag, no filing dates. "
                "Every record is REVIEW_REQUIRED until legal status is "
                "re-verified on USPTO Patent Center / Google Patents."),
        }
        query = {"source": "odp", "profile": "vintage",
                 "grant_from": VINTAGE_GRANT_FROM, "grant_to": VINTAGE_GRANT_TO,
                 "queries_run": len(qlog)}
    elif args.source == "odp":
        keywords = ([k.strip() for k in args.keywords.split(",") if k.strip()]
                    if args.keywords else ODP_KEYWORDS)
        try:
            raw, qlog = fetch_odp(keywords, args.per_query, today)
        except RuntimeError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 1
        source_label = "USPTO Open Data Portal — Patent File Wrapper API (live)"
        source_url = ODP_SEARCH_URL
        normalizer, key_fn = normalize_odp_record, _odp_key
        meta_extra = {
            "status_method": ODP_STATUS_METHOD,
            "search_syntax": (
                "POST /api/v1/patent/applications/search with JSON body; "
                "'q' is a STRING in field:value syntax (an object 'q' "
                "returns HTTP 400); filters/rangeFilters/sort/pagination "
                "as documented at " + ODP_GETTING_STARTED_URL),
            "query_log": qlog,
            "uncertainty": (
                "Filing+20y is a provisional estimate (status_method "
                "'filing+20y provisional'). PTA/PTE, terminal disclaimers, "
                "continuations, claim scope and territorial scope NOT "
                "checked; maintenance-fee lapse IS checked against the ODP "
                "application status and eventDataBag. Every record is "
                "REVIEW_REQUIRED until legal status is re-verified on "
                "USPTO Patent Center / Google Patents."),
        }
        query = {"source": "odp", "keywords": keywords,
                 "per_query": args.per_query, "queries_run": len(qlog)}
    else:
        try:
            raw = fetch_legacy(args.cpc, args.grant_from, args.grant_to, args.limit)
        except RuntimeError as e:
            print("ERROR: %s" % e, file=sys.stderr)
            return 1
        source_label = "PatentsView PatentSearch API (legacy)"
        source_url = LEGACY_API_URL

    blob, counts = build_live_file(raw, query, today, source_label, source_url,
                                   normalizer=normalizer, key_fn=key_fn,
                                   meta_extra=meta_extra)
    if cat_by_key:
        for rec in blob["patents"]:
            cat = cat_by_key.get(rec["patent_number"].removeprefix("US"))
            if cat:
                rec["vintage_category"] = cat
    if counts["included"] == 0:
        print("ERROR: no qualifying records (fetched %d, rejected %d); "
              "refusing to write an empty live file" % (
                  counts["fetched"], counts["rejected"]), file=sys.stderr)
        for r in blob["_meta"]["rejected"]:
            print("  rejected %s: %s" % (r["patent_number"], r["reason"]),
                  file=sys.stderr)
        return 1

    print("records: fetched=%d included=%d rejected=%d review_required=%d" % (
        counts["fetched"], counts["included"], counts["rejected"],
        counts["review_required"]))
    for r in blob["patents"]:
        unc = (" | UNCERTAIN: %s" % r["status_uncertainty"]) if r["status_uncertainty"] else ""
        print("  %-14s %-9s exp=%s%s" % (
            r["patent_number"], r["status"], r["expiration_date"], unc))
    if args.dry_run:
        print("dry-run: nothing written")
        return 0
    atomic_write(args.out, blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
