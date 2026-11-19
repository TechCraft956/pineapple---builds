# Stale-context rule (Decision Engine build, 2026-11-17)

## The rule

A context item whose source record is older than **30 days** is **decayed, not
dropped**:

- `quant` is reduced by a flat **10 points** (floored at 0).
- The item is flagged `stale: true` with `age_days` recorded.
- A `STALE: source is N days old (rule: >30 days decays -10 quant)` flag is
  appended to its doctrine flags, so the staleness is visible in the brief
  and in the feed record.

Fresh items (age ≤ 30 days) are untouched. Items with **no usable date** are
treated as fresh — absence of a date is not evidence of staleness.

## Why this shape

The brief's gap #7 was that freshness discipline was implicit: an old risk or
deadline could resurface at quant 55–60 forever. Dropping stale items
entirely would hide risks the owner may still need to see (e.g. a deadline
that is genuinely still open). Decaying keeps them visible but stops them
competing at full strength with current items.

## Where it lives

- `decision_engine.py`: `STALE_AFTER_DAYS = 30`, `STALE_QUANT_DECAY = 10.0`,
  `apply_staleness(item, date_modified_iso, now=None)`; applied to every
  item built by `items_from_context()` using the record's `date_modified`
  (falling back to `date_added`).
- The source date comes from the index record written by intake/scanner
  (file mtime), so the rule measures the age of the underlying source, not
  of the brief run.

## Tests

`tests/test_decision_engine.py::TestContextDedupAndStale`:

- 45-day-old risk item: quant 55 → 45, `stale` true, `age_days` 45, STALE flag.
- 2-day-old risk item: quant unchanged at 55, no stale marker.
- Boundary: 30 days = fresh, 31 days = stale.
- Missing date = fresh, quant unchanged.
