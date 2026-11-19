#!/usr/bin/env python3
"""Build records for every registered lake and render the Markdown brief.

Usage:
  python3 scripts/build_brief.py           # live pull, cache, render
  python3 scripts/build_brief.py --offline # render from cache only
Writes output/records.json and output/LAKE_BRIEF.md.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))
from common import utc_now_iso  # noqa: E402
from pipeline import collect, load_registry  # noqa: E402
from render import render_brief  # noqa: E402


def main():
    offline = "--offline" in sys.argv
    records = collect(load_registry(), offline=offline)
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "output")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "records.json"), "w",
              encoding="utf-8") as fh:
        json.dump(records, fh, indent=1)
    brief = render_brief(records, generated_at_utc=utc_now_iso())
    with open(os.path.join(outdir, "LAKE_BRIEF.md"), "w",
              encoding="utf-8") as fh:
        fh.write(brief)
    print(brief)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
