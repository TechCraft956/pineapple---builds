#!/usr/bin/env python
"""CLI: import a platform execution export into the journal.

    .venv/bin/python scripts/journal_import.py path/to/export.csv \\
        --strategy asia_sweep --version v3 --symbol-map ES=MyRoot

Writes an import summary to results/, and appends the imported trades to
journal/ as executed rows (unless --dry-run is given).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.core.config import load_config


def _parse_symbol_map(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"--symbol-map entries must be RAW=CANONICAL, got {p!r}")
        raw, canonical = p.split("=", 1)
        out[raw.strip()] = canonical.strip()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", help="path to the platform export (CSV/Excel/Parquet/JSON)")
    parser.add_argument("--strategy", default="", help="strategy name to attach to imported trades")
    parser.add_argument("--version", default="unversioned", help="strategy version string")
    parser.add_argument("--tag", default="", help="setup tag to attach to imported trades")
    parser.add_argument("--symbol-map", action="append", default=[], metavar="RAW=CANONICAL",
                         help="override symbol normalisation; may be repeated")
    parser.add_argument("--dry-run", action="store_true", help="print the summary but do not write to the journal")
    parser.add_argument("--html", action="store_true", help="also write an HTML copy of the summary")
    args = parser.parse_args()

    try:
        from lab.journal.importer import import_executions
        from lab.journal.journal import Journal
        from lab.reports.render import markdown_table, section, to_html
    except ImportError as exc:
        raise SystemExit(
            f"a required lab module is not importable yet ({exc}); "
            "this script needs lab.journal and lab.reports to be complete."
        ) from exc

    cfg = load_config()
    symbol_map = _parse_symbol_map(args.symbol_map)
    result = import_executions(args.export, symbol_map=symbol_map or None, default_strategy=args.strategy)

    lines = [f"# Journal import -- {Path(args.export).name}\n"]
    lines.append(section("Summary", "\n".join([
        f"- source rows: {result.n_source_rows}",
        f"- rows skipped (unparseable): {result.n_rows_skipped}",
        f"- layout detected: `{result.layout}`",
        f"- trades produced: {len(result.trades)}",
    ])))
    lines.append(section("Inferred column mapping", "\n".join(
        f"- `{field}` <- `{col}`" for field, col in sorted(result.column_mapping.items())
    ) or "_none_"))
    if result.warnings:
        lines.append(section("Warnings", "\n".join(f"- {w}" for w in result.warnings)))

    if result.trades:
        import pandas as pd
        preview = pd.DataFrame([t.to_dict() for t in result.trades[:20]])
        lines.append(section(f"Trade preview (first {min(20, len(result.trades))} of {len(result.trades)})",
                              markdown_table(preview, formats={"pnl": ",.2f"})))

    markdown = "\n".join(lines)
    cfg.ensure_dirs()
    out_md = cfg.results_dir / f"journal_import_{Path(args.export).stem}.md"
    out_md.write_text(markdown)
    print(f"wrote {out_md}")
    if args.html:
        out_html = out_md.with_suffix(".html")
        out_html.write_text(to_html(markdown, title=out_md.stem))
        print(f"wrote {out_html}")

    if args.dry_run:
        print("--dry-run: not writing to the journal")
        return

    journal = Journal(cfg.journal_dir)
    for trade in result.trades:
        journal.log_trade(trade, version=args.version, tag=args.tag)
    print(f"logged {len(result.trades)} trades to {journal.parquet_path}")


if __name__ == "__main__":
    main()
