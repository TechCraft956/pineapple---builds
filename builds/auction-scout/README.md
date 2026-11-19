# Auction & Surplus Scout v1

Watches public surplus / government auction sources in Texas and
reports EVERY lot pulled — nothing is filtered by category, distance,
or missing fields. Each lot is normalized into a Deal-Scout-shaped
find with distance from Roma, TX 78584, current bid, and closing
time, tagged with its track(s) — RESALE, FOR YOU (personal),
PROJECT ENABLER, COOL FIND — and ranked deal-first within its lead
track: category fit (vehicles → trailers → equipment → generators →
tools → other), then distance, then closing soonest.

Public listings only. No accounts, no logins, no bids, no seller
contact. Python stdlib only. This build writes only inside its own
workspace and does not touch Deal Scout.

## Layout

- `sources.json` — source registry (data, not code): entry points,
  method (CODE | BROWSER-AGENT), category coverage, Texas filtering,
  status WIRED | NOT WIRED + reason + observed evidence.
- `src/auction_scout.py` — fetchers, parsers, normalizer, haversine
  distance, dedupe/store, digest renderer, NOT WIRED stubs.
- `scripts/live_smoke.py` — live run: wired pulls + one probe per stub,
  merges into `finds.json`, renders `FINDS.md`.
- `tests/` — offline fixture tests (recorded live responses).
- `cache/` — raw responses from live runs, each with a `.meta.json`
  sidecar (URL, method, HTTP status, `retrieved_at_utc`, bytes).
- `finds.json` / `FINDS.md` — the digest. Every digest carries the
  warning: *current bid is not a price — auctions move at close; verify
  lot, premium, taxes and removal terms on the source before acting.*

## Run

```bash
python3 scripts/live_smoke.py            # live pulls, updates finds.json + FINDS.md
python3 -m unittest discover -s tests    # offline suite, no network
```

## Source status (2026-11-17)

| Source | Status | Notes |
|---|---|---|
| Public Surplus | WIRED | Server-rendered search + detail HTML over plain HTTP |
| GSA Auctions (PPMS) | WIRED | Public search API behind gsaauctions.gov (anonymous POST) |
| GovPlanet | NOT WIRED | Anti-bot wall (HTTP 202, empty body); BROWSER-AGENT is the next step |
| Texas state surplus (TFC) | NOT WIRED | No TFC lot feed; legacy URL is a redirect stub, new site returns 403 to plain clients |

See `BUILD_REPORT.md` for per-source evidence, sample lots, test
counts, and differences from the build brief.
