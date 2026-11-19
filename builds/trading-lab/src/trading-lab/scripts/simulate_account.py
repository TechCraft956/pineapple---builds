#!/usr/bin/env python
"""CLI: would this strategy have survived the account rules, and when would it pay out?

    .venv/bin/python scripts/simulate_account.py --trades results/es_ls_v1.parquet \\
        --account 150k --type funded --daily-stop 300 --paths 2000

Takes a trades file with the columns produced by ``lab.core.types.Trade.to_dict()``
(CSV or Parquet) and replays it through one :class:`lab.risk.rules.AccountRules`
preset. The report leads with the breach probability and the survival curve, not
with the return -- a strategy that makes money and breaches the drawdown limit
has not made money.

**The rule figures are only as current as the rulebook they came from.** Read the
``Rules provenance`` section the report prints and diff it against the firm's
current terms before acting on anything here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from anywhere

from lab.core.config import load_config  # noqa: E402
from lab.core.types import ExitReason, Trade  # noqa: E402
from lab.reports.render import markdown_table, section, verdict_box  # noqa: E402
from lab.risk.account import AccountSimulator  # noqa: E402
from lab.risk.montecarlo import simulate_paths  # noqa: E402
from lab.risk.rules import PRESETS, RULES_AS_OF, AccountRules, get_preset  # noqa: E402
from lab.risk.survival import (  # noqa: E402
    account_size_comparison,
    consecutive_loss_analysis,
    consistency_analysis,
    daily_stop_sweep,
    frequency_analysis,
)

_REQUIRED = ("exit_ts", "pnl")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--trades", required=True, help="CSV or Parquet of Trade rows")
    p.add_argument("--account", default="150k", help="50k | 100k | 150k (default: %(default)s)")
    p.add_argument(
        "--type", dest="account_type", default="funded",
        choices=("combine", "funded", "express_funded"),
        help="account variant (default: %(default)s)",
    )
    p.add_argument("--daily-stop", type=float, default=None, help="personal daily loss lock, in dollars")
    p.add_argument("--paths", type=int, default=1000, help="Monte Carlo paths (default: %(default)s)")
    p.add_argument(
        "--method", default="block", choices=("iid", "block", "stationary"),
        help="bootstrap method; block/stationary preserve losing streaks (default: %(default)s)",
    )
    p.add_argument("--horizons", default="20,40,60", help="survival horizons in sessions")
    p.add_argument("--out", default=None, help="output markdown path (default: results/<name>.md)")
    return p.parse_args(argv)


def load_trades(path: Path) -> list[Trade]:
    """Read a trades file into :class:`Trade` objects, or say precisely why not."""
    if not path.exists():
        raise SystemExit(f"no such trades file: {path}")
    if path.suffix.lower() in (".parquet", ".pq"):
        df = pd.read_parquet(path)
    elif path.suffix.lower() in (".csv", ".txt"):
        df = pd.read_csv(path)
    else:
        raise SystemExit(f"unsupported trades format {path.suffix!r}; use .csv or .parquet")

    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise SystemExit(
            f"{path}: missing required column(s) {missing}. Expected the columns "
            f"written by Trade.to_dict(); saw {list(df.columns)}"
        )

    def ts(col: str, row, default=None):
        v = row.get(col, default)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        t = pd.Timestamp(v)
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")

    trades: list[Trade] = []
    for _, row in df.iterrows():
        exit_ts = ts("exit_ts", row)
        entry_ts = ts("entry_ts", row, exit_ts)
        try:
            reason = ExitReason(str(row.get("exit_reason", "manual")))
        except ValueError:
            reason = ExitReason.MANUAL
        trades.append(
            Trade(
                symbol=str(row.get("symbol", "")),
                strategy=str(row.get("strategy", "")),
                direction=int(row.get("direction", 1) or 1),
                entry_ts=entry_ts,
                entry_price=float(row.get("entry_price", 0.0) or 0.0),
                exit_ts=exit_ts,
                exit_price=float(row.get("exit_price", 0.0) or 0.0),
                qty=float(row.get("qty", 1.0) or 1.0),
                pnl=float(row["pnl"]),
                commission=float(row.get("commission", 0.0) or 0.0),
                slippage_cost=float(row.get("slippage_cost", 0.0) or 0.0),
                risk_dollars=float(row.get("risk_dollars", 0.0) or 0.0),
                exit_reason=reason,
                # A missing MAE is the difference between "survived" and
                # "breached on open drawdown", so say so rather than defaulting
                # it to zero silently -- see the warning emitted in main().
                mfe=float(row.get("mfe", 0.0) or 0.0),
                mae=float(row.get("mae", 0.0) or 0.0),
                bars_held=int(row.get("bars_held", 0) or 0),
                tag=str(row.get("tag", "") or ""),
            )
        )
    return trades


def resolve_rules(account: str, account_type: str, daily_stop: float | None) -> AccountRules:
    key = f"topstep_{account_type}_{account.lower()}"
    try:
        rules = get_preset(key)
    except KeyError:
        raise SystemExit(
            f"no preset named {key!r}. Available: {', '.join(sorted(PRESETS))}"
        ) from None
    return rules.with_(personal_daily_stop=daily_stop) if daily_stop else rules


def build_report(trades: list[Trade], rules: AccountRules, args) -> str:
    horizons = tuple(int(h) for h in str(args.horizons).split(",") if h.strip())
    run = AccountSimulator(rules).run(trades)
    mc = simulate_paths(
        trades, rules, args.paths, method=args.method, seed=20260805, horizons=horizons
    )

    parts: list[str] = [f"# Account simulation — {rules.name}\n"]

    # Lead with survival. The return is the second question, always.
    parts.append(
        verdict_box(
            "Breach probability",
            passed=mc.breach_probability < 0.05,
            detail=(
                f"{mc.breach_probability:.1%} of {args.paths:,} {args.method}-bootstrap paths "
                f"breached the ${rules.max_loss_limit:,.0f} maximum loss limit"
            ),
        )
    )
    # Counts arrive as float64 (NaN survival probabilities force the whole
    # frame wide); cast them back so the report reads "20 sessions", not "20.0".
    curve = mc.survival_curve.astype(
        {c: "Int64" for c in ("sessions", "survived", "breached", "censored", "n_paths")
         if c in mc.survival_curve.columns}
    )
    parts.append(
        section("Survival curve", markdown_table(curve, formats={"survival_probability": ".1%"}))
    )

    headline = pd.DataFrame(
        [
            {"metric": "Historical replay", "value": run.summary()},
            {"metric": "Net PnL", "value": f"${run.net_pnl:,.2f}"},
            {"metric": "Worst MLL headroom", "value": f"${run.min_mll_headroom:,.2f}"},
            {"metric": "Max intraday drawdown", "value": f"${run.max_intraday_drawdown:,.2f}"},
            {
                "metric": "Largest day / total profit",
                "value": "n/a" if run.consistency_ratio is None else f"{run.consistency_ratio:.1%}",
            },
            {"metric": "Terminal equity (5th pct)", "value": f"${mc.terminal_equity_percentiles.get(5, float('nan')):,.2f}"},
            {"metric": "Terminal equity (50th pct)", "value": f"${mc.terminal_equity_percentiles.get(50, float('nan')):,.2f}"},
        ]
    )
    parts.append(section("Headline", markdown_table(headline)))

    if rules.payout_paths:
        payout = pd.DataFrame(
            [
                {
                    "path": name,
                    "ever eligible": e.eligible,
                    "eligible now": e.eligible_at_end,
                    "first eligible on": e.eligible_on,
                    "sessions to first": e.sessions_to_eligibility,
                }
                for name, e in run.payout_eligibility.items()
            ]
        )
        parts.append(section("Payout eligibility", markdown_table(payout)))

    parts.append(
        section(
            "Personal daily stop sweep",
            markdown_table(
                daily_stop_sweep(trades, rules, [150, 200, 250, 300, 400, 600]),
                formats={"personal_daily_stop": ",.0f", "net_pnl": ",.2f", "final_equity": ",.2f"},
            ),
        )
    )
    parts.append(
        section(
            "Trade frequency, net of commission",
            markdown_table(
                frequency_analysis(trades, rules, [0.5, 1.0, 1.5, 2.0], commission_per_rt=4.0)
            ),
        )
    )
    parts.append(
        section("Five consecutive losses", markdown_table(consecutive_loss_analysis(trades, rules, n=5)))
    )
    parts.append(section("Consistency", markdown_table(consistency_analysis(trades, rules))))

    tiers = [
        PRESETS[k]
        for k in (
            f"topstep_{args.account_type}_50k",
            f"topstep_{args.account_type}_100k",
            f"topstep_{args.account_type}_150k",
        )
        if k in PRESETS
    ]
    if tiers:
        parts.append(section("Account size comparison", markdown_table(account_size_comparison(trades, tiers))))

    parts.append(
        section(
            "Rules provenance",
            f"Rule set: `{rules.name}`, vintage **{rules.rules_as_of}** "
            f"(module default {RULES_AS_OF}).\n\n"
            f"- Maximum loss limit: ${rules.max_loss_limit:,.0f}\n"
            f"- Starting balance: ${rules.starting_balance:,.0f} (nominal ${rules.nominal_size:,.0f})\n"
            f"- Trails on: `{rules.trail_on.value}`; includes unrealised PnL: "
            f"`{rules.includes_unrealized}`; locks at: `{rules.lock_at.value}`\n"
            f"- Firm daily loss limit: {rules.daily_loss_limit}; personal stop: {rules.personal_daily_stop}\n\n"
            f"> {rules.source_note}\n\n"
            "Re-verify every figure above against the firm's current rulebook before "
            "acting on this report. See `docs/verification-checklist.md`.",
        )
    )
    # Blank line between blocks: a markdown heading immediately after a
    # blockquote or table does not render as a heading in most viewers.
    return "\n\n".join(part.rstrip() for part in parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = load_config().ensure_dirs()

    trades = load_trades(Path(args.trades))
    if not trades:
        print("no trades in file; nothing to simulate")
        return 1

    rules = resolve_rules(args.account, args.account_type, args.daily_stop)

    if rules.includes_unrealized and all(t.mae == 0.0 for t in trades):
        print(
            "WARNING: every trade has mae == 0, but these rules count unrealised PnL "
            "toward the drawdown limit. The breach probability below is therefore a "
            "LOWER BOUND — open-position drawdown is invisible to it. Re-export the "
            "trades with MAE populated before trusting the survival numbers.\n"
        )

    report = build_report(trades, rules, args)

    out = Path(args.out) if args.out else cfg.results_dir / f"account_{rules.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)

    run = AccountSimulator(rules).run(trades)
    print(run.summary())
    print(f"\nreport written to {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
