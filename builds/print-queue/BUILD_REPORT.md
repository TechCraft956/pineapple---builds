# BUILD REPORT — 3D Print Business Queue v1

Built 2026-11-17 (America/Chicago) in the isolated workspace `~/workspace/pineapple/builds/print-queue/`, per `~/workspace/pineapple/build-briefs/PRINT_QUEUE_BUILD_BRIEF.md`. Python standard library only. No network, no printer access, no scheduling, no listings. Nothing outside this folder was written; the AI Bridge sheet and PIPELINE_STATE.md were not touched.

## What genuinely runs

- `python3 build_queue.py` — loads the three input files + filament snapshot, validates, applies hard gates, computes scores/filament fit, writes `queue.json` + `PRINT_QUEUE.md`. End-to-end run verified repeatedly.
- `python3 -m unittest discover -s tests` — **33 tests, all passing, offline.**
- Determinism proven two ways: the test suite builds twice with a fixed timestamp and compares bytes, and the builder was run twice for real — `queue.json` and `PRINT_QUEUE.md` are byte-identical apart from the generated-at timestamp.

## Ranked top 5 (actionable)

| Rank | Item | Score | Market/Ease/Fit | Filament | Next |
|---|---|---|---|---|---|
| 1 | Foosball playing piece (1978) — US4076244 | 27 | H/H/H | Overture PLA+ Fast — black | MODEL |
| 2 | Hand telephone (1955) — Bluetooth handset re-house — USD174098 | 18 | H/M/H | Overture PLA+ Fast — black | MODEL |
| 3 | Lux wall clock (1940) — quartz re-house — USD120511 | 18 | M/H/H | Overture PLA+ Fast — white | MODEL |
| 4 | Derby alarm clock (1965) — quartz — USD201144 | 18 | M/H/H | Overture PLA+ Fast — white | MODEL |
| 5 | Technophone pocket telephone (1987) — prop — USD289896 | 18 | M/H/H | Overture PLA+ Fast — black | MODEL |

The foosball piece ranks #1 actionable at 27 (the only H/H/H), as the brief's acceptance requires. The four-way tie at 18 breaks by market grade (hand telephone H before the three M items), then by deep-check input order. Full queue: 11 actionable patent records (Top 8 + 3 runners-up), 0 feed records, 1 waiting record.

## The waiting section

