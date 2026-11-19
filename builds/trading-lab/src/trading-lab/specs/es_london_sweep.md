# ES London Sweep — `lab/strategies/es_london_sweep.py`

One pattern: the Asia range gets swept, the market fails to hold outside it,
and displaces back through recent structure. The strategy's job ends at
emitting an entry `Signal`; how the trade is managed afterwards (target,
trail, time-out) is entirely the caller's `ExitPolicy` choice and is **not**
part of this spec.

## Session window

- Instrument: **ES** (E-mini S&P 500, CME), tick size `0.25`, tick value `$12.50`.
- Asia range is the high/low of the `asia` session window, **18:00–02:00
  America/Chicago**, anchored so it ends inside the trading day being traded
  (i.e. Monday's Asia session runs Sunday 18:00 → Monday 02:00 CT).
- Entries are only evaluated inside the `entry_window` parameter, default
  `LONDON` = **02:00–07:00 America/Chicago**. No bar outside this window is
  ever scanned.

## Entry trigger — stated so two people mark the same bar

Scanning proceeds bar by bar through the entry window, independently for
each direction (short first, then long, per the code's iteration order):

1. **Sweep**: the first bar whose `high` (short setup) or `low` (long setup)
   trades at least `sweep_min_ticks` (default 4 ticks = 1.00 pt) beyond the
   Asia high/low. That bar's extreme becomes the *sweep extreme*. Bars inside
   a blocked news window (`ctx.in_news_block(ts)`) are skipped while
   searching for the sweep.
2. **Reclaim**: within `reclaim_within_bars` (default 6) bars *after* the
   sweep bar, the first bar whose `close` is back inside the Asia range
   (below the Asia high for a short setup, above the Asia low for a long
   setup). If no bar reclaims in time, no signal.
3. **Displacement**: starting at the reclaim bar and continuing through the
   same `reclaim_within_bars` window, the first bar whose `close` breaks the
   prior swing extreme (the high/low over the `structure_lookback` = 15 bars
   immediately *before* the sweep bar) by at least `displacement_atr_mult` ×
   ATR (ATR from `ctx.as_of(ts)`, so it only ever sees bars `<= ts`). That
   bar's timestamp is the signal's decision time (`Signal.ts`); its `close`
   is the *displacement close*.
4. If the displacement bar itself falls inside a blocked news window, no
   signal is emitted for that direction, even though sweep and reclaim
   already happened.

Two people watching the same bar frame will mark the identical sweep bar,
reclaim bar and displacement bar, because every comparison above is a plain
`>=`/`<=`/`<`/`>` on OHLC values already fixed at bar close — there is no
"looks like" judgement call.

## Entry price and type

- `entry_type = "limit"` (default): entry sits at `retrace_pct` (default
  50%) of the way back from the displacement close toward the sweep extreme,
  rounded to the instrument's tick grid. The order is a resting limit,
  active from the bar *after* the displacement bar and valid for
  `order_valid_bars` (default 10) bars (`valid_until`).
- `entry_type = "market"`: enters at the displacement close instead (fills
  at the next bar's open, slipped, per the engine's market-fill convention).

## Stop placement

`stop_buffer_ticks` (default 3 ticks = 0.75 pt) beyond the sweep extreme —
above it for a short, below it for a long. The stop is fixed at signal
construction; this strategy never moves it itself (a caller-supplied
`BreakevenAfterR` or `AtrTrail` exit policy may).

## Profit-taking rule

**None set by the strategy.** `Signal.targets` is always empty; the ladder
(or absence of one) is entirely the `ExitPolicy` passed to the engine at
backtest time — e.g. `FixedR(1.5)`, `MultiTargetR(...)`, or `AtrTrail(...)`.
Any number produced by this strategy is only meaningful together with the
exit policy it was run under.

## Maximum holding time

**None set by the strategy.** A position stays open until whatever
`ExitPolicy` the caller supplied closes it (stop, target, time stop, session
end, …), or until the data ends (`DATA_END`). `order_valid_bars` bounds only
how long the *unfilled entry order* stays live, not the holding time of a
filled position.

## News restrictions

Any bar inside a `ctx.in_news_block(ts)` window is skipped while scanning for
the sweep bar, and the displacement bar itself is checked again before a
signal is emitted — a setup whose sweep/reclaim happened cleanly but whose
final displacement bar lands in a blocked window produces no signal.

## Max attempts per session

`max_attempts_per_day` (default 1). Both directions are scanned independently
every day; the resulting signals (0, 1, or 2) are sorted by timestamp and
truncated to the first `max_attempts_per_day`. With the default of 1, if both
a short and a long setup complete on the same day, only the one whose
displacement bar came first is kept.

## Long and short rules

Fully symmetric: every rule above applies with high/low, above/below and
`>=`/`<=` mirrored between the short (Asia-high sweep) and long (Asia-low
sweep) cases. The code runs both directions through the identical `_scan`
method parameterised by `direction`.

## Invalidation conditions

A candidate is abandoned (no signal for that direction) when any of:

- No Asia session data exists for the day (`ctx.asia_high`/`asia_low` is
  `None`).
- `ctx.overnight_range` falls outside `[min_overnight_range,
  max_overnight_range]` when either bound is set (both default `None` = no
  filter).
- No bar in the entry window sweeps the Asia extreme by `sweep_min_ticks`.
- No bar reclaims inside `reclaim_within_bars` of the sweep.
- No bar displaces by `displacement_atr_mult` × ATR inside the same window
  (including: ATR itself is `None` or `<= 0` for every candidate bar).
- The displacement bar falls inside a blocked news window.
- Tick-rounding the retrace entry produces a stop/entry ordering `Signal.__post_init__`
  rejects (a razor-thin displacement leg) — skipped rather than fabricated.

## Parameter table

| Parameter | Default | Units |
|---|---|---|
| `sweep_min_ticks` | 4 | ticks |
| `reclaim_within_bars` | 6 | bars |
| `structure_lookback` | 15 | bars |
| `displacement_atr_mult` | 0.5 | × ATR |
| `retrace_pct` | 0.5 | fraction (0–1) of sweep-extreme-to-displacement-close |
| `entry_type` | `"limit"` | `"limit"` \| `"market"` |
| `stop_buffer_ticks` | 3 | ticks |
| `entry_window` | `LONDON` (02:00–07:00) | session window, America/Chicago |
| `max_attempts_per_day` | 1 | signals/day |
| `min_overnight_range` | `None` | points (instrument price units) |
| `max_overnight_range` | `None` | points (instrument price units) |
| `order_valid_bars` | 10 | bars |

## Change log

Standing rule: **one thing changes per version, and old results are never
rewritten under an old version tag.** A parameter change, a rule change, or
an instrument-cost change are each their own version bump; re-run and
publish under the new tag, keep the old tag's results as they were produced.

- **v1.0** — initial rule set as implemented: sweep → reclaim → displacement
  → retrace-limit entry, fixed stop beyond the sweep extreme, no target or
  time exit set by the strategy itself.

## Disable rule

*(To be filled in before this strategy is deployed with real size — see
`docs/scaling-gate.md` for the required form and the fields the rule must
cover.)*
