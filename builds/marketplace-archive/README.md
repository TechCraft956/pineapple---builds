# Marketplace Scraper — archive build (BUILD-20261117-007)

Isolated workspace for the Marketplace Scraper archive brief. The scraper
itself is **archived, not built** — see `ARCHIVE_RECORD.md` for the decision
and evidence. The only code carried forward is the Vehicle Financing Deal
Optimizer, extracted standalone.

## Contents

| File | What it is |
|---|---|
| `vehicle_deals.py` | Extracted evaluator, byte-identical to `snapshot/backend/vehicle_deals.py` (diff-verified). Only dependency: pydantic. |
| `vehicle_deals_cli.py` | CLI: `--json request.json` (or `--json -` for stdin) in, ranked JSON out. Exit 0 on success, 2 on bad input. |
| `test_vehicle_deals.py` | 24 tests: hand-computed payment fixtures, ranking, pursue/negotiate/pass boundaries, invalid inputs, import isolation, CLI. |
| `requirements.txt` | `pydantic>=2.0.0` (the evaluator's only dependency). |
| `.venv/` | Isolated venv with pydantic 2.14.3 (created for this build; system Python has no pydantic). |
| `ARCHIVE_RECORD.md` | The archive decision: full module inventory with covered-by verdicts, supersession mapping, cookie-auth failure evidence, standing GitHub-token flag. |
| `BUILD_REPORT.md` | This build's evidence: test results, verification steps, surprises. |
| `snapshot/` | Read-only historical snapshot of the recovered repo (52 files, no `.git`, no `__pycache__`). Not a build input. See `snapshot/SNAPSHOT_README.md`. |

## Run the tests

```sh
.venv/bin/python -m unittest test_vehicle_deals -v
```

## Run the evaluator

```sh
.venv/bin/python vehicle_deals_cli.py --json request.json
# request.json: {"deals": [{...one to ten vehicle scenarios...}]}
# see vehicle_deals_cli.py --help and test_vehicle_deals.py for the schema.
```

## Boundaries observed

No Facebook cookies created/uploaded/refreshed; no Playwright scraper run;
no seller contacted; nothing deployed; recovered originals untouched
(verified via `git status`/`git diff` and snapshot diff — see
`BUILD_REPORT.md`).
