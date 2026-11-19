# BUILD REPORT — Auction & Surplus Scout v1
Built 2026-11-17 (live runs 2026-11-18T05:21Z and 05:22Z UTC). Python stdlib only.
Writes only inside `~/workspace/pineapple/builds/auction-scout/`. Deal Scout's
workspace, the AI Bridge sheet, and PIPELINE_STATE.md were not touched.

## Fix pass — 2026-11-18 (Airam review of the first FINDS.md)

Airam reviewed the first digest and directed: fix the layout, re-do the
sorting, and make sure no deals are being snuffed out; the scout is also
NOT resale-only. All changes below are live as of the 2026-11-18T05:56Z run.

1. **Source status moved to a bottom footnote.** The digest no longer
   leads with the long govplanet/txsurplus NOT WIRED explanations. Lots
   come first; "## Source notes" at the bottom gives each stub one short
   line (first sentence of the registry reason) and points here for the
   full evidence.
2. **Deal-first sort replaces closing-first.** The old order (closing,
   then distance) topped the report with a slipping-transmission
   Explorer 322 mi away. New order, stated explicitly in the report
   header: category fit (vehicles → trailers → equipment → generators
   → tools → other), then distance from Roma ascending (unknown
   distance last but still listed), then closing soonest.
3. **Per-lot "Resale signal: low — no retail anchor known" line removed.**
   It rendered only when a genuine signal exists (level other than
   low); v1 has no retail anchors, so the line no longer appears. The
   signal stays in the find data; no anchor is ever fabricated.
4. **No-snuff guarantee, enforced at every layer:**
   - The Public Surplus category classifier no longer drops "other"
     lots (it kept 41 of 104 raw). All 104 raw Texas lots are now kept,
     classified, and reported. (Supersedes "What differs from the
     brief" item 4 for Public Surplus.)
   - GSA now pulls ALL pages of the Texas search (3 pages, 70 of
     totalElements=70) instead of page 1 only (25). (Supersedes the
     "GSA pages 2–3 not pulled" note in Not done, below.)
   - The recently-closed list is no longer capped at 10.
   - FINDS.md now renders THIS RUN's pull (finds.json still keeps the
     deduped store), and the header states it plainly: **lots pulled
     174 · lots shown 174** on the fix-pass run (104 publicsurplus +
     70 gsa; 174 open, 0 closed at render time). Ranking and tagging
     reorder only — pulled == shown by construction, and a test pins it.
   - Public Surplus detail enrichment (8 pages/run) now goes to the
     most deal-relevant lots first (category fit, then closing);
     unenriched lots are still listed with location/distance unknown.
   - Known limit, stated honestly: each Public Surplus keyword search
     returns one server-rendered results page; no verified pagination
     endpoint exists for it, so "pulled" means what those searches
     return. The pulled-vs-shown line makes any future gap visible
     instead of silent.
5. **Track tags — the scout is not resale-only.** Every lot now carries
   `tracks` (a lot can carry several):
   - **RESALE** — category fits the flip criteria (vehicles, trailers,
     equipment, generators, tools). Category fit only: with no retail
     anchors, no margin is claimed.
   - **FOR YOU** — Airam's personal categories from the Deal Scout
     FOR YOU track: workshop tools & equipment; 3D printers &
     filament; computers & electronics; generators & power gear for
     the house; truck & trailer stuff.
   - **PROJECT ENABLER** — unlocks/feeds a known project (3D printing,
     the siren project, Pineapple compute, workshop capability:
     welder, CNC, lathe, compressor, workbench, server…).
   - **COOL FIND** — rare/interesting on its face (aircraft, vintage,
     Humvee…); no discount required. The UH-60A Blackhawk carries it.
   The report groups open lots by lead track — For You → Project
   Enablers → Cool Finds → Resale → More lots (untagged) — with all of
   a lot's tags on its line and the deal-first sort inside each track,
   so personal/project finds are not buried under resale ranking.
   Fix-pass run mix: 42 For You, 1 Cool Find, 7 Resale, 124 untagged
   (mostly office/other lots — shown, ranked last, per the no-snuff rule).
