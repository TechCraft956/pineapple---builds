# Four-week deployment plan

Each week has an exit condition. Not meeting it means repeating the week, not
proceeding with a caveat.

---

## Week 1 — convert discretion into rules

Write the specification **before** the code. `specs/es_london_sweep.md` and
`specs/cl_opening_range.md` are the templates; each must pin down:

- exact session window in `America/Chicago`
- entry trigger, stated so two people would mark the same bar
- stop placement
- profit-taking rule
- maximum holding time
- news restrictions
- maximum attempts per session
- long and short rules (symmetric unless you can justify otherwise)
- what invalidates the setup

Then test each **exit** independently against the same entries — 1R, 1.5R, 2R,
opposing Asia level, prior-day level, and time stops at 15/30/60 minutes. This
is one loop over `lab.backtest.exits` policies, not six forks of the strategy.

Start with one objectively recognisable pattern. Stacking every concept you know
into version 1.0 produces a strategy with no attributable edge and no way to
debug it.

**Exit condition:** both specs written; both strategies produce signals on cached
data; the exit comparison table exists.

---

## Week 2 — robustness

Do not optimise across the full history and report the best cell. Use rolling
walk-forward: develop on 12 months, validate on the next 3, roll forward, and
never touch the final holdout.

Then stress it:

| Test | Module |
|---|---|
| +1 and +2 ticks of slippage | `robustness.sensitivity.stress_costs` |
| Commissions +25% | `robustness.sensitivity.stress_costs` |
| Every parameter ±10% and ±20% | `robustness.sensitivity.parameter_sweep` |
| Remove the best 5 trades / best 5 days | `robustness.dropn.drop_best` |
| Trend vs range vs news regimes | `robustness.regimes` |
| Overnight vs London vs US sessions | `robustness.regimes` |
| ES vs MES, CL vs MCL | `robustness.regimes` |

The reading: **a real edge degrades gradually; an overfit one collapses.** The
`fragility_score` reports the shape of the degradation, not just the perturbed
numbers.

**Exit condition:** the walk-forward out-of-sample expectancy is positive, and
the strategy survives every stress test above with its sign intact.

---

## Week 3 — live paper testing

Same decisions you would make on the funded account, executed on paper, with the
research machine providing context and nothing else.

Minimum before proceeding:

- 20 sessions
- 50 valid setups observed
- zero unauthorised trades
- zero parameter changes during the test
- every skipped signal documented
- every manual override documented

Compare, using `lab.journal.adherence`:

- theoretical entry vs observed fill (this is your real slippage — feed it back
  into `config/config.yaml` via `costs_measure.py`)
- backtest signal frequency vs forward frequency
- backtest win rate vs forward win rate
- **whether you hesitate specifically after losing trades** — `hesitation_analysis`
  measures it; it is the failure mode that ends working systems

**Exit condition:** forward frequency and expectancy are inside the confidence
interval the backtest predicted, and adherence is clean.

---

## Week 4 — controlled deployment

One strategy. One instrument. One account.

These are **starting research constraints, not optimal numbers** — replace them
with the output of `scripts/simulate_account.py --daily-stop-sweep` on your own
strategy as soon as it has enough trades to be meaningful:

**$150K funded**
- risk per trade ≈ $75–125
- max 3 legitimate attempts
- personal daily stop ≈ $250–350
- stop for the day after two emotional or rule-breaking decisions
- objective: controlled $150–300 qualifying days

**$50K combine**
- risk per trade ≈ $40–75
- personal daily stop ≈ $150–225
- max 2–3 attempts
- do not increase size to pass faster

### On trade frequency

Ten $30 trades are not automatically better than one $300 trade. The payout
rules count *qualifying days*, drawdown and consistency — not trade count. More
trades mean more commission, more slippage and more opportunities to break
discipline. `lab.risk.survival.frequency_analysis` answers this for your
strategy specifically rather than by intuition; run it before deciding to trade
more.

**Exit condition:** the account is intact, adherence is clean, and the
[scaling gate](scaling-gate.md) has been cleared before any size increase.
