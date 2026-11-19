#!/usr/bin/env python3
"""
Recon Engine  —  04_INTELLIGENCE
Aggregate raw local-opportunity leads from many sources (auctions, estate/moving
sales, public records, county filings, surplus) into one ranked queue. This is the
catch-all intake that feeds the specialized radars.

Run:  python recon_engine.py
Input: input/leads.json (sample created on first run)
       Each lead: {source, title, category, price, est_value, posted_days_ago, location, url}
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


SOURCE_WEIGHT = {
    "county_auction": 28, "estate_sale": 24, "moving_sale": 20, "tax_sale": 30,
    "surplus": 22, "probate_filing": 26, "public_record": 14, "classifieds": 12,
}
CATEGORY_ROUTE = {
    "real_estate": "→ feed Real Estate Radar",
    "vehicle": "→ candidate flip (moto/car/equipment)",
    "equipment": "→ candidate flip (equipment)",
    "misc": "→ manual review",
}

SAMPLE = [
    {"source": "tax_sale", "title": "Tax sale: 3BR ranch, 1.2ac", "category": "real_estate",
     "price": 18000, "est_value": 145000, "posted_days_ago": 1, "location": "County", "url": ""},
    {"source": "county_auction", "title": "2014 Ford F-250 utility", "category": "vehicle",
     "price": 6500, "est_value": 14000, "posted_days_ago": 3, "location": "County yard", "url": ""},
    {"source": "estate_sale", "title": "Estate: tools, mower, trailer", "category": "equipment",
     "price": 900, "est_value": 2600, "posted_days_ago": 0, "location": "Townline Rd", "url": ""},
    {"source": "surplus", "title": "Surplus office furniture lot", "category": "misc",
     "price": 200, "est_value": 350, "posted_days_ago": 10, "location": "City", "url": ""},
    {"source": "moving_sale", "title": "Moving: TW200 motorcycle", "category": "vehicle",
     "price": 1800, "est_value": 3200, "posted_days_ago": 2, "location": "Maple Dr", "url": ""},
]


class ReconEngine(pi.IntelModule):
    module_id = "recon_engine"
    module_name = "Recon Engine"
    layer = "04_INTELLIGENCE"
    one_rule = {"makes_money": True, "saves_time": True}

    def scan(self):
        leads = self.load_input("leads.json")
        if leads is None:
            self.input_dir.mkdir(parents=True, exist_ok=True)
            (self.input_dir / "leads.json").write_text(
                pi.json.dumps(SAMPLE, indent=2), encoding="utf-8")
            leads = SAMPLE

        opps = []
        for ld in leads:
            src = ld.get("source", "classifieds")
            score = float(SOURCE_WEIGHT.get(src, 10))
            price = float(ld.get("price") or 0)
            est = float(ld.get("est_value") or 0)
            margin = (est - price)
            margin_ratio = (margin / price) if price else 0
            score += min(margin_ratio * 25, 40)            # upside
            age = float(ld.get("posted_days_ago") or 0)
            score += max(0, 12 - age * 2)                  # freshness (act fast)
            score = min(round(score, 1), 100)

            cat = ld.get("category", "misc")
            route = CATEGORY_ROUTE.get(cat, "→ manual review")
            roi = f"{margin_ratio:.0%}" if price else "n/a"
            action = f"{route} · buy ${price:,.0f} / est ${est:,.0f} ({roi} upside)"
            risk = "LOW" if margin_ratio > 1 else "MEDIUM" if margin_ratio > 0.3 else "HIGH"
            opps.append(pi.Opportunity(
                title=ld.get("title", "lead"), score=score, action=action,
                signals=[pi.Signal("source", src, SOURCE_WEIGHT.get(src, 10)),
                         pi.Signal("margin_ratio", round(margin_ratio, 2), 0),
                         pi.Signal("posted_days_ago", age, 0)],
                roi_estimate=round(margin, 0), risk=risk,
                fields={"category": cat, "price": price, "est_value": est, "route": route,
                        "location": ld.get("location", ""), "url": ld.get("url", "")},
            ))
        return opps


if __name__ == "__main__":
    ReconEngine().run()
