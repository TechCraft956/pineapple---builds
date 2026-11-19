# BUILD REPORT — BUILD-20261117-006: Remaining OS Modules (09_SENSORS + 07_NETWORK + 06_DECISION)
Built by Everest (subagent run), 2026-11-17 ~23:35–23:55 CT. Workspace: `~/workspace/pineapple/builds/os-modules/`
Brief: `~/workspace/pineapple/build-briefs/OS_MODULES_BUILD_BRIEF.md` (stage GPT_REVIEWED; all 7 GPT QA gates are acceptance checks here).

## Verdict
**All acceptance checks pass.** Sensor selftest exit 0 (8 devices, 12 readings, 4 alerts); simulator selftest exit 0 (3 scenarios); network first-run kit end-to-end (2 SAMPLE users, audit-logged, permission matrix correct); **33/33 tests pass** offline (socket blocked in-test); feed round-trip **7/7 records** through a scratch local feed instance, ANALYSIS ONLY warning verbatim on every simulator record; learning recalibrate proven on synthetic closed outcomes with the outcomes log byte-identical afterwards; **0 real outcomes** exist — `actual_roi` stays null until a real outcome is logged. Recovered originals untouched (scoped `git status` clean for 09_SENSORS / 07_NETWORK / 06_DECISION / _lib).

