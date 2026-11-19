#!/usr/bin/env python
"""CLI: build the pre-market brief for a given trading day.

    .venv/bin/python scripts/report_premarket.py 2026-08-05 \\
        --bars ES=data/cleaned/ES_1m.parquet --calendar data/calendar.json --html

Bar frames are read directly as parquet (lab.core.frames-shaped: UTC
DatetimeIndex named ``ts``, columns open/high/low/close/volume) so this
script has no hard dependency on lab.data's loader, which may not be
importable yet -- see the ground rules in the module docstrings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.core.config import load_config
from lab.core.frames import validate_bars


def _load_bars(spec: str) -> tuple[str, "object"]:
    import pandas as pd

    if "=" not in spec:
        raise SystemExit(f"--bars entries must be SYMBOL=path.parquet, got {spec!r}")
    symbol, path = spec.split("=", 1)
    df = pd.read_parquet(path)
    if df.index.name != "ts" or not hasattr(df.index, "tz"):
        # tolerate a plain timestamp column, mirroring lab.core.frames.normalise_bars
        from lab.core.frames import normalise_bars
        df = normalise_bars(df)
    validate_bars(df, name=symbol, strict=False)
    return symbol.strip().upper(), df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("day", help="trading day, e.g. 2026-08-05")
    parser.add_argument("--bars", action="append", default=[], metavar="SYMBOL=PATH",
                         help="bar parquet for a symbol; may be repeated, first one is primary")
    parser.add_argument("--calendar", default=None, help="JSON file: list of {time, name, impact}")
    parser.add_argument("--prior-results", default=None, help="JSON file of lab.risk output, if available")
    parser.add_argument("--html", action="store_true", help="also write an HTML copy")
    args = parser.parse_args()

    if not args.bars:
        raise SystemExit("at least one --bars SYMBOL=PATH is required")

    try:
        from lab.reports.premarket import build_premarket_report
        from lab.reports.render import to_html
    except ImportError as exc:
        raise SystemExit(f"lab.reports is not importable yet ({exc})") from exc

    bars_by_symbol = dict(_load_bars(spec) for spec in args.bars)
    calendar_events = json.loads(Path(args.calendar).read_text()) if args.calendar else []
    prior_results = json.loads(Path(args.prior_results).read_text()) if args.prior_results else None

    cfg = load_config()
    markdown = build_premarket_report(
        day=args.day, bars_by_symbol=bars_by_symbol, calendar_events=calendar_events,
        prior_results=prior_results, cfg=cfg,
    )

    cfg.ensure_dirs()
    out_md = cfg.results_dir / f"premarket_{args.day}.md"
    out_md.write_text(markdown)
    print(f"wrote {out_md}")
    if args.html:
        out_html = out_md.with_suffix(".html")
        out_html.write_text(to_html(markdown, title=out_md.stem))
        print(f"wrote {out_html}")


if __name__ == "__main__":
    main()
