#!/usr/bin/env python3
"""Live smoke: pull Falcon + Amistad for real and print their records.

Separate from the offline test suite. Caches every raw response under
../cache/ with retrieved_at_utc + URL sidecars.
Usage: python3 scripts/live_smoke.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
from pipeline import collect, load_registry  # noqa: E402
from render import brief_line  # noqa: E402

PRIORITY = ("Falcon International Reservoir",
            "Amistad International Reservoir")


def main():
    entries = [e for e in load_registry() if e["name"] in PRIORITY]
    records = collect(entries)
    for r in records:
        print(brief_line(r))
        print(f"  pct_conservation={r['pct_conservation']} "
              f"(storage {r['current']['storage_acre_ft']} / capacity "
              f"{r['conservation']['capacity_acre_ft']}, observed "
              f"{r['current']['observed_at_utc']}, TWDB published % "
              f"{r['pct_published_twdb']})")
        print(f"  trend={r['trend']} confidence={r['confidence']} "
              f"cross_source={r['cross_source']['status']}")
        print(f"  provenance={json.dumps(r['provenance'])}")
        print(f"  item={json.dumps(r['item'])}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "output", "live_smoke_records.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=1)
    print(f"records written to {out}")
    ok = all(r["pct_conservation"] is not None for r in records)
    print("SMOKE", "PASS" if ok else "PARTIAL",
          "- both priority lakes have a computed % of conservation capacity"
          if ok else "- a priority lake is missing a computed %")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
