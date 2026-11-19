# Feed mapping — Decision Engine brief → Shared Feed (2026-11-17)

Writer: `writers/decision_brief_writer.py` (stdlib only; `FEED_URL` /
`FEED_API_TOKEN` env). Posts the brief's top actions to `POST /api/feed/items`
as Opportunity Engine schema v0.2 records. Schema validation happens on both
ends (writer-side `jsonschema` check in the round-trip test, service-side
validation on POST).

## Field mapping

| Brief field | Feed record field | Notes |
|---|---|---|
| `title` | `title` | verbatim |
| `source` (module name / context file) | `source` | prefixed `decision_engine:` |
| `quant` (0–100) | `confidence` | `quant / 100`, clamped 0..1 |
| `quant` | `provenance.quant` | raw, for audit |
| `raw_score`, `dims` | `provenance.raw_score`, `provenance.dims`; dims also summarised in `evidence` | |
| `roi_estimate` | `provenance.roi_estimate` | **carried raw, exactly as the brief has it — null stays null, never 0.** Its units are module-defined (some modules emit dollar-ish values, e.g. 1700.0 / 127000.0), so it is never normalised and never written into `est_value`. |
| — | `est_value` = 0, `est_value_unknown` = true | No dollar realisable value exists for a ranked action; 0 is a placeholder, flagged unknown (same precedent as the radar writer). |
| — | `purchase_price` = 0 | No purchase is modelled by a ranked action. |
| `category` | `provenance.decision_category` | MONEY / ASSETS / OPPORTUNITIES / RISKS |
| `action` | `next_action` | verbatim |
| `doctrine.flags` | `evidence`, `risk_notes` | flags ride along as evidence |
| `risk` | `risk_level` | LOW→low, MED/MEDIUM→medium, HIGH→high, anything else→null |
| `stale`, `age_days` | `provenance.stale`, `risk_notes` | stale items carry the decay note |
| brief `generated` | `collected_at`, `provenance.brief_generated` | `collected_at_source` = `sweep_ran_at` |
| — | `approval_status` = `PENDING` | a recommendation needs the owner; the engine authorises nothing |
| — | `type` = `other`, `evidence_quality` = `estimate` | a ranked action is none of the resale/patent/venture/trading types |
| — | `id` / `listing_key` = `decision:<YYYYMMDD>:<nn>:<slug>` | stable per brief date + rank + title slug; re-posts dedupe on it |

## Verified round-trip (2026-11-17)

- In-process (`tests/feed_roundtrip_test.py`, 2 tests): 10 top actions mapped,
  schema-validated, POSTed to a throwaway copy of the feed service, read back
  via `GET /api/feed/opportunities` — confidence == quant/100 for all 10,
  `roi_estimate` preserved exactly (7 null, 3 numeric: 1700.0, 127000.0,
  7500.0), `est_value_unknown` true, re-POST idempotent (duplicates, no
  conflict). Unauthenticated POST rejected (401).
- Live HTTP: the same writer posted the same 10 records to a local uvicorn
  copy of the feed service (port 8123, throwaway data dir) and the GET
  read-back matched on all 10 — see BUILD_REPORT.md. The feed-dash build
  itself was not modified; its data dir was never touched.
