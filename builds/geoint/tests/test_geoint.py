"""GEOINT tests — offline, no network (socket is blocked at module level).

Covers brief Task 4 + GPT-folded hardening:
  * flood discount boundaries incl. unknown zone -> conservative HIGH 0.70
  * geometry validation (missing geometry, non-Feature, empty FC, missing props)
  * centroid/bbox on Polygon vs MultiPolygon
  * per-county adapter field mapping on RECORDED live fixtures
  * FEMA join correctness on fixtures (AE -> 0.88, X -> 1.00, unknown -> 0.70,
    centroid-only caveat, polygon-contained, no-intersection inference)
  * no outbound calls in offline tests (socket blocked; fetch_json must fail)
  * feed writer mapping: every record carries the warning + data_source and
    validates against the feed opportunity schema

Run:  ../.venv/bin/python -m pytest tests/ -v
(from ~/workspace/pineapple/builds/feed-dash; or any python with pytest +
jsonschema on the path)
"""
import json
import socket
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

import gis_parcels  # noqa: E402
from adapters import fema, mapping  # noqa: E402
from writers import geoint_writer  # noqa: E402

FIXTURES = WORKSPACE / "fixtures"
FEED_SCHEMA = json.loads(
    (WORKSPACE / "feed-service-copy" / "opportunity.schema.json").read_text())


# ---------------------------------------------------------------------------
# Block the network for the whole module: any accidental outbound call fails.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("offline test attempted a network call")
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _parcel(lon, lat, size=0.001, zone=None, opp=1.0, value=100000):
    x0, x1 = lon - size / 2, lon + size / 2
    y0, y1 = lat - size / 2, lat + size / 2
    props = {"parcel_id": "TEST-1", "owner": "SAMPLE: Test", "value": value,
             "opportunity_score": opp, "zoning": "Residential",
             "county": "Hidalgo", "city": "McAllen", "acreage": 0.25,
             "data_source": "sample"}
    if zone is not None:
        props["flood_zone"] = zone
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon",
                         "coordinates": [[[x0, y0], [x1, y0], [x1, y1],
                                          [x0, y1], [x0, y0]]]}}


def _zone_fc(zone, lon=0.0, lat=0.0, size=1.0, subty=None, dfirm="48000C"):
    x0, x1 = lon - size / 2, lon + size / 2
    y0, y1 = lat - size / 2, lat + size / 2
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"FLD_ZONE": zone, "ZONE_SUBTY": subty,
                        "SFHA_TF": "T" if zone != "X" else "F",
                        "DFIRM_ID": dfirm},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[x0, y0], [x1, y0], [x1, y1],
                                       [x0, y1], [x0, y0]]]}}]}


# ---------------------------------------------------------------------------
# 1. Flood discount boundaries (GPT hardening: unknown -> HIGH 0.70)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("zone,expected_risk,expected_discount", [
    ("X", "LOW", 1.00), ("X500", "LOW", 1.00),
    ("A", "MED", 0.88), ("AE", "MED", 0.88),
    ("AO", "MED", 0.88), ("AH", "MED", 0.88),
    ("V", "HIGH", 0.70), ("VE", "HIGH", 0.70),
    ("x", "LOW", 1.00), ("ae", "MED", 0.88), (" ve ", "HIGH", 0.70),
])
def test_flood_discount_table(zone, expected_risk, expected_discount):
    assert gis_parcels.flood_risk(zone) == expected_risk
    assert gis_parcels.score_parcel(
        {"opportunity_score": 1.0, "flood_zone": zone}) == expected_discount


@pytest.mark.parametrize("zone", ["ZZZ", "", None, "D", "0.2 PCT", "UNKNOWN"])
def test_unknown_zone_is_conservatively_high(zone):
    assert gis_parcels.flood_risk(zone) == "HIGH"
    assert gis_parcels.score_parcel(
        {"opportunity_score": 1.0, "flood_zone": zone}) == 0.70
    assert gis_parcels.score_parcel(
        {"opportunity_score": 0.5, "flood_zone": zone}) == 0.35


