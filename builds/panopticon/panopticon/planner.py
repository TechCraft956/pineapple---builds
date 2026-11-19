"""Panopticon query planner.

Given a subject + type (+ optional explicit purpose), produce a deterministic,
ordered recon plan. Enforcement:
- ethics.excluded sources are NEVER planned.
- ethics.purpose_required sources are planned only when a purpose is supplied,
  and never as CODE steps (no automated runner touches them).
- username plans are REFUSED without a documented legitimate purpose
  (PurposeRequiredError) — no cross-site private-person profile compilation.
- Order: runnable CODE steps first, then other CODE, then BROWSER, then HUMAN.
"""
from __future__ import annotations

from .ethics import PurposeRequiredError
from .registry import by_id

# Registry source ids that have a real v1 runner wired.
RUNNERS = {
    "runner:username_presence": "username",
    "runner:place_geocode": "place",
}

_METHOD_ORDER = {"CODE": 0, "BROWSER": 1, "HUMAN": 2}


def plan(subject_type: str, subject: str, registry: dict,
         purpose: str | None = None) -> list[dict]:
    # GPT gate 1: username enumeration is restricted to user-owned accounts
    # or public professional/organizational subjects with a documented
    # legitimate purpose. Without one the plan is refused, with a reason —
    # never silently planned, never compiled for a private person.
    if subject_type == "username" and not purpose:
        raise PurposeRequiredError(
            "username plan refused: no documented legitimate purpose for "
            "subject %r. Username enumeration is restricted to user-owned "
            "accounts or public professional/organizational subjects with "
            "a purpose on record; re-run with --purpose \"...\". No "
            "cross-site private-person profile is compiled." % (subject,))
    idx = by_id(registry)
    steps = []
    for s in registry["sources"]:
        eth = s["ethics"]
        if eth["excluded"]:
            continue
        if subject_type not in s["subject_types"]:
            continue
        if eth["purpose_required"]:
            if not purpose:
                continue
            if s["method"] == "CODE":
                continue  # hard rule: no CODE runner on purpose-gated sources
        runnable = s["id"] in RUNNERS
        steps.append({
            "source_id": s["id"],
            "name": s["name"],
            "category": s["category"],
            "method": s["method"],
            "runnable": runnable,
            "runner": RUNNERS.get(s["id"]),
            "expected": s["returns"],
            "url": s["url"],
            "purpose_required": eth["purpose_required"],
            "notes": s.get("notes", ""),
        })
    steps.sort(key=lambda st: (0 if st["runnable"] else 1,
                               _METHOD_ORDER[st["method"]],
                               st["source_id"]))
    for i, st in enumerate(steps, 1):
        st["order"] = i
    return steps


def skipped(registry: dict, subject_type: str,
            purpose: str | None = None) -> list[dict]:
    """Sources relevant to the subject type but withheld, with reasons —
    surfaced in briefs so a gate is visible, not silent."""
    out = []
    for s in registry["sources"]:
        eth = s["ethics"]
        if eth["excluded"]:
            out.append({"source_id": s["id"], "reason": "excluded by ethics gate"})
        elif subject_type in s["subject_types"] and eth["purpose_required"] and not purpose:
            out.append({"source_id": s["id"],
                        "reason": "purpose_required: no purpose supplied"})
        elif (subject_type in s["subject_types"] and eth["purpose_required"]
              and purpose and s["method"] == "CODE"):
            out.append({"source_id": s["id"],
                        "reason": "purpose_required: CODE execution barred"})
    return out
