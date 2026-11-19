"""
doctrine - the engine that checks every recommendation against the Pineapple
Constitution (PINEAPPLE_DOCTRINE.md / 00_INDEX/doctrine.json).

Facts alone never produce a recommendation. Doctrine governs. A recommendation
that violates doctrine is flagged and down-ranked even if the numbers look good.
Pure stdlib.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


def _root(start: Path) -> Path:
    start = start.resolve()
    for p in [start, *start.parents]:
        if (p / ".pineapple_root").exists():
            return p
    return start.parent


def load_doctrine() -> dict:
    p = _root(Path(__file__)) / "00_INDEX" / "doctrine.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"rules": [], "autonomy_default": "recommend_only"}


@dataclass
class DoctrineVerdict:
    aligned: bool
    penalty: float = 0.0          # subtracted from an item's overall score
    flags: list = field(default_factory=list)
    checked: int = 0

    def to_dict(self) -> dict:
        return {"aligned": self.aligned, "penalty": self.penalty, "flags": self.flags, "checked": self.checked}


def check(item: dict, domain: str = "all", doctrine: dict | None = None) -> DoctrineVerdict:
    """item may contain: roi_pct, borrower_score, risk, capital, blind_signal, conflicts_family."""
    doc = doctrine or load_doctrine()
    flags, penalty, checked = [], 0.0, 0
    for rule in doc.get("rules", []):
        if rule["domain"] not in (domain, "all"):
            continue
        f = rule.get("field")
        if rule["type"] in ("min", "max") and f in item and item[f] is not None:
            checked += 1
            v = float(item[f])
            bad = (v < rule["threshold"]) if rule["type"] == "min" else (v > rule["threshold"])
            if bad:
                flags.append(rule["message"])
                penalty += 12
        elif rule["type"] == "forbid_flag" and item.get(f):
            checked += 1
            flags.append(rule["message"])
            penalty += 25
        elif rule["type"] == "soft" and item.get(f):
            checked += 1
            flags.append(rule["message"])
            penalty += 18
    return DoctrineVerdict(aligned=not flags, penalty=round(penalty, 1), flags=flags, checked=checked)


if __name__ == "__main__":
    good = {"roi_pct": 80, "risk": 20, "capital": 30}
    bad = {"roi_pct": 18, "risk": 90, "blind_signal": True}
    print("GOOD:", check(good, "assets").to_dict())
    print("BAD :", check(bad, "trading").to_dict())
