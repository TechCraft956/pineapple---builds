"""
pineapple_quant - the life quant scoring spine for Pineapple OS.

Score ANY decision item on five dimensions and collapse to one comparable number.
You stop debating; you compare scores.

    roi         higher is better   (expected upside)
    time        lower is better    (hours/effort required)
    risk        lower is better    (chance / size of loss)
    difficulty  lower is better    (skill / complexity)
    capital     lower is better    (cash tied up)

overall = weighted blend, with the four "lower is better" dims inverted (100 - x).
Weights live in 00_INDEX/quant_weights.json and are nudged by the learning loop,
so scores get sharper as outcomes accumulate. Pure stdlib.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

DIMENSIONS = ("roi", "time", "risk", "difficulty", "capital")
LOWER_IS_BETTER = ("time", "risk", "difficulty", "capital")

# ROI-dominant defaults (the upside should drive the call; friction discounts it).
DEFAULT_WEIGHTS = {"roi": 0.44, "time": 0.12, "risk": 0.18, "difficulty": 0.10, "capital": 0.16}


def _root(start: Path) -> Path:
    start = start.resolve()
    for p in [start, *start.parents]:
        if (p / ".pineapple_root").exists():
            return p
    return start.parent


def weights_path() -> Path:
    return _root(Path(__file__)) / "00_INDEX" / "quant_weights.json"


def load_weights() -> dict:
    p = weights_path()
    if p.exists():
        try:
            w = json.loads(p.read_text(encoding="utf-8")).get("weights", {})
            return {d: float(w.get(d, DEFAULT_WEIGHTS[d])) for d in DIMENSIONS}
        except Exception:
            pass
    return dict(DEFAULT_WEIGHTS)


def save_weights(weights: dict, note: str = "") -> None:
    p = weights_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"weights": weights, "note": note}, indent=2), encoding="utf-8")


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


@dataclass
class QuantInput:
    roi: float = 0.0          # 0-100 expected upside
    time: float = 50.0        # 0-100 effort
    risk: float = 50.0        # 0-100 downside
    difficulty: float = 50.0  # 0-100 complexity
    capital: float = 50.0     # 0-100 cash required

    def normalized(self) -> dict:
        return {d: _clamp(getattr(self, d)) for d in DIMENSIONS}


@dataclass
class QuantScore:
    overall: float
    dims: dict = field(default_factory=dict)
    contributions: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def score(qi: QuantInput, weights: dict | None = None) -> QuantScore:
    w = weights or load_weights()
    dims = qi.normalized()
    wsum = sum(w.get(d, 0) for d in DIMENSIONS) or 1.0
    contributions, total = {}, 0.0
    for d in DIMENSIONS:
        effective = (100.0 - dims[d]) if d in LOWER_IS_BETTER else dims[d]
        c = (w.get(d, 0) / wsum) * effective
        contributions[d] = round(c, 2)
        total += c
    return QuantScore(overall=round(_clamp(total), 1), dims=dims,
                      contributions=contributions, weights=dict(w))


def score_dict(d: dict, weights: dict | None = None) -> QuantScore:
    return score(QuantInput(**{k: d.get(k, QuantInput.__dataclass_fields__[k].default)
                               for k in DIMENSIONS}), weights)


def from_opportunity(opp: dict) -> QuantInput:
    """Heuristically map an IntelModule Opportunity dict to quant dimensions.
    Modules can override by putting an explicit `quant` dict in opp['fields']."""
    f = opp.get("fields", {}) or {}
    if isinstance(f.get("quant"), dict):
        q = f["quant"]
        return QuantInput(**{k: float(q.get(k, getattr(QuantInput, k, 50))) for k in DIMENSIONS})

    roi = float(opp.get("score", 0))  # module score is a decent ROI proxy
    risk_map = {"LOW": 20, "MEDIUM": 50, "HIGH": 80, "UNKNOWN": 55}
    risk = risk_map.get(str(opp.get("risk", "UNKNOWN")).upper(), 55)
    roi_est = opp.get("roi_estimate")
    capital = 50.0
    if isinstance(roi_est, (int, float)):
        # bigger dollar outlay implied -> more capital; rough log-ish bucketing
        amt = abs(float(roi_est))
        capital = 20 if amt < 1000 else 40 if amt < 10000 else 60 if amt < 50000 else 80
    return QuantInput(roi=roi, time=40, risk=risk, difficulty=35, capital=capital)


if __name__ == "__main__":
    # Demo with the user's TW200 example
    tw200 = QuantInput(roi=84, time=22, risk=18, difficulty=15, capital=28)
    s = score(tw200)
    print("TW200 listing")
    for d in DIMENSIONS:
        print("  %-11s %5.1f  (contrib %.1f)" % (d, s.dims[d], s.contributions[d]))
    print("  OVERALL     %5.1f" % s.overall)
    print("  weights:", {k: round(v, 2) for k, v in s.weights.items()})