# ---------------------------------------------------------------------------
# 2. Geometry validation + centroid/bbox
# ---------------------------------------------------------------------------
def _write_fc(tmp_path, fc):
    p = tmp_path / "t.geojson"
    p.write_text(json.dumps(fc))
    return p


def test_load_parcels_rejects_bad_inputs(tmp_path):
    base = _parcel(-98.2, 26.2, zone="X")
    # not a FeatureCollection
    with pytest.raises(ValueError):
        gis_parcels.load_parcels(_write_fc(tmp_path, {"type": "Feature"}))
    # empty features
    with pytest.raises(ValueError):
        gis_parcels.load_parcels(
            _write_fc(tmp_path, {"type": "FeatureCollection", "features": []}))
    # non-Feature member
    bad = {"type": "FeatureCollection",
           "features": [{"type": "NotAFeature", "properties": {}}]}
    with pytest.raises(ValueError):
        gis_parcels.load_parcels(_write_fc(tmp_path, bad))
    # missing geometry
    no_geom = dict(base, geometry=None)
    with pytest.raises(ValueError):
        gis_parcels.load_parcels(_write_fc(
            tmp_path, {"type": "FeatureCollection", "features": [no_geom]}))
    # missing required prop
    props = dict(base["properties"])
    del props["zoning"]
    missing = dict(base, properties=props)
    with pytest.raises(ValueError):
        gis_parcels.load_parcels(_write_fc(
            tmp_path, {"type": "FeatureCollection", "features": [missing]}))


def test_centroid_bbox_polygon_vs_multipolygon():
    poly = _parcel(-98.2, 26.2, size=0.002, zone="X")
    multi = dict(poly)
    multi["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[-98.201, 26.199], [-98.199, 26.199], [-98.199, 26.201],
              [-98.201, 26.201], [-98.201, 26.199]]],
            [[[-98.191, 26.209], [-98.189, 26.209], [-98.189, 26.211],
              [-98.191, 26.211], [-98.191, 26.209]]],
        ]}
    fc_poly = {"type": "FeatureCollection", "features": [poly]}
    fc_multi = {"type": "FeatureCollection", "features": [multi]}
    assert gis_parcels.bbox(fc_poly) == pytest.approx([-98.201, 26.199, -98.199, 26.201])
    assert gis_parcels.centroid(fc_poly) == pytest.approx([-98.2, 26.2])
    assert gis_parcels.bbox(fc_multi) == pytest.approx([-98.201, 26.199, -98.189, 26.211])
    assert gis_parcels.centroid(fc_multi) == pytest.approx([-98.195, 26.205])


def test_sample_data_contract():
    fc = gis_parcels.load_parcels()
    assert len(fc["features"]) == 12
    zones = {f["properties"]["flood_zone"] for f in fc["features"]}
    assert {"X", "A", "AE", "VE"} <= zones
    zonings = {f["properties"]["zoning"] for f in fc["features"]}
    assert len(zonings) >= 3
    its = gis_parcels.items()
    assert len(its) == 12
    for it in its:
        assert it["data_source"] == "sample"
        assert it["warning"] == gis_parcels.PLANNING_WARNING
        assert it["confidence"] == 0.45
    assert gis_parcels.selftest() == 0


# ---------------------------------------------------------------------------
# 3. Per-county adapter field mapping on RECORDED live fixtures
# ---------------------------------------------------------------------------
def test_bis_starr_mapping_on_recorded_fixture():
    raw = _load("starr_q.json")
    assert len(raw["features"]) == 3
    f = mapping.map_bis_feature(raw["features"][0], "Starr",
                                "starr_cad_live", "2026-11-17T22:00:00Z",
                                "https://example.invalid/starr")
    p = f["properties"]
    assert p["parcel_id"] == "00165-07400-00900-023910"  # geo_id, not prop_id
    assert p["owner"].startswith("RUIZ ELIZA")
    assert p["value"] == 187490
    assert p["acreage"] == 66.96
    assert p["city"] == "ROMA"
    assert p["county"] == "Starr"  # configured name, NOT the "01" code field
    assert p["zoning"] == "UNKNOWN"  # CAD layers carry no zoning
    assert p["data_source"] == "starr_cad_live"
    assert p["retrieved_at_utc"] and p["source_url"]
    assert p["flood_zone"] is None  # filled by FEMA join, not the CAD layer
    assert f["geometry"]["type"] == "Polygon"


