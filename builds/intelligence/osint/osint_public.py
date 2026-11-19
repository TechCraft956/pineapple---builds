#!/usr/bin/env python3
"""
OSINT Public (public-records only, ethical)  -  04_INTELLIGENCE/osint

Given a business or person name, aggregate PUBLIC-RECORD signals ONLY:
  - TX Secretary of State business filings (formation, status, registered agent)
  - Assumed-name / DBA records (county clerk)
  - Professional licenses (TDLR / TREC / TABC / TxDMV public lookups)
  - County clerk filing index entries (UCC, assumed names, tax-forfeiture)

It produces ENTITY DOSSIERS for due diligence: who you're about to transact
with, whether the entity is in good standing, whether assets are encumbered,
and whether a license is lapsing. Output feeds the Pineapple Decision Engine.

================================  ETHICS  ================================
HARD CONSTRAINTS (enforced in code via _ETHICS_GATE + assert_record_clean):

  1. PUBLIC RECORDS ONLY. Only data that a government agency publishes for
     public inspection (business filings, DBA index, license registries,
     county clerk index). Nothing behind a login, paywall of private data,
     or terms-of-service that forbids automated access without permission.
  2. NO PRIVATE PII. No SSN, no DOB, no driver's license, no home address,
     no personal phone/email, no financial-account numbers. The fields below
     are BANNED and any record containing them is rejected.
  3. NO PII COMPILATION beyond a public BUSINESS filing. A "person" record is
     limited to the person's PUBLIC BUSINESS ROLE (e.g. "managing member of X
     LLC per SOS filing") and PUBLIC professional licenses. We do not build a
     personal profile of a private individual.
  4. NO SOCIAL-MEDIA SCRAPING. No Facebook/Instagram/X/LinkedIn/TikTok data,
     no scraped web content, no people-search/data-broker aggregators.
  5. CONSENT-AWARE. Person dossiers carry a consent note and are intended for
     legitimate-interest due diligence (you are about to do business with the
     named entity), not surveillance of uninvolved private individuals.

This module ships with SAMPLE data (clearly marked) and is OFFLINE by default.
Real source endpoints are documented in PLUGIN["sources"] and in the README
for later wiring. Wiring those sources must respect each site's robots.txt and
terms of service; several (SOSDirect, TABC) are official lookups intended for
manual/public use.
==========================================================================

Run:
  python osint_public.py --selftest          # health summary, exit 0 on success
  python osint_public.py --query "Valley Sun" # dossiers matching a name
  python osint_public.py --json               # all dossiers as JSON
  python osint_public.py                      # human-readable table
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths (write ONLY inside our own folder or 00_PROCESSED).
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
SAMPLE_FILE = DATA_DIR / "sample_entities.json"


def _find_root(start: Path) -> Path | None:
    for p in [start, *start.parents]:
        if (p / ".pineapple_root").exists():
            return p
    return None


ROOT = _find_root(HERE)
PROCESSED_DIR = (ROOT / "00_PROCESSED" / "people") if ROOT else (HERE / "out")

# --------------------------------------------------------------------------- #
# Ethics gate. These are the things we will NOT touch.
# --------------------------------------------------------------------------- #
# Field-name fragments that signal private PII. If a record (at any depth)
# contains one of these keys, it is rejected as a hard ethical violation.
_BANNED_KEY_FRAGMENTS = (
    "ssn", "social_security", "tax_id", "ein",            # gov / financial ids
    "dob", "date_of_birth", "birth", "age",               # personal identity
    "drivers_license", "driver_license", "passport",      # gov id documents
    "home_address", "residential", "personal_phone",      # private contact
    "cell", "mobile_phone", "personal_email", "private_",
    "credit_card", "bank_account", "account_number",      # financial
    "facebook", "instagram", "twitter", "tiktok",         # social media
    "linkedin", "snapchat", "social_media", "scraped",
)

# Sources we will NOT ingest from, even if asked.
_BANNED_SOURCES = (
    "facebook", "instagram", "twitter", "x.com", "tiktok", "linkedin",
    "snapchat", "spokeo", "beenverified", "truepeoplesearch", "whitepages",
    "intelius", "peoplefinder", "fastpeoplesearch", "data broker", "scrape",
)

_ETHICS_GATE = {
    "public_records_only": True,
    "no_private_pii": True,
    "no_pii_compilation_beyond_public_business_filing": True,
    "no_social_media_scraping": True,
    "consent_aware": True,
    "banned_pii_field_fragments": list(_BANNED_KEY_FRAGMENTS),
    "banned_sources": list(_BANNED_SOURCES),
}


class EthicsViolation(Exception):
    """Raised when a record would breach the public-records-only contract."""


def _walk_keys(obj):
    """Yield every (key, value) pair anywhere in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), v
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def _key_tokens(key: str) -> set[str]:
    """Split a field name into word tokens for precise banned-fragment match.

    Token match (not naive substring) so harmless words like
    'registered_agent' do not trip the short 'age' fragment.
    """
    return set(t for t in re.split(r"[^a-z0-9]+", key.lower()) if t)


