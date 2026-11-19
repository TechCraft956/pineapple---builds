# Verification checklist

Everything in this lab is downstream of two things it cannot verify for you:
the vendor's data and the prop firm's current rulebook. Work through this list
once per instrument, and again whenever either changes.

---

## 1. Data — before any backtest is trusted

Run `python scripts/audit_catalog.py --categories futures` and answer, per symbol:

- [ ] **What is this series?** Single expiry, raw stitched continuous, or
      back-adjusted continuous? `lab/data/continuity.py` infers a verdict; treat
      it as a hypothesis to confirm, not an answer.
- [ ] **How far back does it go, and is it continuous the whole way?** Check the
      gap report for mid-history holes.
- [ ] **Do the timestamps mean what you think?** Pick a session and confirm the
      RTH open bar lands at 08:30 CT (13:30/14:30 UTC depending on DST). An
      off-by-one-hour feed produces a strategy that trades the wrong window and
      backtests beautifully.
- [ ] **Do the rollovers behave?** `sample_for_manual_check` returns the detected
      roll windows. Compare each against your broker's chart. A back-adjusted
      series shows a price discontinuity that never traded; a raw stitched one
      shows a gap that will look like a sweep.
- [ ] **Ten random sessions match the broker chart** — bar for bar on the
      session high, low, open and close. Include at least two roll periods.
- [ ] **Volume is real.** Zero-volume and flat (`high == low`) bar counts from
      `assess_quality` should be near zero on a liquid instrument during RTH. A
      cluster of them is a synthetic fill, and stops will "fill" inside bars
      that never traded.
- [ ] **Prices are never negative** after back-adjustment (a classic artefact,
      and a signal that levels are shifted, not just the deltas).

If ES and MES (or CL and MCL) disagree on a session's high or low by more than a
tick, at least one of the series is wrong. Find out which before continuing.

## 2. Economic data

- [ ] Confirm each release's timestamp is the **publish** time, not the period
      the data describes. `lab/data/economics.py` refuses reads before the
      publish timestamp; that guard is only as good as the timestamps.
- [ ] Spot-check three past releases against a public calendar for time, actual
      and consensus.
- [ ] Confirm the calendar covers the events you actually block on: CPI, NFP,
      FOMC, and for CL the weekly inventory reports.

## 3. Live feed — before the forward test

- [ ] Measure latency: compare a streamed tick's timestamp to local time over a
      few hundred ticks. A feed that is two seconds behind cannot confirm a
      one-minute displacement candle in time to act on it.
- [ ] Confirm the live bars and the historical bars for the same period agree.
      They are frequently produced by different pipelines.
- [ ] Confirm the concurrent-symbol limit and what happens when you exceed it
      (silent drop vs error). The free tier is documented around 16 symbols.

## 4. Account rules — before any survival number is quoted

`lab/risk/rules.py` carries a `RULES_AS_OF` date and a `source_note` on every
preset. Confirm against the firm's current rulebook:

- [ ] Maximum Loss Limit per account size
- [ ] Whether the MLL includes **unrealised** P&L (the simulator's headline
      breach number depends entirely on this)
- [ ] Whether the MLL trails on end-of-day results, intraday peak, or closed
      equity — and exactly when it stops trailing
- [ ] The starting balance of the account type you hold (Express Funded starts
      at zero, not the nominal size)
- [ ] Payout requirements: number and size of qualifying days, minimum trading
      days, and the largest-day consistency percentage
- [ ] Daily loss limit, if the firm imposes one on top of the MLL
- [ ] Commission per round turn actually charged on your account

Update the preset and re-run. A survival curve computed against last year's
rules is worse than no survival curve, because it is believed.

## 5. Costs — after 50+ real fills

- [ ] Run `lab/journal/costs_measure.py` and replace the `cost_overrides` block
      in `config/config.yaml` with measured values.
- [ ] Re-run every backtest whose conclusions you are relying on. Costs move
      expectancy more than most parameter choices do.

## 6. The lab itself

- [ ] `pytest` passes.
- [ ] The no-lookahead tests pass (`test_engine.py`, `test_ml_features.py`) —
      these are the ones that catch the errors you would otherwise never see.
- [ ] Every result in `results/` carries a `data_fingerprint`. A result without
      one cannot be reproduced and should be deleted rather than cited.
