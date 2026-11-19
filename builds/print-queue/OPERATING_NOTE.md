# Operating Note — 3D Print Business Queue (v1)

The queue is two generated files in this folder: `queue.json` (machine-readable, the source of truth) and `PRINT_QUEUE.md` (the human artifact). Both are written by `build_queue.py` from the files under `inputs/`. **Never hand-edit the outputs** — edit an input and re-run the builder.

## How the queue refreshes (manual — there is no cron)

There is **no cron, schedule, or automation** for this queue. It refreshes only when someone runs it by hand:

```bash
cd ~/workspace/pineapple/builds/print-queue
python3 build_queue.py
python3 -m unittest discover -s tests   # offline test suite
```

Refresh triggers worth acting on:

- **After a Patent Radar pull / deep check** — add or update winners in `inputs/patent_winners.json` (grades, make route, one-line market evidence, per-item brand-rule note).
- **After a Feed batch** — seed `inputs/feed_candidates.json` only with trend-scraper records that are genuinely sellable (`sellable: true` on a verbatim licence that affirmatively permits commercial use). Licence unknown means `sellable: false` — that record does not enter the queue, ever. The schema is documented inside that file.
- **After a filament change** (new spool, a colour runs out, gold silk arrives) — update `inputs/filament_inventory.json`, including its `snapshot_date`, and re-run. Fit grades are computed from this snapshot, so a stale snapshot means stale rankings.
- **After a project state change** (e.g. the siren caliper checklist comes back) — update `inputs/projects.json`.

Output is deterministic: the same inputs produce the same bytes apart from the `generated_at_utc` timestamp.

## How Airam adds a candidate by hand

1. Pick the right input file: a patent find goes in `inputs/patent_winners.json`, a sellable Feed model in `inputs/feed_candidates.json`, an own project in `inputs/projects.json`. (A truly one-off manual idea can be added to `patent_winners.json`-style shape in any of them — ask Everest to place it, or copy an existing entry and change every field.)
2. Copy an existing entry and fill in, honestly:
   - `market_grade` (H/M/L) **with** a one-line `market_evidence` string — real observed prices/listings/demand, or say plainly that none was found and grade it L. The builder rejects a missing or empty evidence line.
   - `ease_grade` (H/M/L) and `make_route` — keep the honest route label: if it needs electronics or metal work it is `RE-HOUSE` or `METAL FAB`, not `PRINT`.
   - `assigned_filament_id` (one of the ids in `filament_inventory.json`), `size_class`, `use_context` (indoor/outdoor), `colour_match`, `material_suitability`, and a `fit_context` sentence. Fit is **computed** from these — you do not type a fit grade.
   - `est_filament_g`: a positive number if genuinely known, otherwise `null`. **Never 0** — the builder rejects 0.
   - `next_action`: `MODEL`, `PRINT`, `LIST`, or `WAITING-ON-AIRAM` (with a `blocker` sentence saying exactly what is being waited on).
   - For patents: the `brand_note` — which living brand names must stay off the product and the listing. The cross-cutting rule from the deep check: no living brand names anywhere, on product or in listing copy.
3. Run the builder. Validation failures name the entry and the problem (unknown grade, missing evidence, unknown filament, blocklisted patent). Fix the input, not the code's gate.

## What the scores mean — and don't mean

- Score = **market points × ease points × filament-fit points**, with H=3, M=2, L=1. All three factor grades and points are stored next to every score in `queue.json`, and shown as Market/Ease/Fit in `PRINT_QUEUE.md`.
- Ties break by market evidence first, then by source-track order (patent → siren → feed).
- The score is a **prioritization heuristic, not a profit prediction**. It says "look at this first," not "this will make money." It knows nothing about print time, failure rate, shipping from Roma, TX, listing fees, or your hourly rate — a score-27 item can still be a bad business and a score-4 item a fun afternoon.
- Grades are only as good as the evidence lines behind them. Market grades come from the Patent Radar deep check (observed listings) or, for Feed candidates, from whatever evidence the seeding record carries. If the evidence line is thin, treat the rank as thin too.
- Filament fit is a heuristic against a dated snapshot: colour/material match raises it; PLA on an outdoor piece is flagged a poor fit (PLA softens ~60 °C in Roma sun); a large item on the scarce gold silk stock scores fit L; poor real-world material suitability (e.g. PLA next to ash/heat) scores L.

## Hard gates (enforced by the builder + tests, not by convention)

- Patents with an AVOID verdict in the deep check, and the one commercially-dead item, are blocklisted in `build_queue.py` and **never enter the queue** — the loader rejects them if they ever appear in an input.
- A record with `next_action: WAITING-ON-AIRAM` renders only in the "Waiting on Airam" section of `PRINT_QUEUE.md`. It cannot take an actionable rank, no matter its score.
- A project entry can never be ranked `PRINT` in v1.

## What v1 deliberately does not do

- **No printer link.** Nothing here touches the Bambu P1S, any slicer, or Airam's LAN. Sending a job to the printer is a **future, separate, local step that requires Airam's own approval** (Airam present) before it is built.
- No listings are created, no prices are posted, nothing is bought, and no seller or third party is contacted.
- No scheduling of any kind. If a recurring refresh is ever wanted, it needs Airam's separate approval first.
