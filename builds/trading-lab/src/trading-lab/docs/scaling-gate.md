# Scaling gate

The bar a strategy must clear before it gets more size, another instrument, or a
second funded account. Every line is a check the lab can produce; none of them
are judgement calls made in the moment.

## The gate

- [ ] **100–200 valid historical trades** — enough that expectancy is not one
      good month.
- [ ] **Positive expectancy on the untouched out-of-sample period.** Untouched
      means the holdout has been evaluated exactly once. `lab.ml.walkforward.final_holdout`
      makes a second access deliberately awkward for this reason.
- [ ] **Profit factor ≥ ~1.25 after realistic costs**, using measured commission
      and slippage, not defaults.
- [ ] **Survives +1 and +2 ticks of extra slippage** with the sign of expectancy
      intact.
- [ ] **No dependence on one exceptional day** — `drop_best(n=5, by="day")` and
      `drop_best(n=5, by="trade")` both leave the edge positive.
- [ ] **Worst five-day drawdown below ~20–25% of the account's Maximum Loss
      Limit.** Not of the account size — of the drawdown you are actually
      allowed.
- [ ] **Monte Carlo drawdown comfortably inside the MLL** — use the block or
      stationary bootstrap, not iid. Losing streaks are autocorrelated, and iid
      resampling is exactly the assumption that hides them.
- [ ] **≥ 20 forward-tested sessions** with clean adherence.
- [ ] **Stable across neighbouring parameters** — a low `fragility_score`. If
      the strategy only works at `retrace_pct = 0.62` and dies at `0.55`, you
      have fitted the number, not the behaviour.
- [ ] **A written rule for when the strategy must be disabled**, decided in
      advance. See below.

## The disable rule

Write it into the spec before deployment, in this form:

> `ES-LS-v1.1` is disabled when any of these is true:
> - realised expectancy over the last 30 trades falls below X
> - drawdown from the strategy's own equity peak exceeds Y
> - the setup frequency falls below Z per week for two consecutive weeks
> - adherence drops below N%
>
> Re-enabling requires: 20 fresh forward sessions and a written explanation of
> what changed.

The frequency condition matters as much as the PnL one. A pattern that stops
appearing has stopped existing, and that shows up before the losses do.

## What scaling means, in order

1. More size on the same strategy, same instrument, same account.
2. The micro contract on a second instrument.
3. The full contract on the second instrument.
4. A second account.

One step at a time, each with its own 20 sessions. Copying a strategy across
accounts multiplies correlated risk — two accounts running the same rules on the
same instrument are one position with two drawdown limits, and the losing day
that breaches one breaches both.
