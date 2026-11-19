# CL Opening Range — `lab/strategies/cl_opening_range.py`

Three related setups built off one range definition. `variant` selects which
one a given `ClOpeningRange` instance trades; only one variant runs per
instance/backtest. As with every strategy in this lab, the strategy's job
ends at emitting an entry `Signal` — target, trail and time-based management
are the caller's `ExitPolicy` choice, not part of this spec.

## Session window

- Instrument: **CL** (Crude Oil, NYMEX), tick size `0.01`, tick value `$10.00`.
- The opening range (OR) is the high/low of the first `or_minutes` (5, 15 or
  30) minutes of `CL_RTH`, **08:00 America/Chicago**.
- All scanning after the OR forms happens inside the remainder of `CL_RTH`,
  which ends **13:30 America/Chicago**.
- No new entry is considered after `entry_deadline_minutes` (default 120)
  minutes past 08:00 — i.e. by default, no new entry after **10:00 CT**,
  even though the session runs until 13:30.

## Entry trigger — stated so two people would mark the same bar

Detection is a single forward scan over the post-OR bars (both directions
scanned independently; ties broken by which direction's decision bar comes
first). A bar inside `ctx.in_news_block(ts)` is always skipped while
scanning for a trigger, retest, break or reclaim bar — never counted toward
any of the "within N bars" windows below.

### `breakout`

The first post-OR bar whose `high` (long) or `low` (short) reaches the OR
edge (`>=`/`<=`) is the trigger bar. If `volume_filter` is on, that same bar
must also have `volume > vol_mult × ctx.same_time_of_day_volume(ts)`
(median volume at that wall-clock minute over the last 20 prior trading
days); if the median is unavailable, the bar does not qualify. `Signal.ts` =
trigger bar's timestamp.

### `breakout_retest`

1. **Confirm**: the first post-OR bar whose `close` (not just intrabar
   range) is beyond the OR edge — same `volume_filter` check as above,
   applied to this bar.
2. **Retest**: within `retest_within_bars` (default 5) bars after
   confirmation, the first bar whose range reaches back to the OR edge
   (`low <= edge` for a long, `high >= edge` for a short). `Signal.ts` = this
   retest bar's timestamp.

### `failed_breakout`

1. **Break**: the first post-OR bar that clears an edge by at least
   `min_break_ticks` (default 4 ticks = 0.04) — `low <= or_low -
   min_break_ticks×tick` for the setup that will reverse **long**, or
   `high >= or_high + min_break_ticks×tick` for the setup that will reverse
   **short**. Same `volume_filter` check, applied to this bar. That bar's
   extreme (`low` or `high`) is the *failed extreme*.
2. **Reclaim**: within `reclaim_within_bars` (default 6) bars after the
   break, the first bar whose `close` is back inside the OR (`close >
   or_low` for the long reversal, `close < or_high` for the short reversal).
   `Signal.ts` = this reclaim bar's timestamp.

In every variant, if the decision bar (trigger / retest / reclaim) itself
falls on or after `entry_deadline_minutes`, or inside a blocked news window,
no signal is emitted for that candidate.

## Entry order type and price

| Variant | `entry_type` | `entry` price |
|---|---|---|
| `breakout` | `"stop"` | the OR edge that was traded through |
| `breakout_retest` | `"limit"` | the OR edge (the retest level) |
| `failed_breakout` | `"market"` | the reclaim bar's `close` (nominal; market fills at the next bar's open per the engine) |

The order stays live for `order_valid_bars` (default 5) bars after the
decision bar (`valid_until`).

## Stop placement

- `breakout` / `breakout_retest`: `stop_mode` selects between
  `"opposite_edge"` (the far side of the OR — the default) and `"buffer"`
  (`stop_buffer_ticks` beyond the entry, on the risk side).
- `failed_breakout`: always `stop_buffer_ticks` beyond the *failed extreme*
  (the wick that broke the edge), regardless of `stop_mode` — the point of
  the trade is that the extreme already marks where the setup is wrong.

