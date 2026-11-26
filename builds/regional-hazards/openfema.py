#!/usr/bin/env python3
"""OpenFEMA collector — Pineapple sensors #57 + #73 (regional hazards).

Read-only collector for FEMA open data, filtered to Starr County, TX
(FIPS 48427), covering three legs:

  #57 disasters      DisasterDeclarationsSummaries — every federal
                      disaster/emergency declaration designating Starr
                      County, with the programs declared (IA/PA/HM).
  #57 Public Assist  PublicAssistanceFundedProjectsDetails — funded PA
                      projects in Starr County (project dollars,
                      federal share obligated, damage category).
  #73 NFIP claims    NfipClaims — National Flood Insurance Program
                      claims in Starr County (amounts paid on building
                      / contents / increased cost of compliance).

Sources (keyless, no signup, no API key, $0):
  https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
  https://www.fema.gov/api/open/v2/PublicAssistanceFundedProjectsDetails
  https://www.fema.gov/api/open/v3/NfipClaims

Version note (VERIFIED live 2026-11-26 via the v1 DataSets catalogue):
each OpenFEMA dataset carries its OWN current version — there is no
single "v3" for everything. DisasterDeclarationsSummaries is v2
(recordCount 70,607; refreshed 2026-11-26), PublicAssistance-
FundedProjectsDetails is v2 (852,114 records; refreshed 2026-11-26),
NfipClaims is v3 (2,731,064 records; as-of 2026-11-16). The v3 path
for DisasterDeclarationsSummaries answers HTTP 404 (Drupal page);
the v2 path is live and current, so v2 is used for that leg. The
"v2 retired Oct 2026" claim does not hold for these datasets.

Two API quirks, both VERIFIED live:
  * Requests MUST send ``Accept: application/json``. Without it,
    fema.gov answers the API path with a Drupal 404 HTML page.
  * ``metadata.count`` is 0 unless ``$count=true`` is requested —
    a count of 0 without $count means nothing. All three legs are
    fetched with ``$count=true`` and the returned record list is
    what is counted.

County-code formats differ per dataset (VERIFIED live):
  * DisasterDeclarationsSummaries: ``state eq 'TX'`` and
    ``fipsCountyCode eq '427'`` (3-digit county code; the 5-digit
    FIPS '48427' matches NOTHING — the probe's 404 was the v3 path,
    and a '48427' filter on v2 returns zero rows).
  * PublicAssistanceFundedProjectsDetails: ``stateNumberCode eq '48'``
    and ``countyCode eq '427'`` (both numeric-as-string).
  * NfipClaims: ``countyCode eq '48427'`` (full 5-digit FIPS).

Labels
------
VERIFIED  record present with its key fields parseable (disaster:
          disasterNumber + declarationDate + designatedArea; PA:
          disasterNumber + declarationDate + projectAmount; NFIP:
          dateOfLoss + yearOfLoss).
REPORTED  record present but a key field is missing/unparseable.
          The record is real; the gap is recorded, never zero-filled.
UNKNOWN   record whose county field is absent or does not match the
          requested county (defensive; the server-side filter should
          prevent this).

Privacy
-------
NFIP claim records carry coarse lat/lon and a census-tract geoid.
Lat/lon are dropped at ingest; only ZIP code and census tract are
emitted. No street addresses exist in any of these datasets.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://www.fema.gov/api/open"

# (leg, entity, version) — current versions VERIFIED via the v1
# DataSets catalogue on 2026-11-26.
DATASETS = {
    "disasters": ("DisasterDeclarationsSummaries", 2),
    "public_assistance": ("PublicAssistanceFundedProjectsDetails", 2),
    "nfip_claims": ("NfipClaims", 3),
}

CATALOG_URL = BASE_URL + "/v1/DataSets"

FIPS_STARR_COUNTY_TX = "48427"
STATE_ABBR = "TX"

# The OpenFEMA API caps $top at 1000 records per call; Starr County
# legs are far below that (23 / 238 / 85 on 2026-11-26), but paging
# is implemented anyway so the collector keeps working if counts grow.
PAGE_SIZE = 1000

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Pineapple-OpenFEMA-collector/1.0 (read-only public data)",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_fips(fips: str) -> tuple[str, str]:
    """Split a 5-digit county FIPS into (state_code, county_code).

    '48427' -> ('48', '427'). Raises ValueError on anything else.
    """
    fips = str(fips).strip()
    if len(fips) != 5 or not fips.isdigit():
        raise ValueError(f"expected a 5-digit county FIPS, got {fips!r}")
    return fips[:2], fips[2:]


def build_filter(leg: str, fips: str) -> str:
    """OData $filter expression for one leg and one county FIPS."""
    state_code, county_code = split_fips(fips)
    if leg == "disasters":
        return (f"state eq '{STATE_ABBR}' and "
                f"fipsCountyCode eq '{county_code}'")
    if leg == "public_assistance":
        return (f"stateNumberCode eq '{state_code}' and "
                f"countyCode eq '{county_code}'")
    if leg == "nfip_claims":
        return f"countyCode eq '{fips}'"
    raise ValueError(f"unknown leg {leg!r}")


def build_url(leg: str, fips: str, top: int = PAGE_SIZE,
              skip: int = 0) -> str:
    """Full query URL for one page of one leg."""
    entity, version = DATASETS[leg]
    filt = build_filter(leg, fips)
    filt_enc = (filt.replace(" ", "%20")
                    .replace("'", "%27"))
    return (f"{BASE_URL}/v{version}/{entity}"
            f"?$filter={filt_enc}"
            f"&$top={top}&$skip={skip}&$count=true")


def _clean(value):
    """Strip whitespace; empty strings become None (never zero-filled)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _to_float(value):
    """Parse a number; literal 'null' strings and junk become None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "" or value.lower() == "null":
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError, AttributeError):
        return None


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def fetch_page(url: str, opener=None) -> dict:
    """GET one API page as parsed JSON. Raises on HTTP/network error."""
    open_fn = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers=HEADERS)
    with open_fn(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def fetch_leg(leg: str, fips: str, opener=None) -> dict:
    """Fetch every page of one leg. Returns records + fetch metadata.

    Network/HTTP errors are captured in the returned dict (status
    string), not raised, so one dead leg does not kill the other two.
    """
    entity, version = DATASETS[leg]
    url = build_url(leg, fips)
    records: list[dict] = []
    reported_count = None
    status = "OK"
    try:
        while True:
            page = fetch_page(url, opener=opener)
            meta = page.get("metadata") or {}
            if reported_count is None:
                reported_count = meta.get("count")
            batch = page.get(entity) or []
            records.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            url = build_url(leg, fips, skip=len(records))
    except Exception as exc:  # HTTPError, URLError, JSON errors, ...
        status = f"ERROR: {type(exc).__name__}: {exc}"
    return {
        "leg": leg,
        "entity": entity,
        "version": version,
        "url": build_url(leg, fips),
        "status": status,
        "reported_count": reported_count,
        "records_returned": len(records),
        "records": records,
    }


# ----------------------------------------------------------------------
# Parsers: one raw record -> one observation (pure, testable).
# ----------------------------------------------------------------------

def parse_disaster(rec: dict, fips: str, source_url: str,
                   retrieved_at: str) -> dict:
    """One DisasterDeclarationsSummaries row -> observation."""
    _, county_code = split_fips(fips)
    county_ok = _clean(rec.get("fipsCountyCode")) == county_code
    state_ok = _clean(rec.get("state")) == STATE_ABBR
    obs = {
        "leg": "disasters",
        "sensor": "57",
        "disaster_number": _to_int(rec.get("disasterNumber")),
        "fema_declaration_string": _clean(rec.get("femaDeclarationString")),
        "declaration_date": _clean(rec.get("declarationDate")),
        "declaration_type": _clean(rec.get("declarationType")),
        "incident_type": _clean(rec.get("incidentType")),
        "declaration_title": _clean(rec.get("declarationTitle")),
        "designated_area": _clean(rec.get("designatedArea")),
        "fips_state_code": _clean(rec.get("fipsStateCode")),
        "fips_county_code": _clean(rec.get("fipsCountyCode")),
        "incident_begin_date": _clean(rec.get("incidentBeginDate")),
        "incident_end_date": _clean(rec.get("incidentEndDate")),
        "disaster_closeout_date": _clean(rec.get("disasterCloseoutDate")),
        "ih_program_declared": _to_bool(rec.get("ihProgramDeclared")),
        "ia_program_declared": _to_bool(rec.get("iaProgramDeclared")),
        "pa_program_declared": _to_bool(rec.get("paProgramDeclared")),
        "hm_program_declared": _to_bool(rec.get("hmProgramDeclared")),
        "county_fips": fips,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    if not (county_ok and state_ok):
        obs["label"] = "UNKNOWN"
    elif (obs["disaster_number"] is not None
            and obs["declaration_date"] is not None
            and obs["designated_area"] is not None):
        obs["label"] = "VERIFIED"
    else:
        obs["label"] = "REPORTED"
    return obs


def parse_pa_project(rec: dict, fips: str, source_url: str,
                     retrieved_at: str) -> dict:
    """One PublicAssistanceFundedProjectsDetails row -> observation."""
    state_code, county_code = split_fips(fips)
    county_ok = _clean(rec.get("countyCode")) == county_code
    state_ok = _clean(rec.get("stateNumberCode")) == state_code
    obs = {
        "leg": "public_assistance",
        "sensor": "57",
        "disaster_number": _to_int(rec.get("disasterNumber")),
        "declaration_date": _clean(rec.get("declarationDate")),
        "incident_type": _clean(rec.get("incidentType")),
        "county": _clean(rec.get("county")),
        "applicant_id": _clean(rec.get("applicantId")),
        "application_title": _clean(rec.get("applicationTitle")),
        "damage_category_code": _clean(rec.get("damageCategoryCode")),
        "damage_category": _clean(rec.get("damageCategoryDescrip")),
        "project_amount": _to_float(rec.get("projectAmount")),
        "federal_share_obligated": _to_float(
            rec.get("federalShareObligated")),
        "total_obligated": _to_float(rec.get("totalObligated")),
        "mitigation_amount": _to_float(rec.get("mitigationAmount")),
        "project_status": _clean(rec.get("projectStatus")),
        "project_size": _clean(rec.get("projectSize")),
        "project_process_step": _clean(rec.get("projectProcessStep")),
        "pw_number": _to_int(rec.get("pwNumber")),
        "first_obligation_date": _clean(rec.get("firstObligationDate")),
        "last_obligation_date": _clean(rec.get("lastObligationDate")),
        "county_fips": fips,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    if not (county_ok and state_ok):
        obs["label"] = "UNKNOWN"
    elif (obs["disaster_number"] is not None
            and obs["declaration_date"] is not None
            and obs["project_amount"] is not None):
        obs["label"] = "VERIFIED"
    else:
        obs["label"] = "REPORTED"
    return obs


def parse_nfip_claim(rec: dict, fips: str, source_url: str,
                     retrieved_at: str) -> dict:
    """One NfipClaims row -> observation. Lat/lon are dropped."""
    county_ok = _clean(rec.get("countyCode")) == fips
    state_ok = _clean(rec.get("state")) == STATE_ABBR
    obs = {
        "leg": "nfip_claims",
        "sensor": "73",
        "claim_id": _to_int(rec.get("id")),
        "date_of_loss": _clean(rec.get("dateOfLoss")),
        "year_of_loss": _to_int(rec.get("yearOfLoss")),
        "flood_event": _clean(rec.get("floodEvent")),
        "cause_of_damage": _clean(rec.get("causeOfDamage")),
        "rated_flood_zone": _clean(rec.get("ratedFloodZone")),
        "county_code": _clean(rec.get("countyCode")),
        "reported_zip_code": _clean(rec.get("reportedZipCode")),
        "census_geoid": _clean(rec.get("censusGeoid")),
        "amount_paid_building": _to_float(
            rec.get("amountPaidOnBuildingClaim")),
        "amount_paid_contents": _to_float(
            rec.get("amountPaidOnContentsClaim")),
        "amount_paid_icc": _to_float(
            rec.get("amountPaidOnIncreasedCostOfComplianceClaim")),
        "net_building_payment": _to_float(
            rec.get("netBuildingPaymentAmount")),
        "net_contents_payment": _to_float(
            rec.get("netContentsPaymentAmount")),
        "building_damage_amount": _to_float(
            rec.get("buildingDamageAmount")),
        "total_building_coverage": _to_float(
            rec.get("totalBuildingInsuranceCoverage")),
        "total_contents_coverage": _to_float(
            rec.get("totalContentsInsuranceCoverage")),
        "occupancy_type": _to_int(rec.get("occupancyType")),
        "primary_residence": _to_bool(rec.get("primaryResidenceIndicator")),
        "as_of_date": _clean(rec.get("asOfDate")),
        "county_fips": fips,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }
    if not (county_ok and state_ok):
        obs["label"] = "UNKNOWN"
    elif (obs["date_of_loss"] is not None
            and obs["year_of_loss"] is not None):
        obs["label"] = "VERIFIED"
    else:
        obs["label"] = "REPORTED"
    return obs


PARSERS = {
    "disasters": parse_disaster,
    "public_assistance": parse_pa_project,
    "nfip_claims": parse_nfip_claim,
}


def _sum(values) -> float | None:
    """Sum of non-null numbers; None when every value is null."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums), 2)


