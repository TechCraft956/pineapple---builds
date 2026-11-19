"""Markdown brief renderer — offline, from lake records (cached data).

Contract line, e.g.:
  Falcon Reservoir — 22.8% of conservation capacity (storage 355,620
  ac-ft, TWDB, retrieved 2026-11-18 05:00 UTC), falling over 30 days
  (-18,200 ac-ft).
Missing elements render as "unknown" (e.g. "% unknown (elevation only)").
"""
from __future__ import annotations


def _fmt_num(v):
    if v is None:
        return "unknown"
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return f"{v:,}"


def _fmt_pct(p):
    if p is None:
        return None
    s = f"{p:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _fmt_change(c):
    if c is None:
        return "unknown"
    if isinstance(c, float) and c == int(c):
        c = int(c)
    return f"{c:+,}"


def _retrieved(record, group="current"):
    prov = (record.get("provenance") or {}).get(group) or {}
    ts = prov.get("retrieved_at_utc") or ""
    # 2026-11-18T05:00:00Z -> 2026-11-18 05:00 UTC
    if len(ts) >= 16:
        return f"{ts[:10]} {ts[11:16]} UTC"
    return ts or "unknown"


def brief_line(record: dict) -> str:
    name = record["lake"]
    cur = record["current"]
    pct = record.get("pct_conservation")
    src = cur.get("primary_source") or "unknown source"
    retrieved = _retrieved(record)
    trend = record.get("trend") or {}
    direction = trend.get("direction", "unknown")

    if pct is not None:
        head = (f"{name} — {_fmt_pct(pct)}% of conservation capacity "
                f"(storage {_fmt_num(cur.get('storage_acre_ft'))} ac-ft, "
                f"{src}, retrieved {retrieved})")
    elif cur.get("storage_acre_ft") is None and \
            cur.get("elevation_ft") is not None:
        head = (f"{name} — % unknown (elevation only) "
                f"(elevation {_fmt_num(cur.get('elevation_ft'))} ft, "
                f"{src}, retrieved {retrieved})")
    elif cur.get("storage_acre_ft") is not None:
        head = (f"{name} — % unknown (conservation capacity unknown) "
                f"(storage {_fmt_num(cur.get('storage_acre_ft'))} ac-ft, "
                f"{src}, retrieved {retrieved})")
    else:
        head = f"{name} — % unknown (no current data)"

    if direction == "unknown" or trend.get("change_acre_ft") is None:
        tail = "trend unknown over 30 days"
    else:
        tail = (f"{direction} over 30 days "
                f"({_fmt_change(trend['change_acre_ft'])} ac-ft)")

    line = f"{head}, {tail}."
    cross = record.get("cross_source") or {}
    if cross.get("status") == "disagree":
        sd = record.get("sources_detail") or {}
        line += (f" Sources disagree ({cross.get('basis')}): USGS "
                 f"{sd.get('usgs')}, TWDB {sd.get('twdb')} — both "
                 f"reported, not averaged.")
    return line


def render_brief(records: list[dict], generated_at_utc: str = "") -> str:
    out = ["# Lake Capacities — Texas Reservoirs", ""]
    if generated_at_utc:
        out += [f"_Generated {generated_at_utc} from cached records._", ""]
    for r in records:
        out.append("- " + brief_line(r))
    out += ["", "## Summary table", "",
            "| Lake | % conservation | Storage (ac-ft) | Elevation (ft) "
            "| Trend (30d) | Change (ac-ft) | Confidence |",
            "|---|---|---|---|---|---|---|"]
    for r in records:
        cur, tr = r["current"], r.get("trend") or {}
        pct = r.get("pct_conservation")
        out.append(
            f"| {r['lake']} | "
            f"{_fmt_pct(pct) + '%' if pct is not None else 'unknown'} | "
            f"{_fmt_num(cur.get('storage_acre_ft'))} | "
            f"{_fmt_num(cur.get('elevation_ft'))} | "
            f"{tr.get('direction', 'unknown')} | "
            f"{_fmt_change(tr.get('change_acre_ft'))} | "
            f"{r.get('confidence', 'unknown')} |")
    out.append("")
    return "\n".join(out)
