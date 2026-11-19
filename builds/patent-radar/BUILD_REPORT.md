# BUILD REPORT — Patent Radar (BUILD-20261117-001)
Built 2026-11-17 by Everest in `~/workspace/pineapple/builds/patent-radar/`
(isolated copy; recovered originals in `~/workspace/pineapple/recovered/` untouched).

## What was built
- **Task 1 — sample dataset restored.** `data/sample_patents.json`: 10 synthetic
  records (clearly marked SAMPLE; patent numbers are `US-TEST-######`
  placeholders, not real patents), all 3 statuses, all 4 difficulty levels,
  5× `printable_3d: true`. `_meta` documents the US term rule and that the
  numbers are illustrative.
- **Task 2 — live adapter.** `patent_radar_live.py` (stdlib only): queries the
  PatentsView PatentSearch API by CPC + grant date, computes status itself
  (filing + 20y; "expiring" ≤ 24 months), maps onto the contract, writes
  `data/live_patents.json` with full provenance (`_meta`: source URL,
  retrieved_at UTC, jurisdiction, status_method, uncertainty, counts,
  rejected list, defaults applied). API key from env var only. Supports
  `--fixture` (offline), `--dry-run`, atomic idempotent writes
  (temp file + `os.replace`), `PATENT_RADAR_OFFLINE=1` fetch refusal.
- **Minimal module patch (build copy only).** `patent_radar.py`: `PATENT_RADAR_DATA`
  env switch (sample file stays the default); `data_status` read from
  `_meta` instead of hardcoded `"sample"`; every idea now carries
  `review_required: true` + `review_reason` and passes through
  `status_method` / `status_uncertainty` / `jurisdiction`. No scoring or
  `items()` contract change. Full diff vs. the recovered original is in
  the run log; behaviour on sample data is identical.
- **Tests.** `tests/test_patent_radar.py` (26 tests, stdlib unittest) +
  `tests/fixtures/patentsview_response.json` (9-record recorded-shape response).

## GPT review patches applied (RESULT-BUILD-20261117-001-GPT)
Accepted and implemented: negative tests (missing keys, invalid dates,
duplicate IDs, unknown statuses, non-US jurisdictions, empty dataset,
corrupt JSON); provenance (versioned raw→normalized, source URL,
retrieved_at, jurisdiction, status_method, uncertainty); REVIEW_REQUIRED
state (uncertain ⇒ REVIEW_REQUIRED, never "expired"; all ideas carry it);
filing+20y labeled provisional; scores labeled heuristics, never legal
clearance; atomic writes + dry-run; no outbound call in offline tests;
method × place routing followed (CODE × cloud for the pull, BROWSER-AGENT
spot checks for legal status, BULK FILE for fee events).
Accepted as wording correction: the brief's "engine has never been run"
now reads "never been run here / on the recovered copy" — the missing
sample file proves startup failure on that path only.
Rejected: nothing. GPT's "do not overwrite recovered original" was already
a pipeline rule and was complied with (build is an isolated copy).
GPT's sequencing (feed first) was already followed — Feed+Dash is VERIFIED.

## Acceptance evidence (all run 2026-11-17, this workspace)
- Task 1: `python patent_radar.py --selftest` → exit 0, "SELFTEST OK",
  10 patents loaded, 10 ideas, top idea [100.0] drip-irrigation emitter;
  normal run prints the ranked table and writes `output/ideas.json`.
- Task 2 (offline, fixture): adapter run → `data/live_patents.json`,
  fetched 9 / included 6 / rejected 3 (1 in-force >24mo out, 1 duplicate,
  1 missing patent_number); `PATENT_RADAR_DATA=.../live_patents.json
  python patent_radar.py --selftest` → exit 0, 6 ideas, data status LIVE;
  every live idea carries `data_status: "live"` and `review_required: true`.