6. **Tests: 27, all passing** (was 19). New: deal-first sort (category
   beats distance/closing; distance then closing within category;
   unknown distance last but listed), track classification (9 cases +
   lead-track priority), digest structure (counts line, explicit sort
   statement, source notes at bottom, no signal-noise line, each lot
   listed once under its lead track), and fetch-layer no-snuff tests
   (Public Surplus keeps "other"; GSA paginates to totalElements) using
   monkeypatched fetches over the recorded fixtures.

## Per-source verdicts

### publicsurplus — WIRED
- Live (two runs, identical counts): 5 keyword searches (generator, trailer,
  truck, tool, equipment) against the `region=all,tx` search, all HTTP 200 —
  **104 raw Texas lots**, deduped across keywords; **41 finds** after the
  category classifier kept tools/equipment/vehicles/trailers/generators.
- Detail pages fetched for the 8 soonest-closing finds per run (city/state/ZIP,
  bid count, current price, buyer's-premium sentence, condition text).
- Sample lot (hand-checked against its cached raw detail page
  `cache/publicsurplus/publicsurplus_detail_4128069_*.html`): **2013 Ford
  Explorer (Unit #7160) - Transmission Slipping**, lot 4128069, current bid
  **$1,300.00**, **1 bid**, pick-up **Houston, TX 77029**, closes
  **2026-11-18T20:00:00Z**, 322.5 mi from Roma. Title, bid, bid count, city
  and closing all match the cached raw response.

### gsa — WIRED
- gsaauctions.gov itself is a JS shell (HTTP 200, 1,620 bytes, no listings),
  but the PPMS auction API it loads answers anonymous public requests:
  `GET /api/v1/auctions/stateCountList` reported **70 active Texas auctions**;
  `POST /api/v1/auctions?page=1&size=25` (the search-body shape the site's own
  front end builds, recovered from its JS bundle) returned page 1 — **25 finds**
  normalized; `totalElements=70` (pages 2–3 not pulled in v1).
- Sample lot: **Sikorsky UH-60A Blackhawk, SN: 79-23350**, lot 413108,
  current bid **$500,000.00**, 1 bidder, **El Paso, TX**, closes
  2026-11-19T16:00:00Z, 583.7 mi from Roma. All fields match the cached raw
  JSON (`cache/gsa/gsa_search_tx_*.json`, also the test fixture).
- Dead ends recorded: `POST /api/v1/auctions/search` timed out twice from this
  sandbox (25s, 45s) and is not used; `GET /api/v1/auction-categories` is
  HTTP 401 anonymous and is not used (categories come from title keywords,
  per the brief); page is 1-based (page=0 → HTTP 500 "Page index must not be
  less than zero").

### govplanet — NOT WIRED (stub)
- Evidence: search `GET /jsp/s/search.ips?sm=0&k=generator&mf=1` → **HTTP 202
  with a 0-byte body** (anti-bot challenge; reproduced in the second live
  probe); homepage `govplanet.com` → geo-redirect to `govplanet.eu`; one probe
  attempt had its connection closed without a response.
- Registry routes it BROWSER-AGENT as the next step; the v1 stub returns the
  reason + evidence and **zero finds, always**.

### txsurplus (Texas Facilities Commission) — NOT WIRED (stub)
- Evidence: legacy surplus URL → HTTP 200, 610 bytes, only a meta-refresh to
  `web.tfc.texas.gov`; the new site (root and surplus path) → **HTTP 403
  Access Denied** (Akamai/edgesuite) for a plain client; `surplustexas.gov`
  closed the connection without responding.
- TFC publishes no lot list of its own: per its program documents, public
  sales are the Austin State Surplus Store plus online auctions run by
  contracted third-party auctioneers. Texas state lots listed on Public
  Surplus are already covered by the publicsurplus source.

## Tests
- Offline suite: **19 tests, all passing** (`python3 -m unittest discover -s tests`),
  no network. Fixtures are the real responses recorded during this build
  (Public Surplus all-Texas grid, generator search, one lot detail page; GSA
  Texas search page 1 JSON).
- Coverage: PS grid + detail parsing, GSA parsing, 12-case category
  classification, haversine distance (Roma→Roma 0, Roma→McAllen ≈51 mi,
  unknown city → null), bid-null handling for both parsers (missing bid →
  null, never 0), dedupe/update-in-place with first/last seen, closed-lot
  split + warning label in the digest, stub behaviour (zero finds + reason
  + evidence, registry covers all 4 sources), find-contract keys,
  feed-item confidence cap (≤0.6, est_value null). The fix pass (top of
  this report) replaced the closing-then-distance sort coverage with
  deal-first sort, track, digest-structure, and no-snuff fetch tests —
  27 tests total, all passing.
- Live dedupe verified end-to-end: the second smoke run re-saw all 66 finds
  and `finds.json` stayed at **66** (update in place, `last_seen_utc` advanced).

## Output
- `finds.json`: 66 finds (41 publicsurplus + 25 gsa), each with provenance
  (source search URL + retrieved_at_utc) and first/last seen timestamps.
- `FINDS.md`: warning label on top, pulled-vs-shown counts + explicit
  sort statement, open lots grouped by lead track with the deal-first
  sort inside each track, recently-closed tail, source notes as a
  bottom footnote. (Updated by the 2026-11-18 fix pass, top of report.)
- `cache/`: every live response cached raw with a `.meta.json` sidecar.

## What differs from the brief
1. **GSA worked differently than expected.** The brief expected "structured-ish
   pages"; the HTML is an empty JS shell. It is still WIRED, via the public
   PPMS API the site itself calls — no account or token needed for search.
2. **GSA closing times carry no timezone offset** in the API (`endDate` is a
   naive local timestamp). v1 interprets them as America/Chicago and converts
   to UTC; this is an approximation (e.g. El Paso is Mountain Time) and is
   flagged here rather than hidden. Public Surplus closings come from a
   source-provided epoch timestamp and are exact.
3. **Public Surplus grid cards carry state only, no city.** City/bid-count/
   premium come from detail pages, capped at the 8 soonest-closing finds per
   run to keep request volume modest; the remaining finds honestly carry
   `location: null` / "distance unknown" rather than a guessed city.
4. **Filtering differs per wired source.** Public Surplus is pulled by
   category keywords and classifier-filtered (41 of 104 raw). GSA's Texas
   search returns a mixed-category page, so page 1 is kept whole (25 finds,
   including `other`) with categories labeled — the digest stays complete for
   the largest Texas source instead of silently dropping lots.
5. **Some Public Surplus detail pages render the buyer's-premium percentage
   separately from its sentence**, so the stripped text reads "A Buyers
   Premium of will be added…" — `fees_note` stays null for those lots rather
   than quoting a broken sentence. Lots whose premium sentence is complete
   (6%, 10.5% seen live) carry it verbatim.
6. **Texas state surplus has no feed to wire** (see verdict above) — stronger
   than the brief's "verify the live channel": the channel is third-party
   auctioneers and a physical store, so the stub's reason is structural, not
   just a wall.
7. One tooling note: an early GSA probe batch hit a timed-out approval card;
   the calls that completed are the ones cited as evidence, and no unapproved
   part was retried as-is (the working search route was found afterwards via
   the front-end bundle and run separately).

## Not done / next steps (not in v1 scope)
- GovPlanet via BROWSER-AGENT; GSA pages 2–3 (45 more Texas lots); wiring the
  digest into Deal Scout alerts (separate Airam approval, per the brief).