def _date_range(dates) -> list:
    """[min, max] of non-null date strings; [None, None] when empty."""
    vals = [d for d in dates if d]
    if not vals:
        return [None, None]
    return [min(vals), max(vals)]


def _counts(items, key) -> dict:
    out: dict = {}
    for item in items:
        val = item.get(key)
        if val is None:
            continue
        out[str(val)] = out.get(str(val), 0) + 1
    return dict(sorted(out.items()))


def summarize(leg: str, observations: list[dict]) -> dict:
    """Per-leg aggregates: counts, totals, date ranges."""
    summary: dict = {
        "count": len(observations),
        "by_label": {lab: sum(1 for o in observations if o["label"] == lab)
                     for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
    }
    if leg == "disasters":
        summary["declaration_date_range"] = _date_range(
            [o["declaration_date"] for o in observations])
        summary["by_incident_type"] = _counts(observations, "incident_type")
        summary["by_declaration_type"] = _counts(
            observations, "declaration_type")
        summary["disaster_numbers"] = sorted({
            o["disaster_number"] for o in observations
            if o["disaster_number"] is not None})
        summary["pa_declared_count"] = sum(
            1 for o in observations if o["pa_program_declared"] is True)
        summary["ia_declared_count"] = sum(
            1 for o in observations if o["ia_program_declared"] is True)
        summary["hm_declared_count"] = sum(
            1 for o in observations if o["hm_program_declared"] is True)
    elif leg == "public_assistance":
        summary["declaration_date_range"] = _date_range(
            [o["declaration_date"] for o in observations])
        summary["project_amount_total"] = _sum(
            [o["project_amount"] for o in observations])
        summary["federal_share_obligated_total"] = _sum(
            [o["federal_share_obligated"] for o in observations])
        summary["total_obligated_total"] = _sum(
            [o["total_obligated"] for o in observations])
        summary["mitigation_amount_total"] = _sum(
            [o["mitigation_amount"] for o in observations])
        summary["by_disaster_number"] = _counts(
            observations, "disaster_number")
        summary["by_damage_category"] = _counts(
            observations, "damage_category")
        summary["by_incident_type"] = _counts(observations, "incident_type")
    elif leg == "nfip_claims":
        summary["date_of_loss_range"] = _date_range(
            [o["date_of_loss"] for o in observations])
        summary["amount_paid_building_total"] = _sum(
            [o["amount_paid_building"] for o in observations])
        summary["amount_paid_contents_total"] = _sum(
            [o["amount_paid_contents"] for o in observations])
        summary["amount_paid_icc_total"] = _sum(
            [o["amount_paid_icc"] for o in observations])
        summary["amount_paid_all_total"] = _sum(
            [o["amount_paid_building"] for o in observations]
            + [o["amount_paid_contents"] for o in observations]
            + [o["amount_paid_icc"] for o in observations])
        summary["building_damage_total"] = _sum(
            [o["building_damage_amount"] for o in observations])
        summary["by_year_of_loss"] = _counts(observations, "year_of_loss")
        summary["by_flood_event"] = _counts(observations, "flood_event")
    return summary


def fetch_observations(fips: str = FIPS_STARR_COUNTY_TX,
                       opener=None) -> dict:
    """Fetch all three legs and return the full result document."""
    retrieved_at = utcnow_iso()
    legs: dict = {}
    observations: list[dict] = []
    for leg in ("disasters", "public_assistance", "nfip_claims"):
        fetched = fetch_leg(leg, fips, opener=opener)
        parser = PARSERS[leg]
        leg_obs = [parser(rec, fips, fetched["url"], retrieved_at)
                   for rec in fetched["records"]]
        leg_summary = summarize(leg, leg_obs)
        legs[leg] = {
            "entity": fetched["entity"],
            "version": fetched["version"],
            "url": fetched["url"],
            "status": fetched["status"],
            "reported_count": fetched["reported_count"],
            "records_returned": fetched["records_returned"],
            "summary": leg_summary,
        }
        observations.extend(leg_obs)
    disasters = [o for o in observations if o["leg"] == "disasters"]
    pa = [o for o in observations if o["leg"] == "public_assistance"]
    nfip = [o for o in observations if o["leg"] == "nfip_claims"]
    return {
        "sensors": ["57", "73"],
        "source": "FEMA OpenFEMA API (fema.gov/api/open)",
        "catalog_url": CATALOG_URL,
        "retrieved_at": retrieved_at,
        "county": "Starr County, TX",
        "county_fips": fips,
        "legs": legs,
        "summary": {
            "disasters_count": len(disasters),
            "public_assistance_projects": len(pa),
            "nfip_claims": len(nfip),
            "observations_total": len(observations),
            "by_label": {lab: sum(1 for o in observations if o["label"] == lab)
                         for lab in ("VERIFIED", "REPORTED", "UNKNOWN")},
            "pa_project_amount_total": legs["public_assistance"]
                ["summary"].get("project_amount_total"),
            "pa_total_obligated_total": legs["public_assistance"]
                ["summary"].get("total_obligated_total"),
            "nfip_amount_paid_all_total": legs["nfip_claims"]
                ["summary"].get("amount_paid_all_total"),
            "disaster_date_range": legs["disasters"]
                ["summary"].get("declaration_date_range"),
            "nfip_loss_date_range": legs["nfip_claims"]
                ["summary"].get("date_of_loss_range"),
        },
        "observations": observations,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch OpenFEMA disasters, Public Assistance and "
                    "NFIP claims for Starr County, TX.")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--county-fips", default=FIPS_STARR_COUNTY_TX,
                    help="5-digit county FIPS (default: 48427 Starr, TX).")
    args = ap.parse_args(argv)
    result = fetch_observations(fips=args.county_fips)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        s = result["summary"]
        print(f"wrote {args.out}: {s['disasters_count']} disasters, "
              f"{s['public_assistance_projects']} PA projects, "
              f"{s['nfip_claims']} NFIP claims "
              f"({s['observations_total']} observations)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