def assert_record_clean(rec: dict) -> None:
    """Reject any record carrying private PII or a banned source.

    This is the enforcement point for the ethical contract: every entity is
    passed through here before it can become a dossier.
    """
    for key, val in _walk_keys(rec):
        tokens = _key_tokens(key)
        for frag in _BANNED_KEY_FRAGMENTS:
            # multi-word fragments (e.g. "social_security") -> substring match
            # single tokens (e.g. "ssn", "age", "dob") -> exact token match
            if "_" in frag or "-" in frag:
                hit = frag.replace("-", "_") in key.lower().replace("-", "_")
            else:
                hit = frag in tokens
            if hit:
                raise EthicsViolation(
                    "banned PII field '%s' in entity '%s'"
                    % (key, rec.get("entity", "?"))
                )
        if isinstance(val, str):
            vl = val.lower()
            for bad in _BANNED_SOURCES:
                if bad in vl:
                    raise EthicsViolation(
                        "banned/social source '%s' referenced in entity '%s'"
                        % (bad, rec.get("entity", "?"))
                    )


# --------------------------------------------------------------------------- #
# PLUGIN contract (consumed by the Pineapple registry / decision layer).
# --------------------------------------------------------------------------- #
PLUGIN = {
    "id": "osint_public",
    "name": "OSINT Public (Ethical Public-Records Dossiers)",
    "category": "intelligence",
    "authority": "due_diligence",
    "status": "sample",
    "inputs": [
        "entity_or_person_name",
        "data/sample_entities.json (public-record snapshots)",
    ],
    "outputs": [
        "entity dossiers: {entity, type, filings, addresses_public, "
        "risk_flags, confidence}",
        "decision items: title/category/source/action/est_value/risk/"
        "location/url/confidence",
    ],
    # REAL public-record sources to wire later. All government / official.
    "sources": [
        "https://www.sos.state.tx.us/corp/sosda/index.shtml",          # TX SOS SOSDirect business search
        "https://mycpa.cpa.state.tx.us/coa/",                          # TX Comptroller Taxable Entity Search (status)
        "https://www.tdlr.texas.gov/LicenseSearch/",                   # TDLR professional license search
        "https://www.trec.texas.gov/apps/license-holder-search/",      # TREC real-estate license search
        "https://www.tabc.texas.gov/services/public-inquiry/",         # TABC alcohol permit public inquiry
        "https://prod.txapps.texas.gov/tlc-search/app/license-search", # TxDMV / motor-vehicle dealer license search
        "https://www.hidalgocountyclerk.us/",                          # Hidalgo County Clerk (DBA / records)
        "https://www.cameroncountyclerk.com/",                         # Cameron County Clerk (DBA / records)
        "https://www.co.starr.tx.us/page/starr.County.Clerk",          # Starr County Clerk
        "https://direct.sos.state.tx.us/ucc/ucc-search.asp",           # TX SOS UCC financing-statement search
    ],
    "safety": {
        "ethics": _ETHICS_GATE,
        "data_status": "SAMPLE - fabricated for development; not real filings",
        "offline": True,
        "read_only_user_folders": True,
        "writes_only_inside": [str(HERE), str(PROCESSED_DIR)],
        "legal_note": (
            "Public-record due diligence only. Not a consumer report; do not "
            "use for FCRA-covered purposes (credit/employment/housing/insurance). "
            "Verify every field against the official source before acting."
        ),
    },
}

# --------------------------------------------------------------------------- #
# Data loading.
# --------------------------------------------------------------------------- #
SEVERITY_TO_RISK = {"LOW": "LOW", "MED": "MED", "HIGH": "HIGH"}


def _load_entities() -> list[dict]:
    """Load sample entities, enforce the ethics gate, return clean records."""
    if not SAMPLE_FILE.exists():
        return []
    blob = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    ents = blob.get("entities", [])
    clean = []
    for rec in ents:
        assert_record_clean(rec)  # raises on any violation
        clean.append(rec)
    return clean


