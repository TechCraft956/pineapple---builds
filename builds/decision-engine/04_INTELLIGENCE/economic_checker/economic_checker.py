#!/usr/bin/env python3
"""
Economic Checker  —  04_INTELLIGENCE
Track macro signals that change your local decisions: mortgage rates, oil prices,
construction permits, manufacturing announcements. Output: regime classification +
actionable alerts (when to buy/flip/hold/lend).

Run:  python economic_checker.py
Input: input/indicators.json (sample created on first run)
       Each indicator: {name, value, prev, unit, direction_good}
       direction_good = "down" or "up": which direction is favorable for you.
"""
from __future__ import annotations
import sys
from pathlib import Path

def _boot():
    p = Path(__file__).resolve()
    for a in [p, *p.parents]:
        if (a / ".pineapple_root").exists():
            sys.path.insert(0, str(a / "_lib"))
            return
_boot()
import pineapple_intel as pi  # noqa: E402


# name -> (weight, when-it-moves-the-right-way, action)
PLAYBOOK = {
    "mortgage_rate_30y": (30, "lower rates → buyers return, RE flips move faster",
                          "Rates dropping: accelerate RE acquisition/flip timelines"),
    "oil_price": (15, "lower fuel → cheaper logistics & flips, more discretionary spend",
                  "Fuel cheap: vehicle/equipment flips & travel cheaper"),
    "construction_permits": (25, "rising permits → local growth, demand for assets",
                             "Permits rising: get ahead of demand in growth pockets"),
    "manufacturing_announcements": (30, "new plants → jobs → housing & service demand",
                                    "Plant announced: buy nearby RE / position services early"),
    "unemployment_local": (20, "lower unemployment → stronger borrowers & demand",
                           "Jobs strong: Family Bank risk lower, demand higher"),
}


SAMPLE = [
    {"name": "mortgage_rate_30y", "value": 6.1, "prev": 6.8, "unit": "%", "direction_good": "down"},
    {"name": "oil_price", "value": 74, "prev": 81, "unit": "$/bbl", "direction_good": "down"},
    {"name": "construction_permits", "value": 142, "prev": 120, "unit": "permits/mo", "direction_good": "up"},
    {"name": "manufacturing_announcements", "value": 2, "prev": 0, "unit": "count", "direction_good": "up"},
    {"name": "unemployment_local", "value": 4.4, "prev": 4.1, "unit": "%", "direction_good": "down"},
]


class EconomicChecker(pi.IntelModule):
    module_id = "economic_checker"
    module_name = "Economic Checker"
    layer = "04_INTELLIGENCE"
    one_rule = {"makes_money": True, "reduces_risk": True, "saves_time": True}

    def scan(self):
        inds = self.load_input("indicators.json")
        if inds is None:
            self.input_dir.mkdir(parents=True, exist_ok=True)
            (self.input_dir / "indicators.json").write_text(
                pi.json.dumps(SAMPLE, indent=2), encoding="utf-8")
            inds = SAMPLE

        opps = []
        favorable = 0
        for ind in inds:
            name = ind.get("name", "")
            weight, why, action = PLAYBOOK.get(name, (10, "macro signal", "Monitor"))
            val, prev = float(ind.get("value", 0)), float(ind.get("prev", 0))
            moved = val - prev
            good_dir = ind.get("direction_good", "up")
            is_good = (moved < 0 and good_dir == "down") or (moved > 0 and good_dir == "up")
            if moved == 0:
                continue
            favorable += 1 if is_good else 0
            magnitude = abs(moved) / (abs(prev) or 1)
            score = min(round(weight + magnitude * 100 * (1 if is_good else 0.3), 1), 100)
            arrow = "↓" if moved < 0 else "↑"
            risk = "LOW" if is_good else "HIGH"
            opps.append(pi.Opportunity(
                title=f"{name} {arrow} {val}{ind.get('unit','')} (was {prev})",
                score=score if is_good else round(score * 0.6, 1),
                action=action if is_good else f"HEADWIND — {why}; hold/defer.",
                signals=[pi.Signal(name, val, weight, why), pi.Signal("change", round(moved, 3), 0)],
                risk=risk, fields={"value": val, "prev": prev, "favorable": is_good, "unit": ind.get("unit", "")},
            ))

        regime = "EXPANSION / GREEN" if favorable >= len(opps) * 0.6 else \
                 "MIXED / YELLOW" if favorable >= len(opps) * 0.3 else "CONTRACTION / RED"
        # prepend a regime summary opportunity
        opps.insert(0, pi.Opportunity(
            title=f"REGIME: {regime}", score=100.0 if "GREEN" in regime else 60.0 if "YELLOW" in regime else 30.0,
            action=f"{favorable}/{len(opps)} indicators favorable. Size positions accordingly.",
            signals=[pi.Signal("favorable_count", favorable, 0)], risk="LOW",
            fields={"regime": regime, "favorable": favorable, "total": len(opps)},
        ))
        return opps


if __name__ == "__main__":
    EconomicChecker().run()
