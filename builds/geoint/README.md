# GEOINT / TerraRecon — build workspace (BUILD-20261117-005)

Isolated build of the recovered `pineapple-os/08_GEOINT` module. Recovered
originals were never modified (md5-verified; see BUILD_REPORT.md).
`README_ORIGINAL.md` is the recovered README, kept verbatim.

## Layout

| Path | What it is |
|---|---|
| `gis_parcels.py` | Build copy of the recovered module, with the GPT-folded hardening: unknown flood zone ⇒ HIGH (0.70); `PROCESSED_DIR` kept inside this workspace; `items()`/`export_scored()` carry the planning-signal warning + `data_source`. |
| `data/parcels.geojson` | Restored sample dataset: 12 synthetic RGV parcels (zones X/A/AE/VE, 5 zonings). |
| `00_PROCESSED/geoint_parcels_scored.geojson` | `--export` output (Leaflet-ready). |
| `adapters/` | Live county AD + FEMA NFHL adapters (stdlib only). `run_live.py` pulls bounded live parcels per county, joins FEMA zones, writes `live/`. |
| `writers/geoint_writer.py` | `items()` → Shared Feed opportunity records (`type: other`). |
| `feed-service-copy/` | Unmodified COPY of the feed service (BUILD-20261117-002) used only for the local round-trip test. Never deployed. |
| `verify_feed_roundtrip.py` | Starts the feed-service copy on 127.0.0.1:8101 (scratch data), posts sample + live parcels, GETs them back, verifies warning + data_source. |
| `tests/test_geoint.py` | 33 offline tests (socket blocked): discount boundaries, geometry validation, centroid/bbox, per-county mapping on recorded fixtures, FEMA join correctness, feed writer schema validation. |
| `fixtures/` | Recorded live responses used by the offline tests. |
| `cache/` | Raw live responses with `retrieved_at_utc` + source URL. |
| `live/` | Canonical live GeoJSON per county + `all_live.geojson` (20 parcels). |

## Run

```bash
cd ~/workspace/pineapple/builds/geoint
python3 gis_parcels.py --selftest        # exit 0; 12 parcels
python3 gis_parcels.py --json            # 12 items()
python3 gis_parcels.py --export          # writes 00_PROCESSED/
python3 -m adapters.run_live --limit 5   # live pull + FEMA join -> live/
~/workspace/pineapple/builds/feed-dash/.venv/bin/python -m pytest tests/ -q
~/workspace/pineapple/builds/feed-dash/.venv/bin/python verify_feed_roundtrip.py
```

## Safety

Every scored output and every feed record carries the planning-signal
warning: output is NEVER authoritative title, valuation, or flood
determination — verify against county AD records and FEMA NFHL before
acting. No accounts created, no spending, nothing deployed.
