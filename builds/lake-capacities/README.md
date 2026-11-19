# Lake Capacities v1

Texas reservoir levels, % of conservation capacity, and 30-day trend —
from public USGS NWIS and TWDB Water Data for Texas data, normalized
per the build brief in `~/workspace/pineapple/build-briefs/LAKE_CAPACITIES_BUILD_BRIEF.md`.
Python stdlib only; no accounts or keys.

## Layout
- `lakes.json` — registry (10 lakes; per-source ids + WIRED/NOT WIRED status)
- `src/common.py` — HTTP + raw-response cache (retrieved_at_utc + URL sidecars)
- `src/usgs_client.py` — NWIS instantaneous + 30-day daily (62614/62615/00054)
- `src/twdb_client.py` — TWDB recent-conditions.json + per-lake 30-day CSV
- `src/normalize.py` — lake records, % rule, trend, cross-source confidence,
  `record_to_item()` (category "PLACES", est_value null)
- `src/render.py` — Markdown brief renderer (offline, from records)
- `src/pipeline.py` — registry + clients → records (live or `--offline` cache)
- `scripts/live_smoke.py` — live Falcon + Amistad pull (evidence in `evidence/`)
- `scripts/build_brief.py` — all lakes → `output/records.json` + `output/LAKE_BRIEF.md`
- `tests/` — offline fixture tests (no network)
- `cache/` — raw cached responses with `.meta.json` provenance sidecars
- `evidence/discovery_log.md` — how each endpoint/id was verified live

## Run
```bash
python3 -m unittest discover -s tests -v     # offline tests
python3 scripts/live_smoke.py                # live Falcon + Amistad
python3 scripts/build_brief.py               # live, all lakes
python3 scripts/build_brief.py --offline     # re-render from cache
```

## The % rule
`pct_conservation` is computed only when the storage counted against
conservation capacity **and** the conservation capacity are both present
and dated. Elevation alone is never a percentage (renders "% unknown").
For Falcon, Amistad and Toledo Bend, TWDB's conservation figures are
the Texas share of a shared pool; total storage/capacity are kept
alongside in each record.
