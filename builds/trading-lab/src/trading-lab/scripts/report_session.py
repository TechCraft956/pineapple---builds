#!/usr/bin/env python
"""CLI: build the post-session review for a given trading day.

    .venv/bin/python scripts/report_session.py 2026-08-05 --signals data/signals_2026-08-05.json --html

Executed trades are reconstructed from the journal's own rows for the day
(status == "executed"), so this needs no other module to be importable.
Expected signals -- what the strategy actually said to do before any fill was
known -- are optional; without them the review still shows every trade and
every logged skip, just without a reconcile verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab.core.config import load_config


def _trade_from_journal_row(row) -> "object":
    from lab.core.types import ExitReason, Trade

    import pandas as pd

    return Trade(
        symbol=row["symbol"], strategy=row["strategy"], direction=int(row["direction"]),
        entry_ts=pd.Timestamp(row["entry_ts"]), entry_price=float(row["entry_price"]),
        exit_ts=pd.Timestamp(row["exit_ts"]), exit_price=float(row["exit_price"]),
        qty=float(row["qty"]), pnl=float(row["pnl"]), commission=float(row.get("commission") or 0.0),
        slippage_cost=float(row.get("slippage_dollars") or 0.0), risk_dollars=0.0,
        exit_reason=ExitReason.MANUAL, mfe=float(row.get("mfe") or 0.0), mae=float(row.get("mae") or 0.0),
        tag=row.get("tag") or "",
    )


def _signal_from_dict(d: dict) -> "object":
    from lab.core.types import Signal
    import pandas as pd

    d = dict(d)
    d["ts"] = pd.Timestamp(d["ts"])
    if d.get("valid_until"):
        d["valid_until"] = pd.Timestamp(d["valid_until"])
    if "targets" in d:
        d["targets"] = tuple(d["targets"])
    return Signal(**d)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("day", help="trading day, e.g. 2026-08-05")
    parser.add_argument("--signals", default=None, help="JSON file: list of Signal-shaped dicts")
    parser.add_argument("--account-state", default=None, help="JSON file: {equity, drawdown_headroom, ...}")
    parser.add_argument("--html", action="store_true", help="also write an HTML copy")
    args = parser.parse_args()

    try:
        from lab.journal.journal import Journal
        from lab.reports.render import to_html
        from lab.reports.session_review import build_session_review
    except ImportError as exc:
        raise SystemExit(f"lab.journal / lab.reports is not importable yet ({exc})") from exc

    cfg = load_config()
    journal = Journal(cfg.journal_dir)
    journal_rows = journal.query(start=args.day, end=args.day)
    executed_trades = [
        _trade_from_journal_row(row) for _, row in journal_rows[journal_rows["status"] == "executed"].iterrows()
    ]
    expected_signals = (
        [_signal_from_dict(d) for d in json.loads(Path(args.signals).read_text())] if args.signals else []
    )
    account_state = json.loads(Path(args.account_state).read_text()) if args.account_state else None

    markdown = build_session_review(
        day=args.day, journal_rows=journal_rows, executed_trades=executed_trades,
        expected_signals=expected_signals, account_state=account_state,
    )

    cfg.ensure_dirs()
    out_md = cfg.results_dir / f"session_review_{args.day}.md"
    out_md.write_text(markdown)
    print(f"wrote {out_md}")
    if args.html:
        out_html = out_md.with_suffix(".html")
        out_html.write_text(to_html(markdown, title=out_md.stem))
        print(f"wrote {out_html}")


if __name__ == "__main__":
    main()
