"""Normalization into lake records, per the build-brief contract.

Rules enforced here:
- pct_conservation is computed ONLY when the storage counted against
  conservation capacity AND the conservation capacity are both present
  AND both dated. An elevation alone is never a percentage.
- Trend: last storage value vs the value ~30 days earlier, from a daily
  storage series. steady = |change| <= 0.5% of conservation capacity.
  A series with <2 points or spanning <7 days is "unknown".
- Cross-source: USGS vs TWDB are compared, never averaged. Agreement =
  storage within 2% (of TWDB total storage) when both storages exist,
  else elevation within 1.0 ft when both elevations exist. Confidence
  0.85 when two sources agree, 0.6 for a single source or a disagreement;
  on disagreement both values are kept in `sources_detail`.
"""
from __future__ import annotations

STORAGE_TOL = 0.02   # 2% relative
ELEV_TOL_FT = 1.0
STEADY_FRACTION = 0.005  # 0.5% of conservation capacity
MIN_TREND_SPAN_DAYS = 7


def compute_pct(storage, capacity, storage_date, capacity_date):
    """Percent of conservation capacity, or None (unknown-stays-unknown)."""
    if storage is None or capacity is None:
        return None
    if not storage_date or not capacity_date:
        return None
    if capacity <= 0:
        return None
    return round(100.0 * storage / capacity, 1)


def classify_trend(series, capacity, window_days=30):
    """series: [(date_str, storage_acre_ft)] sorted. Returns trend dict."""
    unknown = {"window_days": window_days, "change_acre_ft": None,
               "direction": "unknown"}
    pts = [(d, v) for d, v in (series or []) if d and v is not None]
    if len(pts) < 2:
        return unknown
    from datetime import date
    try:
        span = (date.fromisoformat(pts[-1][0])
                - date.fromisoformat(pts[0][0])).days
    except ValueError:
        return unknown
    if span < MIN_TREND_SPAN_DAYS:
        return unknown
    change = round(pts[-1][1] - pts[0][1], 1)
    if capacity:
        threshold = STEADY_FRACTION * capacity
        if abs(change) <= threshold:
            direction = "steady"
        else:
            direction = "rising" if change > 0 else "falling"
    else:
        direction = "rising" if change > 0 else (
            "falling" if change < 0 else "steady")
    return {"window_days": window_days, "change_acre_ft": change,
            "direction": direction,
            "from_date": pts[0][0], "to_date": pts[-1][0]}


def compare_sources(usgs: dict, twdb: dict) -> dict:
    """usgs/twdb: {'storage_acre_ft': total storage, 'elevation_ft': ...}.
    Storage comparison uses TOTAL reservoir storage on both sides (TWDB
    `volume`), because TWDB conservation_storage is a treaty share for
    the binational/shared lakes."""
    detail = {"usgs": usgs, "twdb": twdb, "status": "single_source",
              "basis": None}
    if not usgs or not twdb:
        return detail
    us, ts = usgs.get("storage_acre_ft"), twdb.get("storage_acre_ft")
    ue, te = usgs.get("elevation_ft"), twdb.get("elevation_ft")
    if us is not None and ts:
        rel = abs(us - ts) / ts
        detail["basis"] = f"storage rel diff {rel:.3%}"
        detail["status"] = "agree" if rel <= STORAGE_TOL else "disagree"
        return detail
    if ue is not None and te is not None:
        diff = abs(ue - te)
        detail["basis"] = f"elevation diff {diff:.2f} ft"
        detail["status"] = "agree" if diff <= ELEV_TOL_FT else "disagree"
        return detail
    return detail


