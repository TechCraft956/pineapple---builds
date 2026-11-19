"""Normalize findings to the Pineapple feed/opportunity item shape.

Feed shape (from the recovered modules' items() contract):
  title, category, source, action, est_value, risk, location, url, confidence
Panopticon adds a provenance block to every item:
  provenance: {source_url, retrieved_at_utc, method, verification, source_id}
Every item passes the ethics gate before it is emitted.
"""
from __future__ import annotations

from .ethics import assert_record_clean

_RISK = {"VERIFIED": "LOW", "REPORTED": "MED", "UNKNOWN": "MED"}


def normalize(finding: dict) -> dict:
    item = {
        "title": finding["claim"],
        "category": "intelligence",
        "source": "panopticon:" + finding["source_id"],
        "action": ("review finding" if finding["verification"] != "UNKNOWN"
                   else "source inconclusive — retry or route to browser/human step"),
        "est_value": None,  # recon reduces risk / informs; it is not a priced opportunity
        "risk": _RISK.get(finding["verification"], "MED"),
        "location": (finding.get("detail") or {}).get("locality"),
        "url": finding["source_url"],
        "confidence": finding["confidence"],
        "field_confidence": finding.get("field_confidence") or {
            "overall": {"confidence": finding["confidence"],
                        "retrieved_at_utc": finding["retrieved_at_utc"],
                        "source_id": finding["source_id"]},
        },
        "provenance": {
            "source_url": finding["source_url"],
            "retrieved_at_utc": finding["retrieved_at_utc"],
            "method": finding["method"],
            "verification": finding["verification"],
            "source_id": finding["source_id"],
        },
        "subject": finding["subject"],
        "subject_type": finding["subject_type"],
        "detail": finding.get("detail") or {},
    }
    assert_record_clean(item)
    return item


def normalize_all(findings: list[dict]) -> list[dict]:
    return [normalize(f) for f in findings]
