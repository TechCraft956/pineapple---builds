"""Recon brief generator — renders a readable Markdown brief from findings.

Three strictly separated sections:
  VERIFIED  — directly observed by a runner (incl. checked-and-absent facts)
  REPORTED  — a source claims it; not independently confirmed (incl.
              CANDIDATE findings: a 200 with no confirming marker)
  UNKNOWN   — planned but not run, walled, or inconclusive
A checked-and-absent result (NOT_FOUND) is a VERIFIED fact about the check,
never an UNKNOWN. A walled/inconclusive source is UNKNOWN, never a finding.

v1.1 (GPT gates 5-6):
- Findings carry per-field confidence + timestamps; the brief shows them.
- When two different sources disagree on the same field for the same
  subject, the brief records the conflict (both values, both sources) in
  a dedicated section instead of silently picking one. Two alternative
  values from the SAME source (e.g. several geocode hits) are not a
  conflict — they are alternatives from one source.
- The brief re-gates its input (structured ethics check) and its rendered
  output (label-shaped PII leak scan) before returning, and carries the
  not-a-consumer-report / no-FCRA-use notice.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .ethics import assert_record_clean, assert_text_clean

# Detail fields comparable across sources for conflict detection.
CONFLICT_FIELDS = frozenset({
    "result", "lat", "lon", "display_name", "locality", "state", "country",
})

NOTICE = ("Not a consumer report: this brief must not be used for "
          "credit, employment, housing, or insurance decisions "
          "(no FCRA-covered use).")


def find_conflicts(items: list[dict]) -> list[dict]:
    """Groups of (subject, field, scope) where >=2 different sources report
    different values. Returns conflict dicts with every value + its source."""
    groups: dict[tuple, dict[str, list[dict]]] = {}
    for it in items:
        detail = it.get("detail") or {}
        scope = detail.get("site") or ""
        src = it["provenance"]["source_id"]
        for field in CONFLICT_FIELDS:
            value = detail.get(field)
            if value in (None, ""):
                continue
            key = (it["subject"], field, scope)
            groups.setdefault(key, {}).setdefault(str(value), []).append(
                {"source_id": src, "source_url": it["provenance"]["source_url"]})
    conflicts = []
    for (subject, field, scope), values in groups.items():
        sources = {v["source_id"] for entries in values.values() for v in entries}
        if len(values) > 1 and len(sources) > 1:
            conflicts.append({
                "subject": subject, "field": field, "scope": scope,
                "values": [{"value": val,
                            "sources": sorted({e["source_id"] for e in entries})}
                           for val, entries in sorted(values.items())],
            })
    return conflicts


def _line(item: dict) -> str:
    p = item["provenance"]
    s = ("- **%s** (confidence %.2f)\n  - source: %s\n  - retrieved: %s · method: %s"
         % (item["title"], item["confidence"], p["source_url"],
            p["retrieved_at_utc"], p["method"]))
    fc = item.get("field_confidence") or {}
    if fc:
        parts = ["%s %.2f @ %s" % (k, v.get("confidence", 0),
                                   v.get("retrieved_at_utc", "?"))
                 for k, v in sorted(fc.items())]
        s += "\n  - per-field confidence: " + "; ".join(parts)
    attr = (item.get("detail") or {}).get("attribution")
    if attr:
        s += "\n  - attribution: " + attr
    return s


def render(subject: str, subject_type: str, items: list[dict],
           plan_steps: list[dict] | None = None,
           skipped_sources: list[dict] | None = None,
           purpose: str | None = None) -> str:
    # Re-gate: structured check on the items, then a leak scan on the text.
    assert_record_clean(items)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verified = [i for i in items if i["provenance"]["verification"] == "VERIFIED"]
    reported = [i for i in items if i["provenance"]["verification"] == "REPORTED"]
    unknown = [i for i in items if i["provenance"]["verification"] == "UNKNOWN"]
    conflicts = find_conflicts(items)
    out = [
        "# Panopticon recon brief — %s (%s)" % (subject, subject_type),
        "",
        "Generated %s · Public open-source signals only · %s" % (now, NOTICE),
    ]
    if purpose:
        out.append("Purpose on record: %s" % purpose)
    out += ["", "Counts: %d verified · %d reported · %d unknown · %d conflicts"
            % (len(verified), len(reported), len(unknown), len(conflicts)), ""]
    out += ["## Verified", ""]
    out += [_line(i) for i in verified] or ["(none)"]
    out += ["", "## Reported (unconfirmed)", ""]
    out += [_line(i) for i in reported] or ["(none)"]
    if conflicts:
        out += ["", "## Conflicts between sources", ""]
        for c in conflicts:
            scope = " (%s)" % c["scope"] if c["scope"] else ""
            out.append("- **%s** — field `%s`%s: sources disagree; no value "
                       "chosen:" % (c["subject"], c["field"], scope))
            for v in c["values"]:
                out.append("  - %r — from %s" % (v["value"], ", ".join(v["sources"])))
    out += ["", "## Unknown / gaps", ""]
    gap_lines = [_line(i) for i in unknown]
    if plan_steps:
        for st in plan_steps:
            if not st["runnable"]:
                gap_lines.append("- Planned, not run: **%s** (%s) — %s"
                                 % (st["name"], st["method"], st["expected"]))
    if skipped_sources:
        for sk in skipped_sources:
            gap_lines.append("- Withheld: `%s` — %s" % (sk["source_id"], sk["reason"]))
    out += gap_lines or ["(none)"]
    out += ["", "---",
            NOTICE,
            "Every line above carries its source URL and retrieval time. "
            "Absence of a finding is not evidence of absence beyond the "
            "checks actually run."]
    text = "\n".join(out) + "\n"
    assert_text_clean(text)
    return text
