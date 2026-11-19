#!/usr/bin/env python3
"""
PINEAPPLE OS - top-level runner.
Discovers every IntelModule under the bucket folders, runs them, and aggregates
a single ranked daily brief across all layers.

Usage:
    python pineapple_os.py            # run all modules, print brief, write daily_brief.json
    python pineapple_os.py --quiet    # no per-module output, just the brief
    python pineapple_os.py --list     # list discovered modules and exit
"""
from __future__ import annotations
import argparse
import importlib.util
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "_lib"))
import pineapple_intel as pi  # noqa: E402

BUCKETS = ["02_CASHFLOW", "03_ASSETS", "04_INTELLIGENCE", "05_LIFESTYLE"]


def discover():
    """Find every *.py under bucket dirs that defines an IntelModule subclass."""
    found = []
    for bucket in BUCKETS:
        bdir = ROOT / bucket
        if not bdir.exists():
            continue
        for py in sorted(bdir.rglob("*.py")):
            if py.name.startswith("_") or "output" in py.parts or "input" in py.parts:
                continue
            spec = importlib.util.spec_from_file_location(py.stem, py)
            if not spec or not spec.loader:
                continue
            try:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
            except Exception as e:
                print("  ! skip %s: %s" % (py.name, e))
                continue
            for _, obj in inspect.getmembers(mod, inspect.isclass):
                if issubclass(obj, pi.IntelModule) and obj is not pi.IntelModule \
                        and obj.__module__ == mod.__name__:
                    found.append((bucket, py, obj))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    mods = discover()
    if args.list:
        for bucket, py, cls in mods:
            print("  [%s] %-24s (%s)" % (bucket, cls.module_name, py.relative_to(ROOT)))
        return

    all_opps = []
    summary = []
    for bucket, py, cls in mods:
        inst = cls()
        res = inst.run(publish=True, quiet=args.quiet)
        summary.append({"module": cls.module_name, "layer": bucket, "count": res["count"]})
        for o in res["opportunities"]:
            o["_module"] = cls.module_name
            o["_layer"] = bucket
            all_opps.append(o)

    all_opps.sort(key=lambda o: o["score"], reverse=True)
    brief = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "modules_run": len(mods),
        "total_opportunities": len(all_opps),
        "by_module": summary,
        "top_actions": all_opps[:15],
    }
    (ROOT / "daily_brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")

    bar = "#" * 66
    print("")
    print(bar)
    print("#  PINEAPPLE OS - DAILY BRIEF  -  " + brief["generated"])
    print(bar)
    print("#  %d modules / %d opportunities" % (len(mods), len(all_opps)))
    print("#")
    print("#  TOP ACTIONS ACROSS ALL LAYERS:")
    for i, o in enumerate(all_opps[:12], 1):
        layer = o["_layer"][3:]
        print("#  %2d. [%s] %5.1f %-11s %s" % (i, o["priority"], o["score"], layer, o["title"][:42]))
        print("#         -> " + o["action"][:90])
    print("#")
    print("#  Full brief: " + str(ROOT / "daily_brief.json"))
    print(bar)
    print("")


if __name__ == "__main__":
    main()
