#!/usr/bin/env python3
"""Municipal Code Violation radar (RGV) - distressed-property + contractor-lead signal.

Sample data, read-only, public records. Real sources to wire later:
  - City code-enforcement portals (McAllen, Edinburg, Brownsville, Harlingen)
  - Municipal lien records / nuisance abatement lists
Open violation + high lien + absentee owner = acquisition lead; any open case = cleanup bid.
Each item carries lat/lon for the Real Estate Radar map.
"""
from __future__ import annotations
import argparse
import json

PLUGIN = {
    "id": "code_violations",
    "name": "Code Violation Radar",
    "category": "OPPORTUNITIES",
    "authority": "OWNER",
    "status": "sample",
    "inputs": ["city", "status"],
    "outputs": ["scored code cases - acquisition + contractor leads"],
    "sources": [
        "https://www.mcallen.net/departments/code-enforcement",
        "https://www.cityofedinburg.com/",
        "https://www.cob.us/",
    ],
    "safety": "Public code-enforcement records only. Read-only.",
}

# address, city, vtype, status, fine_or_lien, owner_type, lat, lon
_RAW = [
    ("1402 Beaumont Ave", "McAllen", "Dilapidated structure", "open+lien", 4200, "absentee", 26.2061, -98.2255),
    ("908 S 17th St", "Edinburg", "Overgrown/junk", "open", 650, "absentee", 26.2980, -98.1650),
    ("215 W Adams", "Harlingen", "Substandard building", "lien", 7800, "estate", 26.1900, -97.6970),
    ("330 Tyler Ave", "McAllen", "Illegal dumping", "open", 1200, "owner-occ", 26.2010, -98.2330),
    ("77 Mile 3 Rd", "Weslaco", "Junk vehicles/debris", "open+lien", 3100, "absentee", 26.1600, -97.9850),
    ("1190 E 14th St", "Brownsville", "Dilapidated structure", "open", 2500, "absentee", 25.9120, -97.4900),
    ("5402 N 2nd St", "McAllen", "Vacant/unsecured", "open+lien", 5600, "LLC", 26.2600, -98.2410),
    ("402 Palm Blvd", "Brownsville", "Overgrown lot", "abated", 400, "owner-occ", 25.9050, -97.4980),
    ("88 Stonewall St", "Harlingen", "Substandard/unsafe", "open+lien", 9200, "estate", 26.1850, -97.7000),
    ("1203 W Nolana", "Pharr", "Junk/debris", "open", 800, "absentee", 26.2270, -98.1900),
    ("300 W Cano St", "Edinburg", "Dilapidated structure", "lien", 6400, "absentee", 26.3030, -98.1670),
    ("455 Morrison Rd", "Brownsville", "Vacant/unsecured", "open", 1500, "absentee", 25.9700, -97.5360),
    ("210 E Monroe", "Raymondville", "Substandard building", "open+lien", 3800, "estate", 26.4800, -97.7840),
    ("1900 S Cage Blvd", "Pharr", "Commercial blight", "open+lien", 12500, "LLC", 26.1810, -98.1840),
    ("33 Boca Chica Blvd", "Brownsville", "Dilapidated structure", "open", 2200, "absentee", 25.9085, -97.4640),
]


def _score(status, fine, owner_type):
    sc = fine / 250
    if "open" in status:
        sc += 15
    if "lien" in status:
        sc += 12
    if owner_type in ("absentee", "estate", "LLC"):
        sc += 18
    return round(min(100, sc), 1)


def items():
    out = []
    for addr, city, vtype, status, fine, owner_type, lat, lon in _RAW:
        sc = _score(status, fine, owner_type)
        if owner_type in ("absentee", "estate", "LLC") and "open" in status:
            action = "Acquisition lead: %s owner, open case - skip-trace + offer" % owner_type
            cat = "OPPORTUNITIES"
        else:
            action = "Contractor lead: bid cleanup/repair (%s)" % vtype.lower()
            cat = "MONEY"
        out.append({
            "title": "%s - %s, %s" % (vtype, addr, city),
            "category": cat, "source": "Code Violation Radar",
            "action": action, "est_value": fine, "risk": "MED",
            "location": "%s, TX" % city, "url": PLUGIN["sources"][0],
            "confidence": 0.62, "lat": lat, "lon": lon,
            "violation": vtype, "status": status, "owner_type": owner_type, "_score": sc,
        })
    out.sort(key=lambda x: x["_score"], reverse=True)
    return out


def selftest():
    its = items()
    assert its and all("lat" in i for i in its)
    print("%s: %d cases | top: [%s] %s" % (PLUGIN["id"], len(its), its[0]["_score"], its[0]["title"]))
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
