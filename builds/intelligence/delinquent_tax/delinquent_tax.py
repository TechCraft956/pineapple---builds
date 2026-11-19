#!/usr/bin/env python3
"""Delinquent Property Tax radar - motivated-seller / acquisition leads (RGV).

Sample data, read-only, public sources. Real sources to wire later:
  - County tax assessor-collector delinquent rolls (Hidalgo, Cameron, Starr, Willacy)
  - Struck-off / resale property lists
  - Delinquent tax law firms (LGBS linebarger.com, Perdue Brandon pbfcm.com) sale listings
Feeds the decision brief and the Real Estate Radar (each item carries lat/lon).
"""
from __future__ import annotations
import argparse
import json

PLUGIN = {
    "id": "delinquent_tax",
    "name": "Delinquent Tax Radar",
    "category": "ASSETS",
    "authority": "OWNER",
    "status": "sample",
    "inputs": ["county", "min_equity"],
    "outputs": ["ranked delinquent parcels with equity + approach"],
    "sources": [
        "https://www.hidalgocountytax.org/",
        "https://www.cameroncountytax.com/",
        "https://www.pbfcm.com/",
        "https://www.lgbs.com/",
    ],
    "safety": "Public delinquent-tax records only. Read-only. Respectful, compliant outreach.",
}

# account, owner, situs, city, years, owed, assessed, lat, lon
_RAW = [
    ("H-2019-44021", "Estate of R. Salinas", "1421 Cypress Ave", "McAllen", 5, 14200, 168000, 26.2034, -98.2300),
    ("H-2021-11883", "M. & G. Tovar", "908 W Hackberry", "Edinburg", 3, 8800, 132000, 26.3015, -98.1631),
    ("C-2018-77410", "Vacant - absentee", "215 Palm Blvd", "Brownsville", 6, 21900, 142000, 25.9012, -97.4975),
    ("H-2020-30192", "J. Trevino", "3402 Date Palm Dr", "Pharr", 4, 11750, 119000, 26.1948, -98.1836),
    ("H-2022-65120", "Cantu Family Trust", "77 Mile 5 N", "Weslaco", 2, 6400, 98000, 26.1730, -97.9905),
    ("C-2019-50233", "Estate of D. Lopez", "1190 Iowa Ave", "San Benito", 5, 17600, 156000, 26.1326, -97.6311),
    ("H-2017-09844", "ABC Holdings LLC", "5500 N 23rd St", "McAllen", 7, 34800, 410000, 26.2620, -98.2390),
    ("S-2020-12007", "R. Garza", "402 E 1st St", "Rio Grande City", 4, 9200, 84000, 26.3795, -98.8205),
    ("H-2021-88431", "Vacant lot - absentee", "Mile 7 & FM 1925", "Edinburg", 3, 5100, 72000, 26.3550, -98.1300),
    ("C-2018-33019", "Estate of P. Ramirez", "88 Boca Chica Blvd", "Brownsville", 6, 26300, 198000, 25.9085, -97.4640),
    ("H-2022-44190", "L. Hinojosa", "1203 Nolana Loop", "Pharr", 2, 7300, 121000, 26.2280, -98.1850),
    ("W-2019-20155", "Estate of A. Cano", "300 W Main", "Raymondville", 5, 10400, 91000, 26.4801, -97.7836),
    ("H-2016-77002", "Sunbelt Investments", "1900 S Cage Blvd", "Pharr", 8, 41200, 365000, 26.1810, -98.1840),
    ("C-2021-61288", "M. Reyna", "455 Morrison Rd", "Brownsville", 3, 9900, 110000, 25.9700, -97.5360),
]


def _score(years, owed, equity):
    # higher equity + more years delinquent + manageable owed = stronger lead
    return round(min(100, equity / 5000 + years * 6 + (15 if owed < 15000 else 0)), 1)


def items():
    out = []
    for acct, owner, situs, city, years, owed, assessed, lat, lon in _RAW:
        equity = max(0, assessed - owed)
        sc = _score(years, owed, equity)
        absentee = "absentee" in owner.lower() or "estate" in owner.lower() or "llc" in owner.lower()
        action = ("PRIORITY: absentee/estate owner, %dyr delinquent - skip-trace + offer"
                  % years) if absentee else ("Contact owner - %dyr behind, structure payoff+buy" % years)
        out.append({
            "title": "%s - %s, %s" % (owner, situs, city),
            "category": "ASSETS", "source": "Delinquent Tax Radar",
            "action": action, "est_value": equity, "risk": "LOW" if equity > 60000 else "MED",
            "location": "%s, TX" % city, "url": PLUGIN["sources"][0],
            "confidence": 0.7, "lat": lat, "lon": lon,
            "owed": owed, "assessed": assessed, "years_delinquent": years, "_score": sc,
        })
    out.sort(key=lambda x: x["_score"], reverse=True)
    return out


def selftest():
    its = items()
    assert its and all("lat" in i and i["est_value"] is not None for i in its)
    print("%s: %d parcels | top: [%s] %s" % (PLUGIN["id"], len(its), its[0]["_score"], its[0]["title"]))
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
