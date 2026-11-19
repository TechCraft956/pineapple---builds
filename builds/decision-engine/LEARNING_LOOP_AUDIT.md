# Learning-loop audit (Decision Engine build, 2026-11-17)

## Verdict

**The read-back is wired in code and proven with synthetic outcomes — but it
has never run on a real outcome.** Zero realised outcomes exist anywhere in
this workspace, so the loop is code-complete and production-unproven. Nothing
was invented: every `actual_roi` in the real log is null.

## How the loop is supposed to close

1. `decision_engine.build_brief()` appends each recommended top action to
   `06_DECISION/outcomes_log.jsonl` with `status: "recommended"` and
   `actual_roi: null` (append-only; verified by test).
2. The owner (or a later step) records what actually happened:
   `python 06_DECISION/learning.py record <id> --status sold --actual-roi 0.42`.
3. `learning.py recalibrate` reads all CLOSED rows (`sold` / `skipped` /
   `expired`) that carry an `actual_roi`, correlates each quant dimension's
   favourable value with realised ROI, and writes nudged weights to
   `00_INDEX/quant_weights.json` (max ±0.04 per dimension per cycle,
   renormalised) plus `06_DECISION/learning_report.md`. It refuses with
   fewer than 3 closed outcomes.
4. `pineapple_quant.score()` calls `load_weights()` on every call, so the
   next brief ranks with the sharpened weights. The engine exposes this
   behind a flag: `build_brief(use_learned_weights=True)` (default) and
   CLI `--no-learned-weights` forces the built-in defaults.

## Evidence (this build)

- Real log, 2026-11-17: 20 rows, all `recommended`, 0 closed.
  `learning.py stats` → 20 total; `recalibrate` → "Need >=3 closed outcomes
  with actual_roi to recalibrate. Have 0." No `quant_weights.json` exists, so
  the engine currently scores on the built-in default weights.
- Seam proven in an isolated temp copy (deleted afterwards) with 3 SYNTHETIC
  closed rows only: `recalibrate` wrote `00_INDEX/quant_weights.json`
  (roi 0.4106, time 0.1313, risk 0.1826, difficulty 0.1152, capital 0.1604;
  mean realised ROI 0.200) and a learning report; `load_weights()` read them
  back and a TW200-style input scored 81.0 with learned weights vs 81.1 with
  defaults. The synthetic rows never touched the real log.
- `tests/test_decision_engine.py::TestLearnedWeightsFlag` proves the same
  seam in the suite: a weights file changes scoring, and the
  `use_learned_weights=False` path ignores it.

## What is NOT wired

- **Simulator → brief.** `06_DECISION/simulator/simulator.py` is
  analysis-only: `simulate()` / `items()` project end-state net-worth deltas
  for three sample scenarios. It never reads outcomes, and the decision
  engine never ingests its `items()` (the engine only discovers modules
  under the 02/03/04/05 bucket folders; the simulator lives under
  06_DECISION). Wiring it in would change brief composition and needs its
  own decision — left unwired, documented here.
- **No automatic trigger.** `recalibrate` is a manual command. Nothing
  schedules it, and this build adds no schedule (that would cross the
  pipeline's hard boundaries).

## Gaps found in the recovered code (not changed, noted)

- `learning.py cmd_record` **rewrites the whole log file** (`_write`) rather
  than appending. The append-only contract in the brief covers the engine's
  logging; a record update is a deliberate rewrite of one row. Worth knowing
  before anyone treats the log as immutable history.
- `pineapple_quant._root()` falls back to the `_lib/` folder when no
  `.pineapple_root` marker is found anywhere above it. In that case weights
  are read/written at `_lib/00_INDEX/quant_weights.json` instead of the
  workspace `00_INDEX/` — silently. This build ships the marker at the
  workspace root, so the correct path is used; any future copy of this code
  must carry the marker with it.
- `simulator.py` requires **sympy** (non-stdlib; 1.12 present in this
  sandbox) and carries a hardcoded Windows absolute `PROCESSED` path, so
  `--write` is not usable on this Linux runtime. Its selftest passes
  (3 sample scenarios, `items()` → 3 ranked recommendations) after the
  sample data file was recreated — see BUILD_REPORT.md.
- Scoring is **uncalibrated against outcomes** (brief gap #6, unchanged):
  with zero realised outcomes, no ranking here can be called calibrated.
