#!/usr/bin/env python
"""CLI: cache-first fetch of bar data for one or more symbols.

    .venv/bin/python scripts/fetch_data.py --symbols ES,CL --timeframe 1h \\
        --start 2024-01-01 --end 2024-06-01

Thin wrapper around :func:`lab.data.loaders.load_bars` -- every gap it fills
is exactly what :meth:`lab.data.cache.BarCache.missing_ranges` says is
missing, so re-running this command is always cheap. ``--force`` clears the
cache for the requested symbols first. Writes a per-symbol quality summary
into ``results/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from anywhere

from lab.core.config import load_config  # noqa: E402
from lab.data.cache import BarCache  # noqa: E402
from lab.data.loaders import DataQualityError, load_bars  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", required=True, help="comma-separated lab symbols, e.g. ES,MES,CL")
    p.add_argument("--timeframe", default="1m", help="bar timeframe (default: %(default)s)")
    p.add_argument("--start", required=True, help="ISO date/timestamp, inclusive")
    p.add_argument("--end", default=None, help="ISO date/timestamp, inclusive (default: now)")
    p.add_argument("--force", action="store_true", help="clear the cache for these symbols before fetching")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    end = args.end or pd.Timestamp.now(tz="UTC").isoformat()

    cfg = load_config().ensure_dirs()
    cache = BarCache(cfg=cfg)
    if args.force:
        for s in symbols:
            print(f"--force: clearing cache for {s} {args.timeframe}")
            cache.clear(s, args.timeframe)

    rows = []
    exit_code = 0
    for symbol in symbols:
        print(f"\n{symbol} {args.timeframe}: {args.start} -> {end}")
        try:
            df = load_bars(symbol, args.timeframe, start=args.start, end=end, cfg=cfg)
        except DataQualityError as exc:
            print(f"  QUALITY GATE FAILED: {exc}")
            exit_code = 1
            continue
        except Exception as exc:
            print(f"  ERROR: {exc}")
            exit_code = 1
            continue

        quality = df.attrs.get("quality")
        if quality is not None:
            print(f"  {quality.summary()}")
            rows.append({"symbol": symbol, "timeframe": args.timeframe, **{
                "n_bars": quality.n_bars, "start": quality.start, "end": quality.end,
                "n_gaps": quality.n_gaps, "n_zero_volume": quality.n_zero_volume,
                "suspicious_jumps": quality.suspicious_jumps,
            }})
        else:
            print(f"  {len(df)} bars ({df.index[0] if len(df) else '-'} -> {df.index[-1] if len(df) else '-'})")

    if rows:
        stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
        out_path = cfg.results_dir / f"fetch_summary_{stamp}.csv"
        pd.DataFrame(rows).to_csv(out_path, index=False)
        print(f"\nWrote {out_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
