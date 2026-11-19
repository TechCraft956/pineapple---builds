#!/usr/bin/env python3
"""Pre-Foreclosure / Notice-of-Sale radar (RGV) - equity + urgency leads.

Sample data, read-only, public records. Real sources to wire later:
  - County clerk Notice of Substitute Trustee Sale postings (~21 days pre-sale)
  - First-Tuesday courthouse foreclosure auction lists
  - Lis pendens / HOA assessment lien filings
Ethical: homeowner-respectful outreach only. Each item carries lat/lon for the map.
"""
from __future__ import annotations
import argparse
import json

PLUGIN = {
    "id": "preforeclosure",
    "name": "Pre-Foreclosure Radar",
    "category": "OPPORTUNITIES",
    "authority": "OWNER",
    "status": "sample",
    "inputs": ["county", "max_days_to_sale"],
    "outputs": ["ranked pre-foreclosure leads by equity + urgency"],
    "sources": [
        "https://www.hidalgocounty.us/162/County-Clerk",
        "https://www.cameroncountyclerk.com/",
        "https://www.tdhca.texas.gov/",
    ],
    "safety": "Public notice-of-sale records only. Respectful, lawful homeowner outreach. No predatory tactics.",
}

# owner, address, city, trustee, days_to_sale, opening_bid, market_value, stage, lat, lon
_RAW = [
    ("R. & A. Flores", "2210 Wisteria Ave", "McAllen", "Substitute Trustee LLC", 12, 138000, 205000, "NOS posted", 26.2105, -98.2412),
    ("Estate of V. Saenz", "905 N Texas Blvd", "Weslaco", "BDF Law Group", 5, 96000, 168000, "NOS posted", 26.1610, -97.9920),
    ("J. Martinez", "417 Palm Dr", "San Juan", "Mackie Wolf", 21, 110000, 162000, "lis pendens", 26.1895, -98.1556),
    ("Vacant - LLC owned", "6100 N 10th St", "McAllen", "Substitute Trustee LLC", 8, 220000, 380000, "NOS posted", 26.2680, -98.2280),
    ("D. Cavazos", "1320 E Harrison Ave", "Harlingen", "BDF Law Group", 18, 84000, 139000, "lis pendens", 26.1905, -97.6850),
    ("M. Ozuna", "33 Stonegate Dr", "Brownsville", "Mackie Wolf", 3, 152000, 224000, "auction this wk", 25.9430, -97.4890),
    ("Estate of L. Peña", "788 W Expressway 83", "Pharr", "BDF Law Group", 14, 118000, 178000, "NOS posted", 26.1790, -98.1900),
    ("G. Rangel", "210 W Yuma Ave", "McAllen", "Substitute Trustee LLC", 9, 99000, 156000, "NOS posted", 26.1980, -98.2360),
    ("HOA lien - absentee", "455 Sunflower St", "Mission", "HOA counsel", 25, 18000, 148000, "HOA lien", 26.2160, -98.3250),
    ("T. Villarreal", "1900 Morgan Blvd", "Harlingen", "Mackie Wolf", 6, 91000, 147000, "auction soon", 26.1820, -97.7010),
    ("Estate of F. Guzman", "120 E Monroe", "Raymondville", "BDF Law Group", 16, 62000, 105000, "NOS posted", 26.4790, -97.7830),
    ("R. Solis", "5402 Hibiscus Ave", "McAllen", "Substitute Trustee LLC", 11, 165000, 248000, "NOS posted", 26.2590, -98.2150),
]


def _score(days, bid, mv):
    equity = max(0, mv - bid)
    urgency = max(0, 25 - days)  # closer sale = more urgent
    return round(min(100, equity / 4000 + urgency * 2.2), 1)


def items():
    out = []
    for owner, addr, city, trustee, days, bid, mv, stage, lat, lon in _RAW:
        equity = max(0, mv - bid)
        sc = _score(days, bid, mv)
        risk = "HIGH" if days <= 7 else ("MED" if days <= 18 else "LOW")
        action = "URGENT %dd to sale - verify title, prep funds/outreach" % days if days <= 10 \
            else "Monitor (%dd) - title check, contact owner re: pre-sale options" % days
        out.append({
            "title": "%s - %s, %s [%s]" % (owner, addr, city, stage),
            "category": "OPPORTUNITIES", "source": "Pre-Foreclosure Radar",
            "action": action, "est_value": equity, "risk": risk,
            "location": "%s, TX" % city, "url": PLUGIN["sources"][0],
            "confidence": 0.66, "lat": lat, "lon": lon,
            "opening_bid": bid, "market_value": mv, "days_to_sale": days, "stage": stage, "_score": sc,
        })
    out.sort(key=lambda x: x["_score"], reverse=True)
    return out


def selftest():
    its = items()
    assert its and all("lat" in i for i in its)
    print("%s: %d leads | top: [%s] %s" % (PLUGIN["id"], len(its), its[0]["_score"], its[0]["title"]))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.json:
        print(json.dumps(items(), indent=2))
    else:
        selftest()
