#!/usr/bin/env python3
"""Utility / Water Shutoff + Lien distress signal (RGV).

Sample data, read-only, property-level only. Real sources to wire later:
  - Municipal utility lien filings / public works delinquent-utility liens
  - Vacant-meter / disconnected-service flags from code enforcement
PRIVACY: property-condition signal ONLY. No targeting of vulnerable individuals.
Strongest when cross-referenced with delinquent_tax / code_violations on the same parcel.
"""
from __future__ import annotations
import argparse
import json

PLUGIN = {
    "id": "utility_shutoffs",
    "name": "Utility Distress Radar",
    "category": "RISKS",
    "authority": "OWNER",
    "status": "sample",
    "inputs": ["city"],
    "outputs": ["property distress signals (shutoff/lien/vacancy)"],
    "sources": [
        "https://www.mcallen.net/departments/public-works",
        "https://www.brownsville-pub.com/",
    ],
    "safety": "Property-level public lien/vacancy data only. No individual targeting. Dignity-first.",
}

# address, city, utility, status, amount_owed, vacancy, lat, lon
_RAW = [
    ("1402 Beaumont Ave", "McAllen", "water", "disconnected+lien", 1850, True, 26.2061, -98.2255),
    ("5402 N 2nd St", "McAllen", "electric", "vacant meter", 0, True, 26.2600, -98.2410),
    ("215 W Adams", "Harlingen", "water", "lien", 920, False, 26.1900, -97.6970),
    ("88 Stonewall St", "Harlingen", "water", "disconnected", 640, True, 26.1850, -97.7000),
    ("1190 E 14th St", "Brownsville", "water", "disconnected+lien", 2100, True, 25.9120, -97.4900),
    ("300 W Cano St", "Edinburg", "electric", "vacant meter", 0, True, 26.3030, -98.1670),
    ("77 Mile 3 Rd", "Weslaco", "water", "lien", 1100, False, 26.1600, -97.9850),
    ("210 E Monroe", "Raymondville", "water", "disconnected", 480, True, 26.4800, -97.7840),
    ("1900 S Cage Blvd", "Pharr", "water", "lien", 3400, False, 26.1810, -98.1840),
    ("455 Morrison Rd", "Brownsville", "water", "vacant meter", 0, True, 25.9700, -97.5360),
    ("330 Tyler Ave", "McAllen", "electric", "disconnected", 760, True, 26.2010, -98.2330),
    ("1203 W Nolana", "Pharr", "water", "lien", 540, False, 26.2270, -98.1900),
]


def _score(status, owed, vacancy):
    sc = 20 if "disconnect" in status else (10 if "vacant" in status else 0)
    sc += 14 if "lien" in status else 0
    sc += 18 if vacancy else 0
    sc += min(20, owed / 150)
    return round(min(100, sc), 1)


def items():
    out = []
    for addr, city, util, status, owed, vacancy, lat, lon in _RAW:
        sc = _score(status, owed, vacancy)
        out.append({
            "title": "%s distress - %s, %s (%s)" % (util.title(), addr, city, status),
            "category": "RISKS", "source": "Utility Distress Radar",
            "action": "Cross-ref delinquent_tax + code_violations - likely vacant/motivated" if vacancy
                      else "Monitor - utility lien on record",
            "est_value": owed or None, "risk": "MED",
            "location": "%s, TX" % city, "url": PLUGIN["sources"][0],
            "confidence": 0.55, "lat": lat, "lon": lon,
            "utility": util, "status": status, "vacancy": vacancy, "_score": sc,
        })
    out.sort(key=lambda x: x["_score"], reverse=True)
    return out


def selftest():
    its = items()
    assert its and all("lat" in i for i in its)
    print("%s: %d signals | top: [%s] %s" % (PLUGIN["id"], len(its), its[0]["_score"], its[0]["title"]))
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