def build_record(entry, usgs_iv_site, usgs_dv_site, twdb_recent,
                 twdb_history, provenance):
    """Assemble one lake record. All inputs are parsed client outputs
    (any may be None). `provenance`: {group: {source_url, retrieved_at_utc}}.
    """
    from usgs_client import split_current, STORAGE_PARAM

    # --- USGS current ---
    u_storage = u_elev = u_obs = None
    if usgs_iv_site:
        u_storage, u_elev, u_obs = split_current(usgs_iv_site)

    # --- TWDB current (primary for storage/capacity: TWDB owns the
    # conservation figures; daily-average, dated by `timestamp`) ---
    t = twdb_recent or {}
    t_date = t.get("timestamp")
    cons_storage = t.get("conservation_storage_acre_ft")
    total_storage = t.get("total_storage_acre_ft")
    capacity = t.get("conservation_capacity_acre_ft")
    if capacity is None:
        capacity = entry.get("conservation", {}).get("capacity_acre_ft")
        capacity_date = entry.get("conservation", {}).get("as_of")
        capacity_source = entry.get("conservation", {}).get("source")
    else:
        capacity_date = t_date
        capacity_source = "TWDB Water Data for Texas"

    # Storage counted against conservation capacity: TWDB
    # conservation_storage when present, else total storage, else USGS.
    if cons_storage is not None:
        storage, storage_date, storage_src = cons_storage, t_date, "TWDB"
    elif total_storage is not None:
        storage, storage_date, storage_src = total_storage, t_date, "TWDB"
    elif u_storage is not None:
        storage, storage_date, storage_src = u_storage, (
            u_obs or "")[:10], "USGS"
    else:
        storage, storage_date, storage_src = None, None, None

    elevation = t.get("elevation_ft")
    if elevation is None:
        elevation = u_elev
    observed = (t_date + "T00:00:00Z") if t_date else u_obs

    pct = compute_pct(storage, capacity, storage_date, capacity_date)

    # --- Trend: TWDB 30-day conservation-storage series first, then
    # TWDB total storage, then USGS daily storage. ---
    series = []
    series_src = None
    if twdb_history:
        s = [(r["date"], r["conservation_storage_acre_ft"])
             for r in twdb_history
             if r.get("conservation_storage_acre_ft") is not None]
        if len(s) >= 2:
            series, series_src = s, "TWDB"
        else:
            s = [(r["date"], r["reservoir_storage_acre_ft"])
                 for r in twdb_history
                 if r.get("reservoir_storage_acre_ft") is not None]
            if len(s) >= 2:
                series, series_src = s, "TWDB"
    if not series and usgs_dv_site and STORAGE_PARAM in usgs_dv_site:
        series = usgs_dv_site[STORAGE_PARAM]
        series_src = "USGS"
    trend = classify_trend(series, capacity)
    if series_src:
        trend["source"] = series_src

    # --- Cross-source ---
    usgs_side = ({"storage_acre_ft": u_storage, "elevation_ft": u_elev}
                 if (u_storage is not None or u_elev is not None) else None)
    twdb_side = ({"storage_acre_ft": total_storage,
                  "elevation_ft": t.get("elevation_ft")}
                 if (total_storage is not None
                     or t.get("elevation_ft") is not None) else None)
    cross = compare_sources(usgs_side, twdb_side)
    n_sources = sum(1 for s in (usgs_side, twdb_side) if s)
    if cross["status"] == "agree":
        confidence = 0.85
    else:
        confidence = 0.6  # single source, or sources disagree

    record = {
        "lake": entry["name"],
        "aliases": entry.get("aliases", []),
        "region": entry.get("region"),
        "river": entry.get("river"),
        "sources": {
            "usgs_site_id": entry.get("usgs_site_id"),
            "usgs_status": entry.get("usgs_status"),
            "twdb_id": entry.get("twdb_slug"),
            "twdb_status": entry.get("twdb_status"),
        },
        "current": {
            "storage_acre_ft": storage,
            "storage_basis": ("conservation_storage"
                              if cons_storage is not None
                              and storage == cons_storage else "total_storage"),
            "total_storage_acre_ft": total_storage,
            "usgs_storage_acre_ft": u_storage,
            "elevation_ft": elevation,
            "usgs_elevation_ft": u_elev,
            "observed_at_utc": observed,
            "observed_date": t_date or (u_obs or "")[:10] or None,
            "primary_source": storage_src or ("TWDB" if t else None),
        },
        "conservation": {
            "capacity_acre_ft": capacity,
            "total_capacity_acre_ft":
                t.get("total_capacity_at_conservation_pool_acre_ft")
                or entry.get("conservation", {}).get(
                    "total_capacity_acre_ft"),
            "pool_elevation_ft": t.get("conservation_pool_elevation_ft")
                or entry.get("conservation", {}).get("pool_elevation_ft"),
            "source": capacity_source,
            "as_of": capacity_date,
        },
        "pct_conservation": pct,
        "pct_published_twdb": t.get("percent_full_published"),
        "trend": trend,
        "cross_source": cross,
        "confidence": confidence,
        "sources_detail": {"usgs": usgs_side, "twdb": twdb_side},
        "provenance": provenance,
    }
    return record


def record_to_item(record: dict, url: str | None = None) -> dict:
    """items()-style dict for later feed wiring."""
    pct = record.get("pct_conservation")
    title = (f"{record['lake']} — {pct}% conservation capacity"
             if pct is not None else
             f"{record['lake']} — % unknown")
    sources = []
    if record["sources"].get("twdb_status") == "WIRED":
        sources.append("TWDB Water Data for Texas")
    if record["sources"].get("usgs_status") == "WIRED":
        sources.append("USGS NWIS")
    return {
        "title": title,
        "category": "PLACES",
        "source": " + ".join(sources) if sources else "unknown",
        "action": "Monitor lake level / drought awareness",
        "est_value": None,
        "risk": "low",
        "location": record.get("region"),
        "url": url,
        "confidence": record.get("confidence", 0.6),
    }
