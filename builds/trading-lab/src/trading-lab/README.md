# trading-lab

A research, backtesting, risk and machine-learning environment for discretionary
futures rules — built around the free market data API from
[London Strategic Edge](https://londonstrategicedge.com/).

**This lab does not trade.** Nothing in it connects to a broker, places an
order, or touches a funded account. It produces evidence; a human produces
orders, on the trading platform, by hand. That separation is the point — see
[`docs/operating-model.md`](docs/operating-model.md).

---

## What it does

| Module | Answers |
|---|---|
| `lab/data` | Which datasets exist, what they actually contain, and are they safe to backtest on? |
| `lab/strategies` | Two rule sets written down precisely enough to be falsified: **ES London sweep**, **CL opening range**. |
| `lab/backtest` | What would those rules have produced, after realistic commission, slippage and intrabar pessimism? |
| `lab/risk` | Would the account have survived the prop-firm drawdown rules — and when would it have qualified for a payout? |
| `lab/ml` | Given the setup has appeared, what's the probability of +1R before −1R? (A filter on an edge, never a source of one.) |
| `lab/robustness` | Does the edge degrade gracefully under stress, or collapse? |
| `lab/journal` | What did you actually do, versus what the rules said, and what did it cost? |
| `lab/reports` | Pre-session brief and post-session review, generated rather than remembered. |

## Setup

```bash
cd trading-lab
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then paste your key into it — .env is git-ignored
# or: export LSE_API_KEY='...'
```

Get a free key at <https://londonstrategicedge.com/data>. The key never belongs
in a script, a notebook, a config file or a commit; `lab.core.config` reads it
from the environment and is the only place that knows its name.

## First run — verify the data before building anything

```bash
python scripts/audit_catalog.py --categories futures volatility bonds
python scripts/fetch_data.py --symbols ES CL --timeframe 1m --start 2024-01-01
```

`audit_catalog.py` writes a report listing every futures dataset with its
history span and an *inferred* contract type. Inferred is the operative word:
you must establish, for each symbol you intend to trade, whether the series is a
single expiry, a raw stitched continuous series, or a back-adjusted continuous
series. A back-adjusted series has prices that never traded and gaps that never
happened, and a sweep strategy reading levels off one will invent signals.
`lab/data/continuity.py` flags the suspicious dates; `docs/verification-checklist.md`
tells you what to compare them against.

Do not skip this. Everything downstream inherits whatever is wrong here.

## Layout

```
trading-lab/
├── lab/
│   ├── core/          # shared contracts: types, instruments, sessions, frames, config
│   ├── data/          # LSE client, cache, catalog audit, rollover checks, economics
│   ├── strategies/    # ES London sweep, CL opening range
│   ├── backtest/      # engine, costs, exit policies, metrics
│   ├── risk/          # account rules, MLL simulator, Monte Carlo, survival analysis
│   ├── ml/            # features, labels, walk-forward, models, evaluation
│   ├── robustness/    # sensitivity, drop-best-N, regime splits
│   ├── journal/       # execution import, journal, adherence, measured costs
│   └── reports/       # premarket brief, session review
├── specs/             # one-page strategy specifications (write these first)
├── scripts/           # argparse CLIs
├── config/config.yaml # paths, cost overrides, account defaults — never secrets
├── data/              # cached parquet + your platform exports (git-ignored)
├── results/           # generated reports (git-ignored)
└── tests/
```

## The invariants

These are enforced by code and by tests, not by discipline:

1. **UTC internally, exchange clock at the boundary.** Session windows are
   defined in `America/Chicago` and converted through the tz database, so DST
   never silently relabels the London open.
2. **The CME trading day rolls at 17:00 CT.** Daily PnL, drawdown trailing and
   prior-day levels all agree with the broker because they all call
   `lab.core.sessions.trading_day`.
3. **No lookahead.** Features slice `bars.loc[:as_of]` internally; the engine
   may not read bar `i+1` at bar `i`; economic releases are unreadable before
   their publish timestamp. Each is a test, not a comment.
4. **Pessimistic intrabar.** When one bar spans both the stop and the target,
   the stop fills first unless finer bars resolve the sequence — and the count
   of ambiguous bars is reported, because a result that depends on many of them
   is a result that needs tick data.
5. **Costs are assumptions until measured.** The defaults in
   `lab/core/instruments.py` are deliberately conservative. Replace them with
   values `lab/journal/costs_measure.py` derives from your own fills.
6. **Results carry their provenance.** Every `BacktestResult` stamps the code
   parameters and a hash of the exact bars. One rule change per version, and
   old results are never rewritten.

## Documentation

- [`docs/operating-model.md`](docs/operating-model.md) — the two-machine split and the daily routine
- [`docs/four-week-plan.md`](docs/four-week-plan.md) — rules → robustness → forward test → controlled deployment
- [`docs/verification-checklist.md`](docs/verification-checklist.md) — what to verify before trusting any number here
- [`docs/scaling-gate.md`](docs/scaling-gate.md) — the bar a strategy must clear before it gets more size
- [`specs/`](specs/) — the strategy specifications

## Standing caveats

- **Verify the vendor's data yourself.** London Strategic Edge is a young
  platform. Timestamps, session alignment, missing bars, rollover treatment and
  live-feed latency are all things to confirm against your broker's chart
  before a number from this lab influences a real order.
- **Verify the account rules yourself.** `lab/risk/rules.py` encodes prop-firm
  drawdown and payout rules as *parameters* with an `RULES_AS_OF` date and a
  source note. They change. Re-read the current rulebook before trusting a
  survival curve.
- **A backtest is a hypothesis.** Costs, fills and your own behaviour under
  drawdown are all estimated here and real out there. The forward test in week
  three exists because that gap is where accounts die.