def test_bis_willacy_mapping_on_recorded_fixture():
    raw = _load("willacy_q.json")
    assert len(raw["features"]) == 3
    f = mapping.map_bis_feature(raw["features"][1], "Willacy",
                                "willacy_cad_live", "2026-11-17T22:00:00Z",
                                "https://example.invalid/willacy")
    p = f["properties"]
    assert p["parcel_id"] == "L1080-00-00000-002-00-0"
    assert p["owner"] == "Luna, Juan Hernandez"
    assert p["value"] == 18750
    assert p["county"] == "Willacy"  # NOT the "GWI" code in the county field
    assert p["zoning"] == "UNKNOWN"


def test_stratmap_mapping_on_recorded_fixture():
    raw = _load("stratmap_identify_sample.json")
    assert raw["results"], "fixture has no identify results"
    r = raw["results"][0]
    f = mapping.map_stratmap_result(r, "Hidalgo", "stratmap_live",
                                    "2026-11-17T22:00:00Z",
                                    "https://example.invalid/stratmap")
    p = f["properties"]
    assert p["parcel_id"] == r["attributes"]["GEO_ID"]
    assert p["owner"] == r["attributes"]["OWNER_NAME"]
    assert p["value"] == float(r["attributes"]["MKT_VALUE"])  # identify returns strings
    assert p["county"] == "Hidalgo"
    assert p["data_source"] == "stratmap_live"
    assert p["stratmap_tax_year"] == "2026"
    assert "HIDALGO APPRAISAL DISTRICT" in p["stratmap_source"]
    assert f["geometry"]["type"] == "Polygon"


def test_opportunity_heuristic():
    assert mapping.opportunity_heuristic(None) == 0.5
    assert mapping.opportunity_heuristic(0) == 0.5
    cheap = mapping.opportunity_heuristic(10000)
    pricey = mapping.opportunity_heuristic(1000000)
    assert cheap > pricey
    assert 0.10 <= mapping.opportunity_heuristic(10 ** 9) <= 0.90


# ---------------------------------------------------------------------------
# 4. FEMA join correctness on fixtures
# ---------------------------------------------------------------------------
def test_fema_join_ae_parcel_scores_088():
    parcel = _parcel(0.0, 0.0, size=0.1, zone=None)
    out = fema.join_flood_zone(parcel, _zone_fc("AE"))
    p = out["properties"]
    assert p["flood_zone"] == "AE"
    assert p["flood_join_method"] == "polygon_contained"
    assert p["flood_caveat"] is None
    assert gis_parcels.score_parcel(
        {"opportunity_score": 1.0, "flood_zone": p["flood_zone"]}) == 0.88


def test_fema_join_x_parcel_scores_100():
    parcel = _parcel(0.0, 0.0, size=0.1, zone=None)
    out = fema.join_flood_zone(parcel, _zone_fc("X"))
    assert out["properties"]["flood_zone"] == "X"
    assert gis_parcels.score_parcel(
        {"opportunity_score": 1.0, "flood_zone": "X"}) == 1.00


def test_fema_join_centroid_only_carries_caveat():
    # Long parcel straddling the AE boundary: centroid inside, vertices not.
    parcel = _parcel(0.45, 0.0, size=1.0, zone=None)
    out = fema.join_flood_zone(parcel, _zone_fc("AE", size=1.0))
    p = out["properties"]
    assert p["flood_zone"] == "AE"
    assert p["flood_join_method"] == "centroid_in_polygon"
    assert p["flood_caveat"] == fema.CAVEAT_CENTROID
    assert "cannot establish parcel-wide hazard" in p["flood_caveat"]


