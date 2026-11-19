#!/usr/bin/env python
"""CLI: audit the London Strategic Edge catalog before building anything on it.

    .venv/bin/python scripts/audit_catalog.py --categories futures,bonds,volatility

Writes ``results/catalog_audit_<timestamp>.csv`` and the matching markdown
report, and prints a summary to stdout. Requires ``lse-data`` and
``LSE_API_KEY`` -- if either is missing, this fails with an actionable
message rather than a traceback.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from anywhere

from lab.core.config import load_config  # noqa: E402
from lab.data.catalog import audit_catalog, render_markdown  # noqa: E402
from lab.data.client import LSEUnavailable  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--categories", default="futures,bonds,volatility",
        help="comma-separated vendor catalog categories to audit (default: %(default)s)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    cfg = load_config().ensure_dirs()
    try:
        from lab.data.client import LSEClient

        client = LSEClient.from_config(cfg)
    except (LSEUnavailable, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Auditing categories: {', '.join(categories)}")
    df = audit_catalog(client, categories)
    if len(df) == 0:
        print("No catalog entries found -- check LSE_API_KEY and the category names.")
        return 1

    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")
    csv_path = cfg.results_dir / f"catalog_audit_{stamp}.csv"
    md_path = cfg.results_dir / f"catalog_audit_{stamp}.md"
    df.to_csv(csv_path, index=False)
    md_path.write_text(render_markdown(df))

    print(f"\n{len(df)} datasets across {df['category'].nunique()} categories.")
    print(df.groupby(["category", "contract_type_guess"]).size().to_string())
    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
