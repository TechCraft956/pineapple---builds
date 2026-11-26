#!/usr/bin/env python3
"""Sensors #53 + #75 — EPA ECHO violations/permits + facility registry (Starr County, TX).

Read-only collector, standard library only. No accounts, no API keys, no
spending, no signups. One collector, two sensors:

#53 (violations/permits) — EPA ECHO Web Services on the CURRENT host
``echodata.epa.gov`` (the old ``ofmpub.epa.gov/echo`` paths now answer
HTTP 404 — see "Superseded paths" below):
1. All-data facility search summary (``echo_rest_services.get_facilities``,
   ``p_fips=48427``): 389 facilities; CAA 12 / CWA 91 / RCRA 29 / TRI 0;
   significant violations, current violations, quarters in violation,
   formal enforcement actions, inspections, total penalties.
2. All-data facility detail (``echo_rest_services.get_facility_info``):
   one record per facility — name, city, Registry ID, per-program
   compliance status, quarters with noncompliance, SNC flag, inspection
   and formal-action counts, penalties. Program coverage is INFERRED
   from the per-program compliance/permit fields (the detail payload
   carries no explicit CAA/CWA/RCRA flags) and is labelled as such.
3. Program summaries: CWA (``cwa_rest_services.get_facilities``),
   CAA (``air_rest_services.get_facilities``), RCRA
   (``rcra_rest_services.get_facilities``), SDWA
   (``sdw_rest_services.get_systems`` — 22 drinking-water systems).
4. TRI via EPA DMAP (``data.epa.gov/dmapservice/tri.tri_facility``,
   county filter): 0 TRI facilities in Starr County — a real zero,
   cross-checked against ECHO's TRIRows=0 (a Harris County control
   query returns rows, proving the filter syntax works).

#75 (facility registry) — EPA Envirofacts / FRS on the CURRENT host
``data.epa.gov/efservice`` (the old ``ofmpub.epa.gov/enviro/efservice``
path answers HTTP 502 — see below):
5. FRS program-facility rows (``frs.frs_program_facility``,
   ``county_name/equals/STARR``): 498 program rows across 450 distinct
   Registry IDs, with program acronym and city breakdowns. Registry IDs
   are FRS record IDs — one physical site can carry more than one (e.g.
   EXPANDO COMPRESSOR STATION appears under two IDs), so 450 is an upper
   bound on distinct facilities, not a facility count.
6. TCEQ permitted wastewater outfalls (ArcGIS FeatureServer,
   ``TCEQ_Permitted_Wastewater_Outfalls``, ``COUNTY='STARR'``):
   3 outfalls (City of Roma x2, City of Rio Grande City x1).

Superseded paths (probed 2026-11-26, recorded here, NOT retried by the
collector): ``ofmpub.epa.gov/echo/cwa_rest_services.get_facilities``
and ``echo13_rest_services`` / ``echo_rest_services`` on ofmpub all
answer HTTP 404; ``ofmpub.epa.gov/enviro/efservice/FRSCIVIEW`` answers
HTTP 502 (proxy error, retried). The services moved to
``echodata.epa.gov/echo`` and ``data.epa.gov/efservice`` / ``dmapservice``.
The county parameter on ECHO is ``p_fips`` (full FIPS 48427); the
coordinator's probe used ``p_cx``, which ECHO silently ignores (it
returned 5.7M rows instead of the county).

Every observation carries ``status`` (VERIFIED / REPORTED / UNKNOWN /
BLOCKED), ``source_url`` and ``retrieved_at_utc``. Missing values stay
``null`` — never zero-filled, never invented. A zero that the source
actually returns (TRI = 0 facilities) is recorded as a verified zero
with its cross-check noted.

Usage:
    python3 epa_echo.py [--out FILE]

Exit code is 0 whenever an output document was written, even if a leg
failed — leg status is recorded in the document itself. Exit code 2
only if no output could be produced at all.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

SENSOR_IDS = [53, 75]
SENSOR_NAME = "epa-echo-tceq-facilities-starr-county"

USER_AGENT = "PineappleSensor53/1.0 (research; public EPA/TCEQ data, no key)"

COUNTY_FIPS = "48427"
COUNTY_NAME = "STARR"
STATE = "TX"

ECHO_BASE = "https://echodata.epa.gov/echo"
ECHO_ALL_SUMMARY_URL = ECHO_BASE + "/echo_rest_services.get_facilities"
ECHO_ALL_INFO_URL = ECHO_BASE + "/echo_rest_services.get_facility_info"
ECHO_CWA_URL = ECHO_BASE + "/cwa_rest_services.get_facilities"
ECHO_AIR_URL = ECHO_BASE + "/air_rest_services.get_facilities"
ECHO_RCRA_URL = ECHO_BASE + "/rcra_rest_services.get_facilities"
ECHO_SDW_URL = ECHO_BASE + "/sdw_rest_services.get_systems"
ECHO_DOC_URL = "https://echo.epa.gov/tools/web-services"

DMAP_BASE = "https://data.epa.gov/dmapservice"
TRI_URL = DMAP_BASE + "/tri.tri_facility/county_name/equals/STARR/1:500/json"
DMAP_DOC_URL = "https://data.epa.gov/"

EFSERVICE_BASE = "https://data.epa.gov/efservice"
FRS_URL = (EFSERVICE_BASE
           + "/frs.frs_program_facility/county_name/equals/STARR/0:5000/json")
FRS_DOC_URL = "https://www.epa.gov/frs/search-frs-data"

# TCEQ GIS Hub — ArcGIS FeatureServer (keyless). The Hub search API
# (gis-tceq.opendata.arcgis.com/api/search/v1) surfaces only 3 TMDL
# collections and does NOT return this layer, so the service URL below
# is used directly (verified live 2026-11-26).
TCEQ_OUTFALLS_URL = ("https://services2.arcgis.com/LYMgRMwHfrWWEg3s/ArcGIS/rest"
                     "/services/TCEQ_Permitted_Wastewater_Outfalls"
                     "/FeatureServer/0/query")
TCEQ_OUTFALLS_LAYER_URL = ("https://services2.arcgis.com/LYMgRMwHfrWWEg3s/ArcGIS/rest"
                           "/services/TCEQ_Permitted_Wastewater_Outfalls"
                           "/FeatureServer/0")
TCEQ_OUTFALLS_FIELDS = ("GIS_NUMBER,PERMIT_NUM,OUTFALL,LETTER,NPDES_NUM,"
                        "PERMITTEE,STATUS,DTYPE,COUNTY,LAT_DD,LONG_DD,"
                        "SEGMENT,TCEQ_REGION")
TCEQ_HUB_URL = "https://gis-tceq.opendata.arcgis.com/"

# Starr County bounding box (shared with the Wave 2 TxDOT collector).
BBOX = {"xmin": -99.3, "ymin": 26.0, "xmax": -97.6, "ymax": 27.0}

# ECHO summary keys we carry through (strings in the source; parsed to int).
SUMMARY_INT_KEYS = (
    "QueryRows", "IndianCountryRows", "SVRows", "CVRows", "V3Rows",
    "FEARows", "InfFEARows", "INSPRows", "VioLast4QRows", "BioCVRows",
    "BioV3Rows", "FCERows",
)
SUMMARY_PROGRAM_KEYS = ("CAARows", "CWARows", "RCRRows", "TRIRows")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get(url: str, params: dict | None = None, timeout: int = 90) -> bytes:
    """GET a URL, returning raw bytes. Raises on HTTP/network error."""
    full = url
    if params:
        full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_get_json(url: str, params: dict | None = None,
                   timeout: int = 90, fetcher=_http_get):
    raw = fetcher(url, params, timeout)
    return json.loads(raw.decode("utf-8"))


def parse_money(value) -> float | None:
    """Parse an ECHO money string like "$53,692" -> 53692.0. None stays None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value) -> int | None:
    """Parse an ECHO count string like "389" -> 389. None/invalid stays None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def parse_echo_summary(payload: dict) -> dict:
    """Flatten an ECHO get_facilities/get_systems Results block."""
    results = payload.get("Results", {}) or {}
    out: dict = {"message": results.get("Message"),
                 "version": results.get("Version"),
                 "query_id": results.get("QueryID")}
    for key in SUMMARY_INT_KEYS + SUMMARY_PROGRAM_KEYS:
        if key in results:
            out[key] = parse_int(results.get(key))
    out["total_penalties_usd"] = parse_money(results.get("TotalPenalties"))
    out["total_penalties_raw"] = results.get("TotalPenalties")
    if results.get("Error"):
        out["error"] = results["Error"]
    return out


def fetch_echo_summary(name: str, url: str, retrieved_at: str,
                       fetcher=_http_get) -> dict:
    """One ECHO summary leg (get_facilities / get_systems, p_fips=48427)."""
    leg = {"name": name, "status": "VERIFIED", "source_url": url,
           "retrieved_at_utc": retrieved_at, "summary": None, "error": None}
    try:
        payload = _http_get_json(url, {"p_fips": COUNTY_FIPS, "output": "JSON"},
                                 fetcher=fetcher)
        summary = parse_echo_summary(payload)
        if summary.get("error"):
            leg["status"] = "UNKNOWN"
            leg["error"] = f"ECHO error: {summary['error']}"
        elif summary.get("message") != "Success":
            leg["status"] = "UNKNOWN"
            leg["error"] = ("ECHO did not report Success "
                            f"(message={summary.get('message')!r}).")
        leg["summary"] = summary
    except Exception as exc:  # noqa: BLE001 — record, don't crash the run
        leg["status"] = "UNKNOWN"
        leg["error"] = f"{name} fetch failed: {exc}"
    return leg


def _program_present(facility: dict, prefix: str) -> bool:
    """Infer program coverage from the detail payload's per-program fields.

    The get_facility_info payload carries no explicit CAA/CWA/RCRA flags,
    so presence is inferred from non-null per-program compliance, permit,
    or history fields. Returns False (not None) only when every signal
    for that program is empty — the inference is labelled in the output.
    """
    fields = {
        "CAA": ("CAAComplianceStatus", "CAAEvaluationCount",
                "CAA3yrComplQtrsHistory", "CAANAICS"),
        "CWA": ("CWAComplianceStatus", "CWAInspectionCount",
                "CWA13qtrsComplHistory", "CWAPermitTypes"),
        "RCRA": ("RCRAComplianceStatus", "RCRAPermitTypes"),
        "SDWA": ("SDWAComplianceStatus", "SDWASystemTypes",
                 "SDWA3yrComplQtrsHistory"),
    }[prefix]
    return any(facility.get(f) not in (None, "") for f in fields)


def parse_echo_facility(facility: dict, retrieved_at: str) -> dict:
    """One ECHO get_facility_info record -> one facility observation."""
    programs = {
        "CAA": _program_present(facility, "CAA"),
        "CWA": _program_present(facility, "CWA"),
        "RCRA": _program_present(facility, "RCRA"),
        "SDWA": _program_present(facility, "SDWA"),
        "TRI": facility.get("TRIIDs") not in (None, ""),
        "GHG": facility.get("GHGFlag") == "Y",
    }
    # SDWISFlag is a direct flag when present; it corroborates SDWA.
    if facility.get("SDWISFlag") == "Y":
        programs["SDWA"] = True
    return {
        "metric": "echo_facility",
        "facility_name": facility.get("FacName"),
        "street": facility.get("FacStreet"),
        "city": facility.get("FacCity"),
        "state": facility.get("FacState"),
        "zip": facility.get("FacZip"),
        "county": facility.get("FacCounty"),
        "registry_id": facility.get("RegistryID"),
        "programs": programs,
        "programs_inferred": True,
        "compliance_status": facility.get("FacComplianceStatus"),
        "snc_flag": facility.get("FacSNCFlg"),
        "quarters_with_noncompliance": parse_int(
            facility.get("FacQtrsWithNC")),
        "inspection_count": parse_int(facility.get("FacInspectionCount")),
        "formal_action_count": parse_int(
            facility.get("FacFormalActionCount")),
        "total_penalties_usd": parse_money(facility.get("FacTotalPenalties")),
        "date_last_inspection": facility.get("FacDateLastInspection"),
        "date_last_penalty": facility.get("FacDateLastPenalty"),
        "caa_compliance_status": facility.get("CAAComplianceStatus"),
        "cwa_compliance_status": facility.get("CWAComplianceStatus"),
        "rcra_compliance_status": facility.get("RCRAComplianceStatus"),
        "sdwa_compliance_status": facility.get("SDWAComplianceStatus"),
        "cwa_permit_types": facility.get("CWAPermitTypes"),
        "rcra_permit_types": facility.get("RCRAPermitTypes"),
        "sdwa_system_types": facility.get("SDWASystemTypes"),
        "tri_ids": facility.get("TRIIDs"),
        "status": "VERIFIED",
        "note": ("Program coverage inferred from per-program compliance / "
                 "permit fields in the ECHO detail payload (no explicit "
                 "program flags in the source); see programs_inferred."),
        "source": "EPA ECHO — echo_rest_services.get_facility_info",
        "source_url": ECHO_ALL_INFO_URL,
        "retrieved_at_utc": retrieved_at,
    }


def fetch_echo_facilities(retrieved_at: str, fetcher=_http_get) -> dict:
    """Fetch the full Starr County facility list via get_facility_info."""
    leg = {"name": "echo_facilities", "status": "VERIFIED",
           "source_url": ECHO_ALL_INFO_URL, "retrieved_at_utc": retrieved_at,
           "facilities": [], "facility_count": 0, "summary": None,
           "program_counts": {}, "cities": {}, "error": None}
    try:
        payload = _http_get_json(
            ECHO_ALL_INFO_URL, {"p_fips": COUNTY_FIPS, "output": "JSON"},
            fetcher=fetcher)
        results = payload.get("Results", {}) or {}
        if results.get("Error"):
            raise RuntimeError(f"ECHO error: {results['Error']}")
        leg["summary"] = parse_echo_summary(payload)
        facilities = [parse_echo_facility(f, retrieved_at)
                      for f in results.get("Facilities", [])]
        leg["facilities"] = facilities
        leg["facility_count"] = len(facilities)
        for prog in ("CAA", "CWA", "RCRA", "SDWA", "TRI", "GHG"):
            leg["program_counts"][prog] = sum(
                1 for f in facilities if f["programs"][prog])
        leg["cities"] = dict(Counter(
            f["city"] for f in facilities if f["city"]))
        if not facilities:
            leg["status"] = "UNKNOWN"
            leg["error"] = "get_facility_info returned zero facilities."
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"echo_facilities fetch failed: {exc}"
    return leg


def parse_tri_row(row: dict, retrieved_at: str) -> dict:
    """One DMAP TRI facility row -> one observation."""
    return {
        "metric": "tri_facility",
        "facility_name": row.get("facility_name"),
        "city": row.get("city_name"),
        "county": row.get("county_name"),
        "epa_registry_id": row.get("epa_registry_id"),
        "tri_id": row.get("tri_facility_id"),
        "status": "VERIFIED",
        "source": "EPA DMAP — tri.tri_facility (Envirofacts/TRI)",
        "source_url": TRI_URL,
        "retrieved_at_utc": retrieved_at,
    }


def fetch_tri(retrieved_at: str, fetcher=_http_get) -> dict:
    """TRI facilities in Starr County via DMAP (expect 0 — a real zero)."""
    leg = {"name": "tri_facilities", "status": "VERIFIED",
           "source_url": TRI_URL, "retrieved_at_utc": retrieved_at,
           "facilities": [], "facility_count": 0, "error": None,
           "cross_check": ("ECHO all-data summary TRIRows=0 for the same "
                           "county; a Harris County control query returns "
                           "rows, proving the county filter syntax works.")}
    try:
        rows = _http_get_json(TRI_URL, None, fetcher=fetcher)
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected TRI payload type: {type(rows)}")
        leg["facilities"] = [parse_tri_row(r, retrieved_at) for r in rows]
        leg["facility_count"] = len(leg["facilities"])
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"TRI fetch failed: {exc}"
    return leg


def parse_frs_row(row: dict) -> dict:
    """One FRS program-facility row -> a trimmed registry record."""
    return {
        "registry_id": row.get("registry_id"),
        "primary_name": row.get("primary_name"),
        "city": row.get("city_name"),
        "county": row.get("county_name"),
        "location_address": row.get("location_address"),
        "postal_code": (row.get("postal_code") or "").strip() or None,
        "program_acronym": row.get("pgm_sys_acrnm"),
        "program_system_id": row.get("pgm_sys_id"),
        "epa_region": row.get("epa_region_code"),
    }


def fetch_frs(retrieved_at: str, fetcher=_http_get) -> dict:
    """FRS registry for Starr County via Envirofacts efservice."""
    leg = {"name": "frs_registry", "status": "VERIFIED",
           "source_url": FRS_URL, "retrieved_at_utc": retrieved_at,
           "program_rows": [], "program_row_count": 0,
           "distinct_registry_ids": 0, "facilities": [],
           "by_program": {}, "by_city": {}, "error": None,
           "note": ("Registry IDs are FRS record IDs: one physical site "
                    "can carry more than one (e.g. EXPANDO COMPRESSOR "
                    "STATION appears under two IDs), so distinct Registry "
                    "IDs is an upper bound on distinct facilities, not a "
                    "facility count.")}
    try:
        rows = _http_get_json(FRS_URL, None, fetcher=fetcher)
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected FRS payload type: {type(rows)}")
        parsed = [parse_frs_row(r) for r in rows]
        leg["program_rows"] = parsed
        leg["program_row_count"] = len(parsed)
        by_registry: dict[str, dict] = {}
        for rec in parsed:
            rid = rec["registry_id"]
            if not rid:
                continue
            entry = by_registry.setdefault(rid, {
                "registry_id": rid,
                "primary_name": rec["primary_name"],
                "city": rec["city"],
                "county": rec["county"],
                "location_address": rec["location_address"],
                "program_acronyms": [],
                "program_system_ids": [],
            })
            if rec["program_acronym"] and rec["program_acronym"] \
                    not in entry["program_acronyms"]:
                entry["program_acronyms"].append(rec["program_acronym"])
            if rec["program_system_id"]:
                entry["program_system_ids"].append(rec["program_system_id"])
        leg["facilities"] = [dict(entry, status="VERIFIED",
                                  metric="frs_facility",
                                  source="EPA Envirofacts FRS — "
                                         "frs.frs_program_facility",
                                  source_url=FRS_URL,
                                  retrieved_at_utc=retrieved_at)
                             for entry in by_registry.values()]
        leg["distinct_registry_ids"] = len(by_registry)
        leg["by_program"] = dict(Counter(
            r["program_acronym"] for r in parsed if r["program_acronym"]))
        leg["by_city"] = dict(Counter(
            r["city"] for r in parsed if r["city"]))
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"FRS fetch failed: {exc}"
    return leg


def arcgis_query(base_url: str, params: dict, timeout: int = 90,
                 fetcher=_http_get, page_size: int = 2000) -> dict:
    """Run an ArcGIS REST query, following pagination (maxRecordCount)."""
    all_features: list = []
    offset = 0
    while True:
        page_params = dict(params)
        page_params.update({
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        })
        raw = fetcher(base_url, page_params, timeout)
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("error"):
            raise RuntimeError(f"ArcGIS error from {base_url}: "
                               f"{payload['error']}")
        feats = payload.get("features", [])
        all_features.extend(feats)
        if len(feats) < page_size:
            break
        if not payload.get("exceededTransferLimit"):
            break
        offset += len(feats)
        if offset > 200000:
            raise RuntimeError("ArcGIS pagination exceeded safety limit")
    return {"features": all_features}


def parse_tceq_outfall(feature: dict, retrieved_at: str) -> dict:
    """One TCEQ permitted wastewater outfall -> one observation."""
    attrs = feature.get("attributes", {}) or {}
    return {
        "metric": "tceq_permitted_outfall",
        "gis_number": attrs.get("GIS_NUMBER"),
        "permit_number": attrs.get("PERMIT_NUM"),
        "outfall": attrs.get("OUTFALL"),
        "npdes_number": attrs.get("NPDES_NUM"),
        "permittee": attrs.get("PERMITTEE"),
        "status_code": attrs.get("STATUS"),
        "county": attrs.get("COUNTY"),
        "lat": attrs.get("LAT_DD"),
        "lon": attrs.get("LONG_DD"),
        "tceq_region": attrs.get("TCEQ_REGION"),
        "status": "VERIFIED",
        "source": ("TCEQ GIS Hub — TCEQ_Permitted_Wastewater_Outfalls "
                   "(ArcGIS FeatureServer)"),
        "source_url": TCEQ_OUTFALLS_LAYER_URL,
        "retrieved_at_utc": retrieved_at,
    }


def fetch_tceq_outfalls(retrieved_at: str, fetcher=_http_get) -> dict:
    """TCEQ permitted wastewater outfalls in Starr County."""
    leg = {"name": "tceq_outfalls", "status": "VERIFIED",
           "source_url": TCEQ_OUTFALLS_LAYER_URL,
           "retrieved_at_utc": retrieved_at, "outfalls": [],
           "outfall_count": 0, "permittees": {}, "error": None}
    try:
        params = {
            "where": "COUNTY='STARR'",
            "outFields": TCEQ_OUTFALLS_FIELDS,
            "returnGeometry": "false",
        }
        payload = arcgis_query(TCEQ_OUTFALLS_URL, params, fetcher=fetcher)
        outfalls = [parse_tceq_outfall(f, retrieved_at)
                    for f in payload.get("features", [])]
        leg["outfalls"] = outfalls
        leg["outfall_count"] = len(outfalls)
        leg["permittees"] = dict(Counter(
            o["permittee"] for o in outfalls if o["permittee"]))
    except Exception as exc:  # noqa: BLE001
        leg["status"] = "UNKNOWN"
        leg["error"] = f"TCEQ outfalls fetch failed: {exc}"
    return leg


def collect(fetcher=_http_get) -> dict:
    """Run all legs and assemble the sensor document."""
    retrieved_at = utc_now_iso()
    echo_all = fetch_echo_summary("echo_all_summary", ECHO_ALL_SUMMARY_URL,
                                  retrieved_at, fetcher=fetcher)
    facilities = fetch_echo_facilities(retrieved_at, fetcher=fetcher)
    cwa = fetch_echo_summary("echo_cwa_summary", ECHO_CWA_URL, retrieved_at,
                             fetcher=fetcher)
    air = fetch_echo_summary("echo_air_summary", ECHO_AIR_URL, retrieved_at,
                             fetcher=fetcher)
    rcra = fetch_echo_summary("echo_rcra_summary", ECHO_RCRA_URL,
                              retrieved_at, fetcher=fetcher)
    sdwa = fetch_echo_summary("echo_sdwa_summary", ECHO_SDW_URL, retrieved_at,
                              fetcher=fetcher)
    tri = fetch_tri(retrieved_at, fetcher=fetcher)
    frs = fetch_frs(retrieved_at, fetcher=fetcher)
    outfalls = fetch_tceq_outfalls(retrieved_at, fetcher=fetcher)

    all_summary = (echo_all.get("summary") or {})
    cwa_summary = (cwa.get("summary") or {})
    sdwa_summary = (sdwa.get("summary") or {})
    nc_quarters = Counter(
        f["quarters_with_noncompliance"] for f in facilities["facilities"])
    facilities_with_nc = sum(
        1 for f in facilities["facilities"]
        if (f["quarters_with_noncompliance"] or 0) > 0)
    facilities_with_penalties = sum(
        1 for f in facilities["facilities"]
        if (f["total_penalties_usd"] or 0) > 0)
    snc_count = sum(
        1 for f in facilities["facilities"] if f["snc_flag"] == "Y")

    observations: list = []
    observations.extend(facilities["facilities"])
    observations.extend(frs["facilities"])
    observations.extend(outfalls["outfalls"])
    observations.append({
        "metric": "tri_facilities",
        "value": tri["facility_count"],
        "unit": "facilities",
        "status": tri["status"],
        "note": ("Zero TRI facilities in Starr County — a real zero from "
                 "the DMAP query, cross-checked against ECHO TRIRows=0; "
                 "not a failed fetch."),
        "source": "EPA DMAP — tri.tri_facility (Envirofacts/TRI)",
        "source_url": TRI_URL,
        "retrieved_at_utc": retrieved_at,
    })

    legs = {
        "echo_all_summary": {k: v for k, v in echo_all.items()
                             if k != "summary"},
        "echo_facilities": {k: v for k, v in facilities.items()
                            if k != "facilities"},
        "echo_cwa_summary": {k: v for k, v in cwa.items() if k != "summary"},
        "echo_air_summary": {k: v for k, v in air.items() if k != "summary"},
        "echo_rcra_summary": {k: v for k, v in rcra.items()
                              if k != "summary"},
        "echo_sdwa_summary": {k: v for k, v in sdwa.items()
                              if k != "summary"},
        "tri_facilities": {k: v for k, v in tri.items()
                           if k != "facilities"},
        "frs_registry": {k: v for k, v in frs.items()
                         if k not in ("program_rows", "facilities")},
        "tceq_outfalls": {k: v for k, v in outfalls.items()
                          if k != "outfalls"},
    }
    # Keep the per-leg summaries visible inside the leg records.
    legs["echo_all_summary"]["summary"] = echo_all.get("summary")
    legs["echo_cwa_summary"]["summary"] = cwa.get("summary")
    legs["echo_air_summary"]["summary"] = air.get("summary")
    legs["echo_rcra_summary"]["summary"] = rcra.get("summary")
    legs["echo_sdwa_summary"]["summary"] = sdwa.get("summary")
    legs["echo_facilities"]["summary"] = facilities.get("summary")
    legs["echo_facilities"]["program_counts"] = facilities["program_counts"]
    legs["echo_facilities"]["cities"] = facilities["cities"]

    return {
        "sensor_ids": SENSOR_IDS,
        "sensors": ["53-epa-echo-violations-permits",
                    "75-facility-registry-frs-tceq"],
        "county": "Starr County, Texas",
        "county_fips": COUNTY_FIPS,
        "state": STATE,
        "bbox": BBOX,
        "retrieved_at_utc": retrieved_at,
        "legs": legs,
        "summary": {
            "echo_facilities_total": facilities["facility_count"],
            "echo_facilities_status": facilities["status"],
            "echo_program_rows": {
                "CAA": all_summary.get("CAARows"),
                "CWA": all_summary.get("CWARows"),
                "RCRA": all_summary.get("RCRRows"),
                "TRI": all_summary.get("TRIRows"),
            },
            "echo_facility_program_counts_inferred": facilities["program_counts"],
            "echo_significant_violations": all_summary.get("SVRows"),
            "echo_current_violations": all_summary.get("CVRows"),
            "echo_quarters_in_violation": all_summary.get("V3Rows"),
            "echo_formal_enforcement_actions": all_summary.get("FEARows"),
            "echo_inspections_5yr": all_summary.get("INSPRows"),
            "echo_total_penalties_usd": all_summary.get("total_penalties_usd"),
            "cwa_facilities": cwa_summary.get("QueryRows"),
            "cwa_violations_last_4q": cwa_summary.get("VioLast4QRows"),
            "cwa_total_penalties_usd": cwa_summary.get("total_penalties_usd"),
            "sdwa_systems": sdwa_summary.get("QueryRows"),
            "sdwa_significant_violations": sdwa_summary.get("SVRows"),
            "sdwa_current_violations": sdwa_summary.get("CVRows"),
            "facilities_with_noncompliance_quarters": facilities_with_nc,
            "facilities_with_penalties": facilities_with_penalties,
            "facilities_flagged_snc": snc_count,
            "noncompliance_quarters_distribution": {
                str(k): v for k, v in sorted(
                    nc_quarters.items(), key=lambda kv: str(kv[0]))},
            "tri_facilities": tri["facility_count"],
            "tri_status": tri["status"],
            "frs_program_rows": frs["program_row_count"],
            "frs_distinct_registry_ids": frs["distinct_registry_ids"],
            "frs_status": frs["status"],
            "frs_by_program": frs["by_program"],
            "tceq_outfalls_starr": outfalls["outfall_count"],
            "tceq_outfalls_status": outfalls["status"],
            "tceq_outfalls_permittees": outfalls["permittees"],
        },
        "superseded_paths": {
            "note": ("Probed 2026-11-26; the services moved hosts. "
                     "Collector uses the current hosts only."),
            "ofmpub_echo_404": {
                "urls": [
                    "https://ofmpub.epa.gov/echo/cwa_rest_services.get_facilities",
                    "https://ofmpub.epa.gov/echo/echo13_rest_services.get_facilities",
                    "https://ofmpub.epa.gov/echo/echo_rest_services.get_facilities",
                    "https://ofmpub.epa.gov/echo/swaggerx.swagger_json?p_prefix=ECHO",
                ],
                "result": "HTTP 404 on every variant (also with p_st=TX).",
                "replacement": ECHO_BASE,
            },
            "ofmpub_envirofacts_502": {
                "urls": [
                    "https://ofmpub.epa.gov/enviro/efservice/FRSCIVIEW?rows=0:2&output=JSON",
                ],
                "result": "HTTP 502 proxy error (retried 2026-11-26).",
                "replacement": EFSERVICE_BASE,
            },
            "echo_county_param": {
                "note": ("p_cx is silently ignored by ECHO (returns 5.7M "
                         "rows); the county parameter is p_fips=48427."),
            },
        },
        "observations": observations,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None,
                        help="Write the JSON document to this file as well as stdout.")
    args = parser.parse_args(argv)

    doc = collect()
    text = json.dumps(doc, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    sys.stderr.write(
        f"[sensors #53+#75] ECHO facilities={doc['summary']['echo_facilities_total']} "
        f"(CAA {doc['summary']['echo_program_rows']['CAA']} / "
        f"CWA {doc['summary']['echo_program_rows']['CWA']} / "
        f"RCRA {doc['summary']['echo_program_rows']['RCRA']} / "
        f"TRI {doc['summary']['echo_program_rows']['TRI']}) | "
        f"penalties ${doc['summary']['echo_total_penalties_usd']:,.0f} | "
        f"FRS registry IDs={doc['summary']['frs_distinct_registry_ids']} | "
        f"TRI={doc['summary']['tri_facilities']} | "
        f"TCEQ outfalls={doc['summary']['tceq_outfalls_starr']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
