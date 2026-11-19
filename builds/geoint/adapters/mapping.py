"""adapters/mapping.py — county AD field mappings onto the canonical schema.

Canonical props (see gis_parcels.py REQUIRED_PROPS + README):
  parcel_id, owner, value, opportunity_score, flood_zone, zoning
  (+ county, city, acreage, data_source, retrieved_at_utc, source_url,
     flood_join_method, flood_caveat)

Verified live 2026-11-17 (see BUILD_REPORT.md for layer indexes/fields):
  * Starr CAD  — BIS Consultants ArcGIS Online hosted FeatureServer,
    StarrCADWebService/FeatureServer/0 "Parcels".
  * Willacy CAD — same BIS platform, WillacyCADWebService/FeatureServer/0
    "Parcels". Field names identical to Starr EXCEPT "Block" (capital B)
    vs Starr's "block". Both services' `county` field is a district CODE
    (e.g. "01", "GWI"), not a county name — the adapter uses the configured
    county name, never that field.
  * TxGIO StratMap (fallback for Hidalgo + Cameron, whose own AD REST paths
    are walled — see BUILD_REPORT.md) — MapServer/0 "StratMap Land Parcels
    48 Most Recent". COUNTY is uppercase ("HIDALGO"); SOURCE names the
    contributing AD. NOTE: /0/query with an envelope returns 0 features on
    this service (verified live); the working path is /MapServer/identify
    at a point, so the StratMap adapter pulls via an identify point grid.

No county AD layer carries zoning: zoning is recorded as "UNKNOWN" and the
record says so. opportunity_score is a documented heuristic (cheap land
relative to a $250k reference scores higher); it is a planning signal, not
a valuation. flood_zone is filled in later by adapters/fema.py.
"""
from __future__ import annotations

ZONING_UNKNOWN = "UNKNOWN"


def opportunity_heuristic(value) -> float:
    """Cheap land scores higher. value in USD; missing value -> 0.5 neutral."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    if v <= 0:
        return 0.5
    return round(max(0.10, min(0.90, 0.90 - 0.40 * (v / 250000.0))), 3)


def _clean_str(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("null", "none") else s


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def map_bis_feature(feature: dict, county: str, data_source: str,
                    retrieved_at_utc: str, source_url: str) -> dict:
    """Map one BIS (Starr/Willacy) Parcels feature onto the canonical schema."""
    p = feature.get("properties", {}) or {}
    market = _num(p.get("market"))
    land = _num(p.get("land_val"))
    imprv = _num(p.get("imprv_val"))
    value = market
    if value is None and (land is not None or imprv is not None):
        value = (land or 0) + (imprv or 0)
    city = _clean_str(p.get("situs_city")) or _clean_str(p.get("city"))
    props = {
        "parcel_id": _clean_str(p.get("geo_id")) or _clean_str(p.get("prop_id_text")),
        "owner": _clean_str(p.get("file_as_name")),
        "value": value,
        "opportunity_score": opportunity_heuristic(value),
        "flood_zone": None,  # filled by FEMA join
        "zoning": ZONING_UNKNOWN,
        "county": county,
        "city": city,
        "acreage": _num(p.get("legal_acreage")),
        "data_source": data_source,
        "retrieved_at_utc": retrieved_at_utc,
        "source_url": source_url,
        "cad_prop_id": _clean_str(p.get("prop_id_text")),
        "cad_geo_id": _clean_str(p.get("geo_id")),
        "cad_legal_desc": _clean_str(p.get("legal_desc")),
        "cad_land_val": land,
        "cad_imprv_val": imprv,
    }
    return {
        "type": "Feature",
        "properties": props,
        "geometry": feature.get("geometry"),
    }


def map_stratmap_result(result: dict, county: str, data_source: str,
                       retrieved_at_utc: str, source_url: str) -> dict:
    """Map one StratMap identify result onto the canonical schema."""
    a = result.get("attributes", {}) or {}
    mkt = _num(a.get("MKT_VALUE"))
    land = _num(a.get("LAND_VALUE"))
    imp = _num(a.get("IMP_VALUE"))
    value = mkt
    if value is None and (land is not None or imp is not None):
        value = (land or 0) + (imp or 0)
    # situs_addr is a combined "123 MAIN ST, MCALLEN" string; city from mail_city.
    city = _clean_str(a.get("MAIL_CITY"))
    if not city:
        addr = _clean_str(a.get("SITUS_ADDR"))
        parts = [x.strip() for x in addr.split(",") if x.strip()]
        city = parts[-1].title() if len(parts) > 1 else ""
    props = {
        "parcel_id": _clean_str(a.get("GEO_ID")) or _clean_str(a.get("PROP_ID")),
        "owner": _clean_str(a.get("OWNER_NAME")),
        "value": value,
        "opportunity_score": opportunity_heuristic(value),
        "flood_zone": None,  # filled by FEMA join
        "zoning": ZONING_UNKNOWN,
        "county": county,
        "city": city,
        "acreage": _num(a.get("LEGAL_AREA")),
        "data_source": data_source,
        "retrieved_at_utc": retrieved_at_utc,
        "source_url": source_url,
        "cad_prop_id": _clean_str(a.get("PROP_ID")),
        "cad_geo_id": _clean_str(a.get("GEO_ID")),
        "cad_legal_desc": _clean_str(a.get("LEGAL_DESC")),
        "cad_land_val": land,
        "cad_imprv_val": imp,
        "stratmap_fips": _clean_str(a.get("FIPS")),
        "stratmap_tax_year": _clean_str(a.get("TAX_YEAR")),
        "stratmap_source": _clean_str(a.get("SOURCE")),
    }
    geom = result.get("geometry") or {}
    rings = geom.get("rings")
    geometry = ({"type": "Polygon", "coordinates": rings}
                if rings else None)
    return {"type": "Feature", "properties": props, "geometry": geometry}