- Full suite: `python3 -m unittest discover -s tests` → **26 tests, OK**
  (one failure found and fixed during the run: per-record provenance
  hardcoded the legacy URL; now uses the caller's source URL).
- Dry-run wrote nothing; corrupt fixture failed cleanly with no output file;
  empty fixture refused an empty write; no temp files left after writes.

## BLOCKER — live wiring cannot be verified (external, not a code failure)
**RESOLVED 2026-11-17 evening — see "Live wiring (ODP)" below.** The ODP
key was obtained and the ODP search endpoint is wired and verified live.
The text below is the historical record of the blocker as it stood.

The legacy PatentsView PatentSearch API is **retired**. Verified three ways
2026-11-17: (1) POSTs from this VM get connection resets / empty replies
(HTTP 000); (2) the docs host `search.patentsview.org` is NXDOMAIN in the
browser; (3) `patentsview.org` redirects to the USPTO Open Data Portal
transition guide (`data.uspto.gov/support/transition-guide/patentsview`):
legacy PatentsView migrates to ODP from 2026-03-20, the PatentSearch API
has "temporary interruptions" with **no estimated reintroduction date**,
old API keys are incompatible with ODP, and no search endpoint exists in
the ODP API list yet. ODP APIs need an ODP API key, which needs a
USPTO.gov account + MFA. **That is a HUMAN STEP / account action for
Airam** — see AWAITING_AIRAM in `PIPELINE_STATE.md`.
Fallbacks, in order: (a) ODP Bulk Datasets API once a key exists (also
key-gated); (b) BROWSER-AGENT spot checks on Google Patents / USPTO Patent
Center for individual candidates (already the brief's routing for legal
status); (c) keep the radar on synthetic fixtures + manual data until (a).

## Live wiring (ODP) — 2026-11-17 evening, adapter v1.1.0

The blocker below is RESOLVED. Airam created the USPTO.gov account,
completed MFA on his own device, and saved his ODP API key through the
secure card (connector `custom.uspto-odp`). `patent_radar_live.py --source odp`
now pulls REAL data from the USPTO Open Data Portal Patent File Wrapper API.
The key is never handled by the adapter: requests carry it via the
connector's surrogate credential exchange
(`dynamic_credentials.add_surrogate_to_request`).

**Route used:** Route A — the ODP search endpoint (no fallback needed).

**Search syntax — SOLVED.** The Getting Started example body returns
HTTP 400 because it shows `q` as an object. The working shape (verified
live 2026-11-17, HTTP 200, `count` + `patentFileWrapperDataBag`):

```json
POST https://api.uspto.gov/api/v1/patent/applications/search
{
  "q": "applicationMetaData.inventionTitle:garden",
  "filters": [{"name": "applicationMetaData.applicationTypeCode", "value": ["UTL"]},
              {"name": "applicationMetaData.applicationStatusDescriptionText",
               "value": ["Patented Case"]}],
  "rangeFilters": [{"field": "applicationMetaData.filingDate",
                    "valueFrom": "2000-01-01", "valueTo": "2006-11-16"}],
  "sort": [{"field": "applicationMetaData.filingDate", "order": "asc"}],
  "pagination": {"offset": 0, "limit": 3}
}
```

Attempts log: (1) POST with `q` as an object (docs example) → 400;
(2) POST with `q` as a field:value STRING → 200 (9,373,724 utility
records); (3) GET `?q=16123456` free-text → 200; (4) POST full shape with
filters + rangeFilters → 200 (271,753 granted utility patents filed
2001–2003); (5) status filter probe with a guessed lapse-status string →
404, resolved via a facets call to the exact status text
"Patent Expired Due to NonPayment of Maintenance Fees Under 37 CFR 1.362";
(6) design patents leaked into title searches until the
`applicationTypeCode = UTL` filter was added. ODP throttling is burst 1,
so the adapter queries sequentially.

**Status logic (ODP):** expiration = filing_date + 20 years, labeled
`filing+20y provisional` (see `ODP_STATUS_METHOD`); expiring = within
24 months; expired = past term OR maintenance-fee lapse evidenced by the
ODP application status or an `EXP.` "Expire Patent" event in eventDataBag
— for lapsed records the lapse event date is the effective expiration
shown. Ambiguous records (non-utility, missing filing date) land in the
safe "filing" bucket, REVIEW_REQUIRED as before. A title screen rejects
off-domain keyword collisions (medical/data-storage/telecom) with the
reason recorded in `_meta.rejected`.

**Live pull (2026-11-18T03:05:20Z):** 24 queries (lapsed → expiring →
expired-term across 12 title keywords: garden, planter, irrigation,
sprinkler, feeder, kitchen, storage, organizer, shower, faucet, lamp,
toolbox). Fetched 48 unique records → **included 38, rejected 10**
(all 10 by the off-domain title screen). Included mix: 31 expired
(12 with maintenance-fee lapse evidence, 19 by term), 7 expiring,
0 filing. `data/live_patents.json` `_meta` carries the full query log,
provenance, status method and uncertainty note.

**Module run against live data:** `PATENT_RADAR_DATA=data/live_patents.json
python3 patent_radar.py` → selftest OK, 38 ideas, every idea
`data_status: "live"` and `review_required: true`. Top ideas (all score
74.5 — live records share the labeled heuristic defaults: medium
manufacture profile, steady demand default, printable_3d unverified, so
scores tie until figures are reviewed; ordering within the tie is by
patent number):

1. US11064803 — KIT OF PARTS FOR A KITCHEN UNIT (lapsed 2025-08-25)
2. US11083145 — PLANTER SYSTEM (lapsed 2025-09-15)
3. US11122750 — Bottomless In-Ground Water Conservation… (lapsed 2025-10-27)
4. US11206809 — Fun pet feeder (lapsed 2026-02-02)
5. US11285349 — SPRINKLER SYSTEM ANTIFREEZE COMPOSITIONS AND METHODS (lapsed 2026-05-04)

**Tests:** 36/36 pass (26 pre-existing + 10 new ODP tests:
normalization, term expiry, lapse-by-status override, lapse-event dating,
in-force rejection, design→filing bucket, missing number, title screen,
recorded-fixture CLI end-to-end, offline refusal). New recorded fixture:
`tests/fixtures/odp_search_response.json` (3 real ODP records — lapsed,
expiring, expired — metaData verbatim, event bags trimmed). No live calls
in tests.

**Remaining gaps:** (a) live scores tie because demand/manufacture/
printable fields are labeled defaults — differentiating them needs
figure review per patent (human or browser-agent spot checks);
(b) PTA is available via the ODP `/adjustment` sub-endpoint but not yet
folded into the term estimate (uncertainty note covers this);
(c) a few borderline records survive the title screen (e.g. a suction
device, a fire-sprinkler for document storage) — all REVIEW_REQUIRED;
(d) the pull is a one-shot snapshot, not a schedule.

## Marketable smalls pull — 2026-11-17 (adapter v1.1.0, `--keywords`)

Second live pull, aimed at small, shippable, giftable consumer items —
the vintage-lighter class (Airam, 2026-11-17 ~21:14 CT). Keywords:
lighter, ashtray, cigar, corkscrew, keychain, flask (lapsed + expiring
queries), plus opener, cigarette, smoking, incense, candle, clip,
multitool (expired-term). Same strategy as the first pull: lapsed →
expiring → expired-term, UTL only, title screen on. Written to a
SEPARATE dataset, `data/live_patents_marketable.json` (the first pull's
`data/live_patents.json` untouched).

**Counts:** 25 queries → fetched 46 unique → **included 45, rejected 1**
(a dental record, title screen). Status mix: **41 expired (11 with
maintenance-fee lapse evidence), 4 expiring, 0 filing**. Five queries
returned zero hits — ODP answers those with HTTP 404, which the adapter
now treats as an empty result instead of aborting the pull (new test;
suite now 39/39). Module run: selftest OK, 45 ideas, all
`data_status: "live"`, all REVIEW_REQUIRED. Scores tie at 74.5 again
(heuristic defaults), so the top 8 below are a marketability curation
of the included set, not the module's tie order.

**Top 8 marketable finds** (printability/manufacturability note each):

1. **US6732741 — LIGHTER WITH CIGAR CUTTER** (expired by term
   2021-10-09). Two-in-one smoker's gift item. Housing is printable;
   cutter blade and ignition parts are commodity metal/hardware.
2. **US11344061 — Self-locking Cigar Cutting Tool** (fee-lapsed
   2026-07-06 — freshest lapse in the pull). Small hand tool; printable
   body, one metal blade. Simple manufacture.
3. **US6814081 — POCKET ASHTRAY** (expired by term 2022-10-24). Tiny
   and simple; printable shell, but a real ashtray needs a metal liner
   for heat — print the body, line it.
4. **US9955723 — COVERED ASHTRAY** (fee-lapsed 2022-06-06). Lidded
   ashtray, among the most printable items here (same metal-liner caveat).
5. **US9538784 — MULTIPURPOSE ASHTRAY HOLDER** (fee-lapsed 2021-02-15).
   Dead-simple holder, fully printable, no moving parts.
6. **US6415689 — CORKSCREW FOR A WINE STEWARD** (expired by term
   2021-04-30). Classic waiter's friend; not a print — simple stamped/
   machined metal, cheap to manufacture.
7. **US9604832 — EXTRACTION COMPONENT FOR A CORKSCREW AND A CORKSCREW**
   (fee-lapsed 2021-05-03). The worm/extraction mechanism; metal,
   simple, pairs with #6.
8. **US6843086 — MAGIC KEYCHAIN** (expired by term 2023-04-25). Novelty
   gift item, small, printable, no electronics.

**Safety-flagged (NOT in the top 8):** US6476359 — CIGAR LIGHTER WITH
THERMAL SAFETY DEVICE (expired 2021-06-21): the claims center on a
fuel/ignition safety system — higher risk to reproduce faithfully.
US7556494 — CHILD RESISTANT LIGHTER (expiring 2027-03-01): safety-
mechanism claims, and not yet expired. US6485291 (covered spark device
for a lighter) is safety-adjacent. Any lighter build still inherits
fuel/ignition risk regardless of which patent it follows.

**Borderline survivors** (title screen passed them; all REVIEW_REQUIRED):
two corkscrew *suture anchors* (medical — "corkscrew" as adjective),
cell-cultivating flask, laboratory flask holder/dispenser, iCloud-style
keychain *syncing* software, borehole "corkscrew effect" geophysics,
a lighter-than-air hydrogen system ("lighter" collision), an industrial
candle filter element, an agricultural furrow opener, a hair clip, and
telecom/belt clips. The screen's term list can grow from these.

**Adapter changes this pull:** `_TITLE_DOMAIN` gained the marketable
keyword labels (smoking accessories, bar/kitchen smalls, home/fragrance,
personal gear) so CPC-unmapped classes (e.g. F23Q lighters) no longer
fall through to "general product"; `fetch_odp` treats a zero-hit
HTTP 404 as an empty query result. +3 tests (39/39 pass).

## Vintage / golden-era pull — 2026-11-17 (adapter v1.2.0, `--profile vintage`)

Third live pull, a DESIGN hunt at Airam's direction ("vintage like
20's–80's — golden era of designs"): patents of 1920–1989 are ALL
expired by term today, so this profile does not lapse-hunt. It includes
design patents alongside utility and labels type per record.

**The headline finding is about the source, not the finds.** The ODP
Patent File Wrapper index — the only searchable ODP surface — cannot
see the golden era. Measured live 2026-11-17 before building:

- The index carries **no filing dates before 2001-01-02** (earliest in
  the whole index), so the filing-date range filters used by prior
  pulls return zero for anything pre-2001.
- Pre-1990 grants exist only as sparse **"old case" tracking records**
  (status text "Patented File - (Old Case Added for File Tracking
  Purposes)"). Grant-date counts for ALL records, no title filter:
  **1920s 0 · 1930s 0 · 1940s 0 · 1950s 0 · 1960s 35 · 1970s 1,417 ·
  1980s 18 · 1990s 0**. Total 1960–1989: 1,292 records (1,290 UTL +
  **only 2 DES** — both automobile trim strips).
- Old-case records are bibliographic-thin: grant date and title are
  reliable; filingDate is absent; `effectiveFilingDate` is a tracking
  artifact (1986-01-27 on patents granted in 1978/1979) and is
  deliberately not used; no CPC bag; abstracts spotty.
- The Bulk Datasets API (the brief's fallback route) is **not reachable
  through the registered connector**: its paths on api.uspto.gov return
  403 "Missing Authentication Token" (the gateway serves no such route),
  verified 2026-11-17 for both the product list and a known product's
  file list. A true 1920s–80s catalog would need the bulk grant
  backfiles (full-text XML exists only from 1976) — a bulk-file mining
  project, not a search pull. Flagged for the parent/Airam; this pull
  delivers what the search index actually holds.

**Mechanics:** era is keyed to **grant date** 1920–1989 (the only
reliable date on these records). The pull pages through EVERY old-case
record in range (28 queries; coverage check: index said 1,290 UTL,
sweep collected 1,292 unique incl. the 2 DES) and screens titles locally
against vintage consumer-product categories. Status for every kept
record: `expired`, with `status_method` = **"term (vintage, pre-1990
filing)"** and a per-record `term_basis`: filing+20y (utility) /
filing+14y (design) when a filing date is on record, else **grant+17y
(utility — the pre-1995 term ran 17 years from grant) / grant+14y
(design)**. Records with no usable date or an exotic type land in the
safe "filing" bucket (none occurred). All records REVIEW_REQUIRED.

**Screen lesson (fixed mid-pull):** the first sweep kept 118 records,
but substring keyword matching was collision-riddled — "lamp" fired on
industrial CLAMPs, "table" on STABLE and TABLETS (two pharmaceutical
titles), "iron" on alloy chemistry. `vintage_category` now matches on
**word boundaries** (+1 test). Kept set dropped 118 → **69**, all
genuine title-level category matches. Residual collisions remain and
are named, not hidden: ductile-iron alloy papers and iron-stain
chemistry (standalone word "iron"), one cigarette-pack *factory
machine*, sewing-machine electronics, TV/radio *circuit* patents
(the screen keeps product classes, not just housings), two camera-tube
records, and a "CLOCK GENERATOR" (an electronics pun). By curation,
roughly 30 of the 69 are genuine consumer-product patents.

**Counts:** swept 1,292 → category-kept 69 → **included 69, rejected
0**. Mix by grant decade: **1970s 68, 1980s 1** (nothing earlier
survives the screen — the index's 35 1960s records are all
industrial/electronics). Mix by type: **utility 69, design 0** — the
index's only 2 design records are auto trim strips whose titles name
no category, and the one D-numbered record the loose screen caught
was a surgical clamp. **Design patents, the heart of the ask, are
effectively absent from this source.** Module run: selftest OK,
69 ideas, all `data_status: "live"`, all REVIEW_REQUIRED, scores tie
at 74.5 (heuristic defaults), so the top 12 below are a design/making
curation, not the tie order. Decades below are GRANT decades (filing
dates are not on these records).

**Top 12 vintage finds** (number — title — type — grant decade — why /
how to make it):

1. **US4080530 — EQUAPOISED LAMP AND NEW COUNTERBALANCED ARM
   ASSEMBLIES** (utility, 1970s, granted 1978). The balanced-arm desk
   lamp — the Anglepoise-style mechanism that defined mid-century
   desks. Springs, arms, pivots: metal fab, printed joints possible.
2. **US4076244 — PLAYING PIECE FOR TABLE SOCCER** (utility, 1970s).
   The foosball man. Directly 3D-printable; sell as replacement /
   custom players.
3. **US4008893 — SIMULATED BOWLING GAME** (utility, 1970s). Tabletop
   bowling game; printable parts + simple pin mechanics.
4. **US4224761 — TOY FISHING PLAY UNIT** (utility, 1980s). The
   magnetic fishing game; print + magnets + simple gearing.
5. **US3891229 — TRAVEL CHAIR** (utility, 1970s). Folding travel
   chair; tube-and-fabric fabrication.
6. **US4013258 — CHAIR CONTROL FOR TILTABLE CHAIRS** (utility,
   1970s). The tilt mechanism under every office chair since; stamped
   / cast metal fab.
7. **US3806217 — SEWING MACHINE CABINET** (utility, 1970s). Furniture
   cabinet that folds a sewing machine away; wood fab, very much a
   vintage-furniture reproduction candidate.
8. **US3772974 — SINGLE-LENS REFLEX CAMERA WITH AN AUTOMATIC APERTURE
   CONTROL DEVICE** (utility, 1970s). Peak film-era SLR mechanism;
   precision fab — ambitious, better as a parts/donor study.
9. **US3839725 — CAMERA RANGEFINDING AND FOCUSING DEVICE** (utility,
   1970s). Rangefinder mechanism; precision fab, same caveat.
10. **US3869005 — VALUE COMPUTING SCALE** (utility, 1970s). The
    mechanical price-computing deli scale — a great retro object;
    metal fab.
11. **US3965510 — COMBINATION DRILLING AND WRENCHING TOOL** (utility,
    1970s). Multi hand tool; straightforward metal fab.
12. **US4029316 — GAME BALL** (utility, 1970s). Ball design from the
    era of inventive sports goods; printable molds / casting.

**Adapter changes this pull:** `--profile vintage` (query sweep +
`normalize_odp_vintage_record` + `VINTAGE_STATUS_METHOD` +
`vintage_category` screen with word-boundary matching); vintage title
keywords added to `_TITLE_DOMAIN`; records carry `patent_type`
("utility"/"design"), `application_type_code`, `term_basis`, and (live
path) `vintage_category`; `_meta.category_screen` records the sweep
counts and every screened-out patent number. +9 tests (**48/48 pass**:
vintage utility/design/filing term bases, no-dates review bucket,
component-title screen, category screen incl. word boundaries,
paginated full-sweep fetch, fixture CLI end-to-end). New fixture:
`tests/fixtures/odp_vintage_response.json` (2 records with fields as
observed live + 1 synthetic-shaped wrapper, labeled as such in the
test docstring).

## Files
- `patent_radar.py` — patched build copy (original untouched)
- `README_UPSTREAM.md` — recovered README, copied for reference
- `patent_radar_live.py` — Task 2 adapter, v1.2.0 (ODP live wiring + vintage profile)
- `data/sample_patents.json` — Task 1 fixture (10 records)
- `data/live_patents.json` — REAL ODP pull, 2026-11-17 (38 records)
- `data/live_patents_marketable.json` — REAL ODP pull, marketable smalls, 2026-11-17 (45 records)
- `data/live_patents_vintage.json` — REAL ODP pull, vintage old-case sweep, 2026-11-17 (69 records)
- `output/ideas.json` — last run output
- `tests/test_patent_radar.py` (48 tests), `tests/fixtures/patentsview_response.json`,
  `tests/fixtures/odp_search_response.json` (recorded live ODP response),
  `tests/fixtures/odp_vintage_response.json` (vintage old-case response)