## What was built (files changed / created — build copy only)
| File | Change |
|---|---|
| `09_SENSORS/data/devices.json` (new) | Restored SAMPLE registry: 8 devices, all 8 sensor types, realistic Roma TX coords (26.405x, -99.006x), fabricated telemetry. |
| `09_SENSORS/data/readings.json` (new) | 12 SAMPLE readings; latest-per-metric trips 4 alerts (garage open + left open 47 min, water detected, bike battery 11.8V) and leaves motion/temp/freezer/gate/mailbox quiet. |
| `06_DECISION/simulator/data/sample_scenarios.json` (new) | One SAMPLE scenario per kind (flip_vs_save TW200, fha_now_vs_later Starr County, debt_vs_deploy 21.9% APR). |
| `06_DECISION/simulator/simulator.py` (build copy) | **Portability patch only:** `PROCESSED` now resolves to this workspace's `00_PROCESSED` instead of the hard-coded Windows path `C:\Users\chamg\...`, which on Linux would have created a literal backslash-named directory under the CWD (caught live: first `--write` landed in `~/workspace/pineapple/builds/00_PROCESSED/`; stray file removed, path fixed to `HERE.parents[1]`, re-verified). No math touched. |
| `07_NETWORK/registry/roles.json` (new) | Roles from the architecture doc §2 (OWNER god_mode, ADMIN, FAMILY_USER, TRADER_USER, PAID_USER, GUEST), least-privilege. |
| `07_NETWORK/registry/plans.json` (new) | Plans from the architecture doc §12 (FREE_FAMILY, TRADER_BASIC, TRADER_PRO, BUSINESS_BASIC, CUSTOM). Entitlement checks only. |
| `07_NETWORK/dashboard.py` (build copy) | Footer link-out to the shared feed (`/api/feed/opportunities`) only — NOT rebuilt into a second feed UI. |
| `07_NETWORK/users.json`, `audit_log.jsonl`, `workspaces/` (generated) | First-run kit output: 2 SAMPLE users, 2 audit entries. |
| `scripts/first_run_kit.py` (new) | Seeds `sample_owner` + `sample_family`; passwords generated per run via `secrets`, passed by env var, verified in-memory against pbkdf2 hashes, never printed or written to any file; idempotent; records list/whoami/can + audit log to `07_NETWORK/first_run_kit_log.md`. |
| `tests/test_os_modules.py` + `tests/sim_driver.py` (new) | 33 tests (see below). |
| `writers/sensor_writer.py`, `writers/simulator_writer.py` (new) | Feed adapters (see below). |
| `verify_feed_roundtrip.py` + `BUILD_LOG_feed_roundtrip.txt` (new) | Scratch feed instance on 127.0.0.1:8102, token generated per run, service terminated after. |
| `feed-service-copy/` | Unmodified copy of `builds/feed-dash/feed-service` (diff clean except the original's leftover `data-live` dir, which was not copied). Read-only use. |
| `_lib/pineapple_api.py`, `_lib/pineapple_quant.py` (copied) | Unmodified copies from the recovered clone; `.pineapple_root` marker at workspace root (same convention as the decision-engine build). |
| `00_PROCESSED/decision_simulator.json`, `00_PROCESSED/sensors_alerts_items.json` | Generated outputs of `--write` / `--export`. |

## Test evidence (exact)
- **Sensor selftest:** exit 0 — `devices 8 (8 sensor types)`, `readings 12`, `active alerts 4 (HIGH=2 MED=2 LOW=0)`, top alert `Garage opened - 5:13 AM`. `--json` emits all 4 alerts with lat/lon.
- **Simulator selftest:** exit 0 — `SELFTEST PASSED`, 3 scenarios: flip 1mo +146 / 1yr +1,756 / 5yr +8,802; FHA 1mo −4,541 / 1yr +6,692 / 5yr +12,483; debt 1mo −198 / 1yr −2,564 / 5yr −18,628; 3 ranked items.
- **Full suite:** `33 passed in 5.10s` (`pytest tests/ -q`, feed-dash venv; socket blocked module-wide so no outbound call can hide). Breakdown: ingest validation 6, alert boundaries 7 (incl. lt/gt/change_to at the exact boundary), simulator math 3, exit-code regression 3, learning 3, dashboard 3, first-run kit 2, feed-writer mapping 2, originals-untouched 1, plus module fixtures.
- **Simulator math vs hand-computed fixtures (independent plain-float recomputation, no sympy):** flip {146.31, 1756.50, 8801.56}; FHA {−4540.94, 6692.15, 12482.89}; debt {−198.15, −2563.50, −18627.76} — simulator output matches to ±0.05 on every horizon, and matches the plain-float recomputation to the same tolerance.
- **Exit-code regression:** selftest with sample data removed exits **1** with `[FAIL] missing sample data`; with restored data exits **0** (`SELFTEST PASSED`).
- **Learning recalibrate (synthetic only):** 4 synthetic closed outcomes (roi dim tracking realized ROI, all other dims neutral 50) → roi weight **0.44 → 0.4615** (documented direction: dimensions whose favorable value tracked good outcomes gain weight), weights re-normalized to sum 1.0; outcomes log **byte-identical** before/after recalibrate (append-only preserved); report written (`Closed outcomes used: 4`). Recalibrate with <3 closed outcomes refuses without writing weights. Workspace `learning.py stats` → `Outcomes log: 0 total`; no `outcomes_log.jsonl` exists in the workspace — no real outcome invented.
- **Network kit:** `list` shows both SAMPLE users; `whoami` clean (no password fields); `can` matrix: owner ALLOW god_mode for `create_watchlists`/`raw_fs`, family DENY both + DENY unknown action; audit log 2 entries (`create_user` ×2); re-run idempotent (created=none, audit still 2).
- **Dashboard:** renders with empty engines (`No users`, no crash); renders against real engines with both SAMPLE users; a marker file planted in `sample_owner`'s private workspace documents does **not** appear in the HTML and no workspace path leaks; feed link-out present; `--selftest` renders a 3,648+ byte preview (verified >3,000 bytes).
- **Feed round-trip (scratch instance, port 8102):** 7/7 — 4 sensor + 3 simulator records posted (200) and read back unchanged in meaning; sensor records carry lat/lon + the firing rule + SAMPLE warning (4/4); simulator records carry the ANALYSIS ONLY warning **verbatim** in evidence, risk_notes, and provenance.warning (3/3), and `est_value == 1yr delta` (3/3); unauthenticated POST → **401**; re-post → duplicates (4+3), **0 conflicts**. Run twice, passed twice. Service terminated; no uvicorn process left running; nothing deployed.

## The exit-code fix (Task 2) — finding, not a code change
The brief states the simulator selftest "reports [FAIL] yet exits 0". **That does not reproduce in this recovered copy.** Verified before any modification, on the recovered original: `--selftest` with missing sample data prints `[FAIL] missing sample data: ...` and exits **1**. I audited every `[FAIL]` path in `selftest()` (sympy import, missing data, <3 scenarios, simulate exception, missing horizon/field, empty/bad items) — all return 1 or set `ok=False` → return 1. The regression test now locks this behavior (missing → 1, restored → 0), so the gate is proven rather than assumed. No fix was needed; nothing in the simulator's control flow was changed.

## Surprises / observations
1. **Simulator `--write` Windows path (fixed, see above):** the original hard-codes a `C:\Users\chamg\...` path. On Linux it silently creates a backslash-named directory under the CWD. The build copy now resolves to the workspace `00_PROCESSED`. The recovered original was not touched.
2. **No numeric range check in sensor ingest (finding):** `validate_reading` validates schema + value *type* only. An out-of-range *number* (e.g. temp_f 999) is accepted by the recovered code's design; only values outside the accepted type domain (None/list/dict) are rejected. The test asserts the rejection behavior that actually exists and documents this rather than pretending a range test passed. Adding a range rule would be new behavior, not a restoration — left for a future brief if Airam wants it.
3. **`learning.py cmd_record` rewrites the log (pre-existing quirk, out of scope):** `record` updates a row by rewriting the whole file. The *recalibrate* path — the one this brief tests — never writes the log (proven byte-identical). The GPT gate "append-only outcomes" holds for recalibrate; `record`'s rewrite is historical-module behavior, flagged here, not changed.
4. **venv gap:** the feed-dash venv (pytest) has no sympy, while system python3 has sympy 1.12. Simulator tests run via `tests/sim_driver.py` under `/usr/bin/python3`; everything else runs in the venv. No packages were installed and no shared venv was modified.
5. **Untracked `04_INTELLIGENCE/osint/out/` in the recovered clone** (created 2026-11-17 23:39, during this run window, by parallel pipeline work — not this build; outside the modules this brief touches). The untouched-check is therefore scoped to the four trees this build copied; it is clean. The osint/out directory was left alone.
6. `/tmp/os_modules_orig.md5` (checksums taken at run start) did not survive between shell invocations — `/tmp` is not stable across exec calls here. The scoped `git status` check is the durable evidence instead.
7. **No ports opened, no real users created, no deployment, no spending, no account changes.** Feed service ran only on 127.0.0.1:8102 with a scratch data dir and a per-run generated token; terminated after each round-trip run.

## GPT QA gates (all 7, restated as acceptance checks)
1. Missing SAMPLE device/scenario fixtures authored (Task 1) — done, selftests exit 0.
2. Sensor ingest validation + alert boundaries tested (Task 4) — 13 tests, all pass.
3. Simulator `[FAIL]` exits non-zero (Task 2) — proven by regression test (missing → 1); no bug present in this copy.
4. Isolated synthetic users only (Task 3) — `sample_owner`/`sample_family` only; passwords generated, never stored.
5. No cross-user dashboard leaks (Task 4) — marker test passes.
6. Append-only outcomes + null `actual_roi` until a real outcome is logged — recalibrate leaves log byte-identical; workspace has 0 outcomes.
7. ANALYSIS ONLY feed provenance on every simulator record (Task 5) — verbatim in 3/3 records, 3 fields each.

## How to re-verify
```
cd ~/workspace/pineapple/builds/os-modules
python3 09_SENSORS/sensor_ingest.py --selftest        # exit 0
/usr/bin/python3 06_DECISION/simulator/simulator.py --selftest  # exit 0
python3 scripts/first_run_kit.py                      # idempotent, created=none
python3 06_DECISION/learning.py stats                # Outcomes log: 0 total
~/workspace/pineapple/builds/feed-dash/.venv/bin/python -m pytest tests/ -q  # 33 passed
python3 verify_feed_roundtrip.py                      # ROUND-TRIP PASSED 7/7
git -C ~/workspace/pineapple/recovered/pineapple-os status --porcelain -- 09_SENSORS 07_NETWORK 06_DECISION _lib  # clean
```