def test_fema_join_no_intersection_infers_x_with_caveat():
    parcel = _parcel(50.0, 50.0, size=0.1, zone=None)
    out = fema.join_flood_zone(
        parcel, {"type": "FeatureCollection", "features": []})
    p = out["properties"]
    assert p["flood_zone"] == "X"
    assert p["flood_join_method"] == "no_intersection"
    assert "not polygon-confirmed" in p["flood_caveat"]


def test_fema_join_unknown_zone_kept_verbatim_scores_high():
    parcel = _parcel(0.0, 0.0, size=0.1, zone=None)
    out = fema.join_flood_zone(parcel, _zone_fc("D"))
    p = out["properties"]
    assert p["flood_zone"] == "D"
    assert gis_parcels.flood_risk("D") == "HIGH"
    assert gis_parcels.score_parcel(
        {"opportunity_score": 1.0, "flood_zone": "D"}) == 0.70


def test_fema_join_on_recorded_live_ae_polygons():
    """Real recorded NFHL polygons (coastal Cameron Co, DFIRM 48061C)."""
    fc = _load("fema_coast.json")
    assert fc["features"], "recorded FEMA fixture is empty"
    poly = fc["features"][0]["geometry"]
    assert poly["type"] == "Polygon"
    # Find a point guaranteed inside the first recorded AE polygon.
    ring = poly["coordinates"][0]
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    inside = None
    for ix in range(1, 20):
        for iy in range(1, 20):
            pt = (min(xs) + (max(xs) - min(xs)) * ix / 20,
                  min(ys) + (max(ys) - min(ys)) * iy / 20)
            if fema.point_in_polygon(pt, poly):
                inside = pt
                break
        if inside:
            break
    assert inside is not None, "no interior point found in recorded polygon"
    parcel = _parcel(inside[0], inside[1], size=0.0002, zone=None)
    out = fema.join_flood_zone(parcel, fc)
    p = out["properties"]
    assert p["flood_zone"] == "AE"
    assert p["fema_dfirm_id"] == "48061C"
    assert p["flood_join_method"] in ("centroid_in_polygon", "polygon_contained")
    if p["flood_join_method"] == "centroid_in_polygon":
        assert "cannot establish parcel-wide hazard" in p["flood_caveat"]


# ---------------------------------------------------------------------------
# 5. No outbound calls offline
# ---------------------------------------------------------------------------
def test_fetch_json_fails_with_network_blocked():
    from adapters import client
    with pytest.raises(Exception):
        client.fetch_json("https://hazards.fema.gov/arcgis/rest/services/"
                          "public/NFHL/MapServer?f=json")


# ---------------------------------------------------------------------------
# 6. Feed writer mapping (pure; schema-validated)
# ---------------------------------------------------------------------------
def test_feed_writer_records_carry_warning_and_data_source():
    import jsonschema
    items = gis_parcels.items()
    records = geoint_writer.map_items(items)
    assert len(records) == 12
    for rec in records:
        jsonschema.validate(rec, FEED_SCHEMA)
        assert rec["provenance"]["warning"] == gis_parcels.PLANNING_WARNING
        assert rec["provenance"]["data_source"] == "sample"
        assert gis_parcels.PLANNING_WARNING in rec["risk_notes"]
        assert rec["approval_status"] == "PENDING"
        assert rec["id"].startswith("geoint:")
        assert rec["type"] == "other"


def test_feed_writer_live_item_keeps_join_provenance():
    live = json.loads((WORKSPACE / "live" / "all_live.geojson").read_text())
    assert len(live["features"]) == 20
    items = gis_parcels.items(WORKSPACE / "live" / "all_live.geojson")
    assert len(items) == 20
    assert {i["confidence"] for i in items} == {0.8}
    records = geoint_writer.map_items(items)
    for rec in records:
        assert rec["provenance"]["data_source"] in (
            "starr_cad_live", "willacy_cad_live", "stratmap_live")
        assert rec["provenance"]["flood_join_method"] in (
            "centroid_in_polygon", "polygon_contained", "no_intersection")
        assert gis_parcels.PLANNING_WARNING in rec["risk_notes"]