The siren (PQ-SIREN-001) is present only in the "Waiting on Airam" section, `next_action: WAITING-ON-AIRAM`, with the blocker stated verbatim in both outputs: print the adcurtin parts + return the 8-item caliper checklist; D-flat depth UNKNOWN; gear ratio UNVERIFIED; **authorized powered-test RPM = 0** until the gear ratio is verified. Its recorded next step after the wait is MODEL. It can never be ranked PRINT (loader rejects a PRINT project entry; a test pins the siren's state).

## Feed-track seed verdict: EMPTY (honest, not fabricated)

Inspected `~/workspace/pineapple/builds/trend-scraper/` directly. Its verified output `data/trend_records.json` holds 28 records (20 gui_paste, 5 google_trends, 3 printables) and **every one is `sellable: false` with licence null/unknown** — the build's hard default working as designed. Its `tests/fixtures/licence_cases.json` contains licence strings that would classify as commercial, but those are unit-test fixtures for the licence classifier, not real candidates, and were **not** seeded. Result: `inputs/feed_candidates.json` ships with an empty `candidates` list, the full candidate schema documented inside the file, and this verdict recorded in it. The feed loader additionally rejects any future candidate that is not `sellable: true`, has an unknown licence, or carries an NC/ND licence.

## Hard gates — verified

- The deep check's 2 AVOID patents and the commercially-dead item are blocklisted in `build_queue.py`; the loader rejects them if they ever appear in an input (test), and a grep + test confirm none of the three numbers appears anywhere in `queue.json` or `PRINT_QUEUE.md`.
- WAITING-ON-AIRAM records render only in their own section with `rank: null` (test).
- RE-HOUSE / METAL FAB routes keep their labels (test pins the corkscrew as METAL FAB and the radio/telephone as RE-HOUSE).
- `est_filament_g` is `null` on every record (no weighed/modelled estimate exists for any item yet) and the validator rejects 0 (test).

## Tests (33, all passing)

- Scoring math on known factor triples (6 assertions incl. 27/18/9/8/1).
- Filament-fit rules: gold-silk + large ⇒ L; gold-silk + small ⇒ M (scarce cap); PLA + outdoor ⇒ L with the `pla_for_outdoor_poor_fit` flag; PETG + outdoor ⇒ not flagged; colour mismatch ⇒ M cap; poor material suitability ⇒ L.
- Hard gates: blocklist rejection (all three numbers), blocklist absence from outputs, WAITING sectioning, siren state, feed licence gates (unknown licence and not-sellable candidates both rejected).
- Input validation: unknown grade, missing evidence, empty evidence, `est_filament_g: 0`, unknown next_action, unknown filament id — all rejected.
- Queue content: counts (12 total / 11 patent / 0 feed / 1 siren), foosball #1 at 27 with H/H/H, actionable ordering, per-record factor/score consistency, route labels.
- Determinism: two builds with a fixed timestamp are byte-identical; two builds differing only in timestamp are otherwise equal.
- Renderer: every queue id appears in `PRINT_QUEUE.md` exactly once; header carries generated-at, filament snapshot date (2026-11-17) and the heuristic disclaimer; waiting section states the siren blocker.

## Differences from the brief (flagged, not silently changed)

1. **Siren STL count.** The brief says 29 STL files; the project folder actually contains 26 `.stl` files on disk (including zip-duplicate copies) and `MEASUREMENTS.md` lists 23 measured entries. The queue record uses the measured count (23 entries across the 3 designs) and the report flags the discrepancy here.
2. **Runner-up grades.** The deep check's shortlist names the 3 runners-up without grades in that section; their grades were taken from their full entries in the same document (fan H/M/M, pocket ashtray H/M/M, Lux alarm H/L/H) — faithful to the source, just sourced from the full entries rather than the shortlist.
3. **All patent items have next_action MODEL.** No CAD model exists yet for any of the 11 (the foosball piece included), so MODEL is the honest next action for each; none was labelled PRINT or LIST, since nothing is modelled, printed, or ready to list.
4. **Feed seeding.** The brief's "seed records labeled as such" wording was overridden by the task instruction: nothing qualifies as genuinely sellable, so the feed input ships empty with the schema documented, rather than seeding fixture records.

## Files written (all inside `~/workspace/pineapple/builds/print-queue/`)

- `build_queue.py` — loaders, validation, filament-fit engine, scoring, renderer, CLI (`--generated-at`, `--out-dir`).
- `inputs/patent_winners.json` — Top 8 + 3 runners-up, faithful grades/routes/evidence/brand notes.
- `inputs/feed_candidates.json` — empty candidate list + documented schema + seed verdict.
- `inputs/projects.json` — the siren entry, authored from the real project state.
- `inputs/filament_inventory.json` — 2026-11-17 snapshot (white/black Overture PLA+ Fast, clear PETG, a little gold silk PLA; Bambu P1S 256³).
- `queue.json`, `PRINT_QUEUE.md` — generated outputs.
- `OPERATING_NOTE.md` — manual refresh flow, how Airam adds a candidate, what scores mean/don't mean, explicit: no cron exists; the printer link is a future approved local step.
- `tests/test_print_queue.py` — the 33-test offline suite.
- `BUILD_REPORT.md` — this report.

## Not done / stubs

- Feed track is an intentional empty (reason above) — it fills only when a trend-scraper record ever carries a proven commercial licence.
- No gram estimates exist for any item (`est_filament_g: null` everywhere) — they arrive when items are actually modelled/sliced.
- No printer link, no cron, no listings — out of v1 scope by the brief, each needing Airam's separate approval.
