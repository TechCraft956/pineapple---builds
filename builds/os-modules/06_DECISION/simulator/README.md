# End-State Decision Simulator

Module: `06_DECISION/simulator/simulator.py`
Plugin id: `decision_simulator` · Category: `DECISION` · Status: **sample**

> **ANALYSIS ONLY — not financial, tax, lending, or investment advice.**
> Every projection is a deterministic function of *your* assumptions. Reality
> will differ. Validate params against the real Pineapple modules and the
> cited public sources before acting.

## What it does

Models life/capital decisions as parameterized scenarios and projects the
**end-state net-worth delta** at three horizons — **1 month / 1 year / 5 years** —
using *symbolic* `sympy` expressions (so the math is transparent and
re-derivable, not a black box).

Each `simulate()` returns:

- `projected_net_worth_delta` → `{"1mo", "1yr", "5yr"}` (USD, signed)
- `risk` → `LOW` / `MED` / `HIGH`
- `bottleneck` → the single constraint that gates the outcome
- `best_next_action` → the concrete next move
- `expr` → the sympy expression strings used (audit trail)
- `params` → the resolved inputs

### Scenarios covered

| kind                | question modeled |
|---------------------|------------------|
| `flip_vs_save`      | Buy a vehicle/bike to flip vs keep the cash in savings. EV per flip nets recon + fees + sell-through probability; compares against monthly-compounded savings. |
| `fha_now_vs_later`  | FHA home purchase **now** vs **waiting ~12 months**. Standard 360-mo amortization, appreciation, carrying costs (tax/insurance/MIP), rent avoided, rate path. |
| `debt_vs_deploy`    | Pay down high-APR debt (guaranteed return = avoided interest) vs deploy capital at a risk-adjusted expected return while the debt keeps compounding. |

Add a scenario by writing one `_sim_<kind>(params)->dict` and registering it in
the `_SIMS` map.

## Run it

```bash
# venv python (sympy lives here)
PY="C:/Users/chamg/Documents/Projects_NEW/PINEAPPLE_OS/.venv/Scripts/python.exe"

"$PY" simulator.py --selftest   # health summary, exits 0 on success
"$PY" simulator.py              # run all sample scenarios + print projections
"$PY" simulator.py --json       # full results + items() as JSON
"$PY" simulator.py --write      # also write 00_PROCESSED/decision_simulator.json
```

Requires the data-science venv (sympy 1.14.0). Pure-stdlib otherwise; offline.

## Public API

```python
from simulator import simulate, items, run_all, PLUGIN

simulate("debt_vs_deploy", {"capital": 10000, "debt_apr": 0.219, ...})
simulate(scenario_dict)          # dict with 'kind'/'name'/'params'
items()                          # ranked recommendations for the brief
```

## How it plugs into the decision brief

`items()` returns a list of recommendation dicts already shaped for the
existing decision engine (`decision_engine.py` / `decision_brief.json`). Each
item carries:

`title, category, source, action, est_value, risk, location, url, confidence`

plus engine-tolerated extras (`projected_net_worth_delta`, `bottleneck`,
`scenario`, `disclaimer`). Items are ranked by absolute 1-year net-worth swing.

- `category` is `DECISION`; `est_value` = projected 1-year net-worth delta.
- `confidence` is capped at 0.8 because inputs are **sample** data.
- The engine can ingest these the same way it ingests module opportunities;
  the simulator is meant to sit downstream of the radar/economic/family-bank
  modules — feed their real numbers in as `params` to replace the samples.

Running with `--write` drops `00_PROCESSED/decision_simulator.json`
(the only file written outside this folder), containing all results + `items()`.

## Data

`data/sample_scenarios.json` — three realistic, clearly-labeled **sample**
scenarios tuned for the Rio Grande Valley (Hidalgo/Cameron County, South Texas).
Marked `"status": "sample"` with source attribution. **No live data is fetched.**

### Real public data sources to wire later

| field | source |
|-------|--------|
| 30y mortgage rate | Freddie Mac PMMS — https://www.freddiemac.com/pmms |
| FHA county loan limits | HUD — https://entp.hud.gov/idapp/html/hicostlook.cfm |
| FHA 203(b) program | HUD — https://www.hud.gov/buying/loans |
| CPI / inflation | BLS — https://www.bls.gov/cpi/ |
| rates / economic series | FRED — https://fred.stlouisfed.org/ |
| county appraisal values | Hidalgo CAD — https://www.hidalgoad.org/ · Cameron CAD — https://www.cameroncad.org/ |
| used-vehicle values | NADA — https://www.nadaguides.com/ · KBB — https://www.kbb.com/ |

## Safety

Read-only toward the user's real folders. Writes only inside this folder or
`00_PROCESSED`. No network. No money movement. **Analysis, not advice.**