def _aggregate_risk(flags: list[dict]) -> str:
    """Roll a list of risk_flags up to a single LOW/MED/HIGH for the item."""
    if not flags:
        return "LOW"
    order = {"LOW": 0, "MED": 1, "HIGH": 2}
    worst = max((SEVERITY_TO_RISK.get(f.get("severity", "LOW"), "LOW")
                 for f in flags), key=lambda s: order[s])
    return worst


def _primary_location(rec: dict) -> str:
    county = rec.get("county", "")
    addrs = rec.get("addresses_public", [])
    if addrs:
        return "%s (%s County, TX)" % (addrs[0].get("value", ""), county) \
            if county else addrs[0].get("value", "")
    return "%s County, TX" % county if county else "TX"


def _dossier(rec: dict) -> dict:
    """Shape one public-record entity into a dossier (spec-required shape)."""
    return {
        "entity": rec.get("entity"),
        "type": rec.get("type"),
        "entity_subtype": rec.get("entity_subtype"),
        "status_public": rec.get("status_public"),
        "filings": rec.get("filings", []),
        "addresses_public": rec.get("addresses_public", []),
        "professional_licenses": rec.get("professional_licenses", []),
        "officers_public": rec.get("officers_public", []),
        "registered_agent_public": rec.get("registered_agent_public"),
        "risk_flags": rec.get("risk_flags", []),
        "county": rec.get("county"),
        "confidence": rec.get("confidence", 0.5),
        "data_status": "sample",
    }


def dossiers(query: str | None = None) -> list[dict]:
    """Return entity dossiers, optionally filtered by a name substring."""
    out = []
    for rec in _load_entities():
        if query:
            q = query.strip().lower()
            hay = " ".join([
                str(rec.get("entity", "")),
                " ".join(f.get("name", "") for f in rec.get("filings", [])),
                " ".join(o.get("name", "") for o in rec.get("officers_public", [])),
            ]).lower()
            if q not in hay:
                continue
        out.append(_dossier(rec))
    return out


# --------------------------------------------------------------------------- #
# Decision-engine item shaping.
# --------------------------------------------------------------------------- #
def _action_for(rec: dict, agg_risk: str) -> str:
    name = rec.get("entity", "this entity")
    status = (rec.get("status_public") or "").lower()
    flags = [f.get("flag", "") for f in rec.get("risk_flags", [])]
    if "forfeited" in status:
        return ("DO NOT CONTRACT: %s shows forfeited existence in public "
                "record. Require reinstatement proof first." % name)
    if "active_ucc_lien" in flags or "multiple_ucc_filings" in flags:
        return ("Pull full UCC financing statement(s) for %s to confirm "
                "collateral before any asset purchase." % name)
    if any("license_expiring" in f for f in flags):
        return ("Verify license renewal for %s at the issuing board before "
                "signing." % name)
    if agg_risk == "LOW" and rec.get("type") == "business":
        return ("%s appears in good standing (sample). Confirm current status "
                "on SOSDirect, then proceed with normal diligence." % name)
    return "Review public-record dossier for %s before transacting." % name


def items(query: str | None = None) -> list[dict]:
    """Return decision-engine items, one per public-record entity dossier.

    Each item: title, category, source, action, est_value, risk, location,
    url, confidence  (plus a nested `dossier` payload for drill-down).
    """
    out = []
    for rec in _load_entities():
        if query:
            q = query.strip().lower()
            if q not in str(rec.get("entity", "")).lower():
                # also allow officer-name match
                if not any(q in o.get("name", "").lower()
                           for o in rec.get("officers_public", [])):
                    continue
        flags = rec.get("risk_flags", [])
        agg_risk = _aggregate_risk(flags)
        n_filings = len(rec.get("filings", []))
        n_lic = len(rec.get("professional_licenses", []))
        title = "%s - public-record dossier (%d filings, %d licenses)" % (
            rec.get("entity", "?"), n_filings, n_lic)
        out.append({
            "title": title,
            "category": "intelligence",
            "source": "OSINT Public (TX SOS / county clerk / TDLR - SAMPLE)",
            "action": _action_for(rec, agg_risk),
            # OSINT/due-diligence is risk-reduction, not a priced opportunity.
            "est_value": None,
            "risk": agg_risk,
            "location": _primary_location(rec),
            "url": PLUGIN["sources"][0],  # SOSDirect business search entry point
            "confidence": round(float(rec.get("confidence", 0.5)), 2),
            "dossier": _dossier(rec),
        })
    out.sort(key=lambda x: ({"HIGH": 0, "MED": 1, "LOW": 2}[x["risk"]],
                            -x["confidence"]))
    return out


