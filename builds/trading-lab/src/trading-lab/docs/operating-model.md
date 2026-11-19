# Operating model

## Two machines, one job each

The single most expensive mistake available to a systematic-discretionary trader
is turning a research idea into a funded-account order in the same five minutes
it occurred to them. The defence is physical, not psychological.

**Trading machine — execution only.**

- The broker/prop platform and its order entry
- One primary chart per instrument being traded
- Account risk settings
- Nothing else. No notebooks, no scripts, no model training, no strategy edits
  during a session.

**Research machine — everything else.**

- This lab: data, backtests, Monte Carlo, ML training, account simulation
- The market-data terminal, journal analysis, and any coding assistant
- Where new ideas live until they have cleared the gate in
  [`scaling-gate.md`](scaling-gate.md)

A rule you changed at 09:40 has not been tested. The separation makes that
obvious instead of arguable.

## What runs where

| Task | Machine | Tool |
|---|---|---|
| Pre-session brief | Research | `scripts/report_premarket.py` |
| Live context, levels, alerts | Trading (read-only) | Charting terminal |
| Order entry | Trading | Broker platform, manually |
| Post-session review | Research | `scripts/report_session.py` |
| Backtests, sweeps, ML | Research | this lab |
| Account survival simulation | Research | `scripts/simulate_account.py` |

## Daily routine

### Before the session

1. Run the pre-market report. Read it before opening a chart, not after.
2. Confirm scheduled high-impact releases and mark the blocked windows.
3. Mark the Asia high/low and prior-day levels the report produced.
4. Note the overnight range and its percentile — this is the regime input.
5. Accept the report's verdict on **which single strategy is permitted today**.
   One strategy. Not "whichever one the market looks like".
6. Set the personal daily loss lock on the platform.
7. Decide the maximum number of attempts, and write the number down.

### During the session

- The research machine provides context. The trading machine provides fills.
- No retraining, no rule editing, no strategy switching after a loss.
- Screenshot every entry.
- Log every valid setup you *skipped* — a journal of only the trades you took
  cannot detect the moment you stopped trusting the system.

### After the session

Export the platform's trade file, then:

```bash
python scripts/journal_import.py --file data/topstep_exports/2026-08-05.csv
python scripts/report_session.py --day 2026-08-05
```

The review records strategy version, setup tag, entry/exit, MFE/MAE, slippage
against the theoretical fill, rule adherence, emotional state, whether the model
approved the trade, and whether it was in the plan.

### Weekend

Change **one** thing per new strategy version, and bump the version:

```
ES-LS-v1.0 — 1.5R fixed target
ES-LS-v1.1 — adds high-impact-news exclusion
ES-LS-v1.2 — adds maximum overnight-range filter
```

Old results are never edited to match a new rule. If a version's numbers
embarrass the current version, that is information, not a formatting problem.

## Where the machine learning fits

It does not predict direction. It answers one question, after the setup has
already qualified: *what is the probability price reaches +1R before −1R within
the next N minutes?* A model that improves win rate while worsening expectancy
is rejected automatically by `lab.ml.evaluate.accept_model` — win rate is the
metric most easily improved by making the system worse.

A useful outcome looks like "skip the first entry within 20 minutes of a
high-impact release" or "only take the reversal variant when the overnight range
is in the bottom tercile". It does not look like a prediction for the next
candle.

## Standing rules

- One strategy, one instrument, one account until the evidence says otherwise.
- The daily stop is set before the session and is not moved during it.
- Two rule-breaking decisions ends the day, regardless of PnL.
- Research output never becomes an order in the same session it was produced.