## Profit-taking rule

**None set by the strategy.** `Signal.targets` is always empty; profit
management is entirely the caller's `ExitPolicy`.

## Maximum holding time

**None set by the strategy.** `order_valid_bars` bounds only the unfilled
entry order's lifetime, not how long a filled position may stay open — that
is the `ExitPolicy`'s job (e.g. a `SessionEnd(CL_RTH)` policy to flatten by
13:30 CT).

## News restrictions

Every bar considered as a trigger/confirm/break bar, and as a
retest/reclaim bar, is checked against `ctx.in_news_block(ts)` and skipped if
blocked (CL's blocked windows are expected to cover EIA/API inventory
releases and other high-impact energy prints — see `lab.data.economics`).
Every emitted signal additionally carries `meta["news_day"]`: whether *any*
blocked news window overlaps the day's `CL_RTH` session at all, even if the
particular entry bar itself was clean — so days containing an inventory
report can be sliced out of a results table rather than silently averaged in
with ordinary days.

## Max attempts per session

`max_attempts_per_day` (default 1). Long and short are scanned
independently (at most one candidate signal each); results are sorted by
timestamp and truncated to the first `max_attempts_per_day`.

## Long and short rules

Fully symmetric in all three variants — every rule above applies with
high/low, above/below, and `>=`/`<=` mirrored between the long and short (or,
for `failed_breakout`, the long-reversal and short-reversal) cases. Each
variant's scan method is parameterised by `direction` and run for both.

## Invalidation conditions

A candidate produces no signal, or the whole day produces no signals, when
any of:

- No bars fall inside the OR window for the day.
- The OR is degenerate (`or_high <= or_low`, e.g. a single tick print).
- `max_range_atr_pct` is set and the OR width exceeds that fraction of ATR
  (or ATR itself is unavailable at OR completion) — the whole day is skipped,
  both directions.
- No post-OR bar exists at all (OR ran through the end of the session).
- No bar completes the variant's trigger condition before
  `entry_deadline_minutes`.
- `volume_filter` is on and the qualifying bar's volume does not exceed
  `vol_mult` × the same-time-of-day median (or the median is unavailable).
- The decision bar falls inside a blocked news window.
- Tick-rounding produces a stop/entry ordering `Signal.__post_init__` rejects.

## Parameter table

| Parameter | Default | Units |
|---|---|---|
| `or_minutes` | 15 | minutes; one of {5, 15, 30} |
| `variant` | `"breakout"` | `"breakout"` \| `"breakout_retest"` \| `"failed_breakout"` |
| `stop_mode` | `"opposite_edge"` | `"opposite_edge"` \| `"buffer"` |
| `stop_buffer_ticks` | 10 | ticks |
| `min_break_ticks` | 4 | ticks |
| `reclaim_within_bars` | 6 | bars |
| `retest_within_bars` | 5 | bars |
| `order_valid_bars` | 5 | bars |
| `volume_filter` | `False` | bool |
| `vol_mult` | 1.5 | × same-time-of-day median volume |
| `max_range_atr_pct` | `None` | fraction of ATR; `None` = no cap |
| `max_attempts_per_day` | 1 | signals/day |
| `entry_deadline_minutes` | 120 | minutes past the 08:00 CT open |

## Change log

Standing rule: **one thing changes per version, and old results are never
rewritten under an old version tag.** A parameter change, a rule change
(including switching `variant`), or an instrument-cost change are each their
own version bump; re-run and publish under the new tag, keep the old tag's
results as they were produced.

- **v1.0** — initial rule set as implemented: three OR variants
  (`breakout`, `breakout_retest`, `failed_breakout`) off a configurable
  opening range, symmetric long/short, no target or time exit set by the
  strategy itself.

## Disable rule

*(To be filled in before this strategy is deployed with real size — see
`docs/scaling-gate.md` for the required form and the fields the rule must
cover.)*