# --------------------------------------------------------------------------- #
# Output writer (only inside our folder / 00_PROCESSED).
# --------------------------------------------------------------------------- #
def write_processed() -> Path:
    target_dir = PROCESSED_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        target_dir = HERE / "out"
        target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "osint_public_dossiers.json"
    payload = {
        "plugin": PLUGIN["id"],
        "status": "sample",
        "ethics": _ETHICS_GATE,
        "count": len(items()),
        "items": items(),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# Self-test.
# --------------------------------------------------------------------------- #
def selftest() -> int:
    ok = True
    checks = []

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        checks.append((name, bool(cond), detail))

    # 1. sample data present
    ents = []
    try:
        ents = _load_entities()
        check("load_entities", len(ents) >= 5, "%d entities" % len(ents))
    except Exception as e:
        check("load_entities", False, repr(e))

    # 2. dossiers shaped correctly
    ds = dossiers()
    required = {"entity", "type", "filings", "addresses_public",
                "risk_flags", "confidence"}
    shape_ok = all(required.issubset(d.keys()) for d in ds)
    check("dossier_shape", shape_ok and len(ds) == len(ents),
          "%d dossiers" % len(ds))

    # 3. decision items shaped for the engine
    its = items()
    item_keys = {"title", "category", "source", "action", "est_value",
                 "risk", "location", "url", "confidence"}
    items_ok = all(item_keys.issubset(i.keys()) for i in its)
    risk_ok = all(i["risk"] in ("LOW", "MED", "HIGH") for i in its)
    conf_ok = all(0.0 <= i["confidence"] <= 1.0 for i in its)
    check("item_shape", items_ok, "%d items" % len(its))
    check("item_risk_enum", risk_ok)
    check("item_confidence_range", conf_ok)

    # 4. query filter works
    q = items(query="Valley Sun")
    check("query_filter", len(q) == 1 and "Valley Sun" in q[0]["title"],
          "%d match(es) for 'Valley Sun'" % len(q))

    # 5. ETHICS GATE actually blocks private PII (inject a violation)
    gate_blocks = False
    try:
        assert_record_clean({"entity": "Test", "ssn": "xxx-xx-xxxx"})
    except EthicsViolation:
        gate_blocks = True
    check("ethics_gate_blocks_pii", gate_blocks)

    # 6. ETHICS GATE blocks social-media source
    gate_blocks_social = False
    try:
        assert_record_clean({"entity": "Test", "note": "from facebook profile"})
    except EthicsViolation:
        gate_blocks_social = True
    check("ethics_gate_blocks_social", gate_blocks_social)

    # 7. all sources are real-looking official gov / county-clerk URLs
    official_markers = (".gov", ".state.tx.us", ".texas.gov", ".state.",
                        "countyclerk", "co.starr.tx.us")
    src_ok = all(
        s.startswith("https://") and any(m in s for m in official_markers)
        for s in PLUGIN["sources"]
    )
    check("sources_are_official", src_ok,
          "%d sources" % len(PLUGIN["sources"]))

    # 8. write output without touching user folders
    try:
        p = write_processed()
        check("write_processed", p.exists(), str(p))
    except Exception as e:
        check("write_processed", False, repr(e))

    print("OSINT Public - selftest")
    print("  status: SAMPLE data, OFFLINE, public-records-only")
    for name, passed, detail in checks:
        print("  [%s] %-26s %s" % ("OK" if passed else "XX", name, detail))
    print("  ethics: public-records-only, no-PII, no-social-scraping, "
          "consent-aware")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _render_table(its: list[dict]) -> None:
    print("OSINT Public dossiers (SAMPLE / public records only)")
    print("-" * 78)
    for i in its:
        print("[%-4s] %s" % (i["risk"], i["title"]))
        print("        loc: %s" % i["location"])
        print("        -> %s" % i["action"])
        print("        confidence: %.2f | source: %s" %
              (i["confidence"], i["source"]))
        print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=PLUGIN["name"])
    ap.add_argument("--selftest", action="store_true",
                    help="run health check, exit 0 on success")
    ap.add_argument("--query", type=str, default=None,
                    help="filter dossiers by business/person name substring")
    ap.add_argument("--json", action="store_true",
                    help="emit items as JSON")
    ap.add_argument("--write", action="store_true",
                    help="write dossiers to 00_PROCESSED/people/")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    its = items(query=args.query)
    if args.write:
        p = write_processed()
        print("wrote:", p)
    if args.json:
        print(json.dumps(its, indent=2))
    else:
        _render_table(its)
    return 0


if __name__ == "__main__":
    sys.exit(main())
