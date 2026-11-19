# 3D Trend Scraper — sellable-prints feeder (BUILD-20261117-003)

Scouts 3D-printing trend data and turns it into ranked, sellable-print
leads: what is popular, what is rising, and — critically — what can
legally be printed and sold (licence) and printed on the filament on hand
(white/black Overture PLA+ Fast, clear PETG, a little gold silk PLA).
Upstream feeder for the sellable-prints Feed track; writes into the
shared feed (brief #2).

Built 2026-11-17 in this isolated workspace from the recovered
`3d-trend-scraper` repo (originals untouched). See `BUILD_REPORT.md`.

## Sources (no phantom sources)

| Source | State |
| --- | --- |
| Thingiverse | Search/category pages with counts; licence per model page. Live re-verification pending (403 on 2026-11-17) — see SELECTORS.md. GUI paste fallback works today. |
| Printables | NEW scraper: search + model pages, same record shape. Search + title/author/rating verified live 2026-11-17. |
| Google Trends | pytrends, terms refreshed to sellable-prints categories (miniatures, organizers, tools, household, toys/games). 429 backoff kept; CSV export fallback. |
| GrabCAD | Login DEFERRED — no live pull, no credentials attempted. Code path ready for the owner's login step. |
| Reddit | REMOVED — the README claimed it; no Reddit scraper ever existed. Claim deleted, not implemented. |

No "AI trend analysis" is claimed: trend analysis is the MinMaxScaler
spike check, as in the recovered code.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.run_scrapers --help   # exits 0, no browser, no network
.venv/bin/python -m src.run_scrapers           # offline fixture run -> data/trend_records.json
.venv/bin/python -m pytest tests/ -q           # offline tests (live test is opt-in: --live)
```

Live (opt-in only): `--live --source thingiverse --browser` (Selenium,
headless) or `--live --source printables`. GUI paste fallback:
`.venv/bin/python -m src.gui`, or headless `--paste-file <file>`.

Feed round-trip: `.venv/bin/python verify_feed_roundtrip.py` (starts the
real feed service on a scratch data dir; needs FEED_API_TOKEN only when
posting outside the script — the script uses a throwaway token).

## The trend record (one schema, every source)

`source, title, url, author, licence, likes, downloads, remixes,
collected_at_utc, spike, filament_fit, sellable, sellable_reason,
confidence (0–1)`.

Licence rules (hard default): unknown licence ⇒ `sellable: false`,
reason `licence: unknown`. Non-commercial ⇒ not sellable. Sellable only
when the verbatim licence, proven per model from its source page,
affirmatively permits commercial use. `filament_fit` is a heuristic,
labelled as such — never a print guarantee. Unknown counts stay `None`,
never zero.

## Layout

- `src/models.py` — record schema + validation
- `src/licensing.py` — licence/sellability classification, filament fit
- `src/scrapers/` — thingiverse, printables, google_trends, grabcad
- `src/processors/` — data_cleaner, text_extractor, paste_parser (GUI paste → records)
- `src/writers/feed_writer.py` — TrendRecord → shared-feed opportunity record
- `src/gui.py` — manual-paste fallback GUI (emits the same record)
- `src/run_scrapers.py` — runner (`--help` / `--offline` / `--live` / `--feed`)
- `tests/fixtures/` — dated HTML/CSV fixtures (see SELECTORS.md for provenance)
- `SELECTORS.md` — every selector with its verification date and status
- `BUILD_REPORT.md` — what was built, test evidence, failures/deferrals
