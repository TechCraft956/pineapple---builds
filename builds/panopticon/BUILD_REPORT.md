# BUILD REPORT — Panopticon v1.1 (FRESH BUILD)
Built by Everest, 2026-11-17 (bridge task BUILD-20261118-001); v1.1 gates
verified + live-smoked 2026-11-18 ~05:58Z (this update). Isolated
workspace: `~/workspace/pineapple/builds/panopticon/`. Recovered originals
untouched; nothing deployed; no schedule created.

## v1.1 — GPT acceptance clarifications, gate by gate
GPT's static QA of the brief (bridge RESULTS row 44,
RESULT-BUILD-20261118-001-GPT, 2026-11-18T05:25Z) returned 7 required
acceptance clarifications. Audit of the tree on 2026-11-18 found all 7
already implemented as code gates (acceptance tests 7–12 in the brief);
this run verified each gate against the code, ran the full suite, and
live-smoked both runners. Status per gate:

1. **Subject-purpose restriction — IMPLEMENTED.** Planner refuses a
   username plan without a documented legitimate purpose
   (`PurposeRequiredError`); the username runner and the CLI refuse too.
   No cross-site private-person profile path exists.
2. **HTTP 200 ≠ presence proof — IMPLEMENTED.** 200 + confirming body
   marker for the queried username → FOUND (VERIFIED); 200 + absent /
   soft-404 marker → NOT_FOUND; bare 200 → CANDIDATE (REPORTED tier);
   403/429/5xx/transport → UNKNOWN, never guessed. A marker naming a
   different username does not confirm (false-identity guard). Markers
   verified live for GitHub/GitLab/Twitch/Hacker News/Keybase;
   markerless sites (Reddit, YouTube, Medium, Dev.to, Codeberg) stay
   CANDIDATE on a bare 200 by design.
3. **ToS/robots + Nominatim policy — IMPLEMENTED.** Identifiable UA with
   contact on every request; global ≥1 req/s throttle (injectable clock);
   memory + disk cache (repeat queries make no request); ODbL attribution
   carried on every geocode finding. Username checks send the same
   identifying UA, one request per host per run.
4. **SSRF / redirect validation — IMPLEMENTED.** Redirects followed only
   to the same public host (allowlist empty by design); private /
   loopback / link-local targets refused before any socket use;
   credentials-in-URL and non-http(s) schemes refused; the validating
   handler sorts ahead of urllib's default redirect handler; usernames
   containing URL-injection characters are rejected pre-fetch.
5. **Per-field confidence + conflicts — IMPLEMENTED.** Every finding
   carries `field_confidence` (per-field confidence + retrieved_at_utc +
   source); the normalizer passes it through; the brief renders it and
   records cross-source disagreements in a Conflicts section (both
   values, both sources, no silent pick). Same-source alternatives are
   not conflicts.
6. **Ethics gate on nested fields + output — IMPLEMENTED.** The gate
   recurses into nested dicts/lists; the brief generator re-gates its
   structured input and scans the rendered text for label-shaped PII
   leaks; every brief carries the not-a-consumer-report / no-FCRA notice.
7. **Tests for the new gates — IMPLEMENTED.** Suite grew 23 → 59 tests:
   soft-404, false identity, markerless-200 CANDIDATE, purpose refusal
   (planner/runner/CLI), throttle + cache, redirect/SSRF refusals,
   nested-PII rejection, output re-gate, conflict recording,
   all-UNKNOWN brief honesty, excluded-never-planned-or-run, disk-cache
   round-trip. (59th test added ~06:01Z, after this section was first
   written — see addendum below.)

**Tests: `python3 -m unittest discover -s tests` → 59 tests, all passing**
(2026-11-18). `python3 panopticon.py selftest` → OK (36 sources).

### v1.1 live smoke (2026-11-18T05:58Z, public data only)
- **Place:** live Nominatim geocode of "Roma, Texas" (disk cache cleared
  first — a test run had cached fixture data) → "Roma, Starr County,
  Texas, United States", lat 26.4094075, lon −99.0144578, VERIFIED,
  confidence 0.90. Nominatim's representative point sits ~1 km from the
  v1 capture (26.4052451, −99.0240000); same town, current live value
  reported as-is. Output: `out/v1.1_smoke/`.
- **Username:** `torvalds` (the v1 test handle; public professional
  figure; purpose on record in the brief) across 10 sites → **4 FOUND**
  VERIFIED (GitHub, GitLab, Twitch, Keybase — marker-confirmed),
  **3 NOT_FOUND** VERIFIED (YouTube, Dev.to, Codeberg — checked-and-absent),
  **1 CANDIDATE** REPORTED (Reddit — bare 200, no marker, exactly the
  gate-2 case), **2 UNKNOWN** (Hacker News HTTP 429, Medium HTTP 403 —
  reported undetermined, never guessed). Gate 2 firing live, as designed.

### v1.1 addendum — fixes landed after the 05:58Z smoke (~06:01Z)
Three defects found while re-running the live checks after the smoke
above; all fixed in code, covered by tests, suite re-run green (59 tests):
- **Username findings dropped `http_status`.** `_finding()` defaulted
  the status to `None`; every branch now passes the real status through
  (regression test asserts 200 and 429 are recorded). Live torvalds
  re-check re-run after the fix: same verdicts, statuses now recorded
  (current `out/findings_torvalds.json`).
- **Disk cache pointed inside the package** (`panopticon/.cache/`)
  instead of the workspace root. Corrected to
  `.cache/nominatim_cache.json` at the workspace root; stray
  `panopticon/.cache/` removed.
- **The test suite polluted the real disk cache**: place tests used the
  module cache, so fixture payloads were persisted and a later live run
  could be served fixture data as a "cache hit" (caught live: a Roma
  run returned fixture coordinates flagged `from_cache`). Tests now pass
  explicit per-test cache dicts and never touch the real disk path; one
  dedicated test covers the disk round-trip against a temp dir. Live
  Roma re-check after the fix (clean cache): 26.4094075, −99.0144578,
  fresh fetch, then a repeat run served from cache — cache verified
  working, not faked.

## What was built
- **Build brief** — `~/workspace/pineapple/build-briefs/PANOPTICON_BUILD_BRIEF.md`,
  posted to the canonical AI Bridge as **BUILD-20261118-001** (QUEUE row 30,
  full brief text embedded, status QUEUED, verified by readback; MUSE STATUS
  heartbeat updated 2026-11-18T04:58:30Z).
- **Source registry** — `panopticon/sources.json`: 36 sources built from the
  OSINT4ALL catalog (people_search, username, email, phone, geoint,
  search_documents, technical, archives, generators_misc) plus the recovered
  osint module's official TX public-record sources. Every entry carries
  method (CODE/BROWSER/HUMAN), subject types, access class, and an ethics
  block (`excluded` / `privacy_sensitive` / `purpose_required`).
- **Query planner** — `panopticon/planner.py`: deterministic ordered plans;
  excluded sources never planned; purpose_required sources only with an
  explicit purpose and never as CODE steps; withheld sources are reported
  with reasons (`planner.skipped`) so gates are visible in output.
- **Ethics gate** — `panopticon/ethics.py`: rejects any record carrying
  banned PII field names (SSN/EIN/DOB/home address/personal contact/account
  fields), mirroring `osint_public.assert_record_clean`.
- **Normalizer** — findings → Pineapple feed item shape
  (title/category/source/action/est_value/risk/location/url/confidence)
  plus a provenance block (source_url, retrieved_at_utc, method,
  verification, source_id). `est_value` is null by design.
- **Brief generator** — Markdown brief with VERIFIED / REPORTED / UNKNOWN
  sections; checked-and-absent results render as VERIFIED facts, walled or
  un-run sources render under Unknown/gaps. The two are never conflated.

## What genuinely runs today
1. **Username presence runner** (`runners/username.py`) — 10 public profile
   URL patterns (GitHub, GitLab, Reddit, YouTube, Twitch, Hacker News,
   Keybase, Medium, Dev.to, Codeberg) with v1.1 marker semantics (gate 2
   above) and a documented-purpose requirement (gate 1). Latest live
   evidence: the v1.1 smoke in the section above (v1 run, 2026-11-18
   ~05:00Z, under the old status-only semantics: 9 VERIFIED / 1 UNKNOWN —
   superseded). Outputs: `out/v1.1_smoke/`, baseline in `out/v1_baseline/`.
2. **Place geocode runner** (`runners/place.py`) — OpenStreetMap Nominatim,
   no key, policy-compliant (gate 3). Latest live evidence: v1.1 smoke
   above (Roma, Texas VERIFIED, 26.4094075, −99.0144578).

## Tests
`python3 -m unittest discover -s tests` → **59 tests, all passing**
(registry integrity + category coverage, planner gate enforcement incl.
excluded-never-planned across all subject types and the purpose_required
CODE bar, purpose refusal at planner/runner/CLI, username marker semantics
incl. soft-404 + false identity + markerless CANDIDATE, Nominatim UA /
throttle / cache, redirect + SSRF validation, per-field confidence,
conflict recording, nested-PII + output re-gate, all-UNKNOWN brief
honesty, stub honesty). `python3 panopticon.py selftest` → OK
(36 sources; username plan 6 steps).

## What is stubbed (explicit NOT WIRED — raises, never fabricates)
- `wayback_cdx` runner — endpoint is no-key/CODE-able; top v2 quick win.
- Email runners — sources are key-gated (HUMAN STEP) and purpose-gated.
- Public-records runners — TX SOS / Comptroller / TDLR / TREC / TABC / UCC /
  county clerks are web-only; they arrive as BROWSER-AGENT runners in v2.
  (The recovered osint module's offline sample dossiers remain the
  reference for that contract.)
- Registry entries for maigret / sherlock / PhoneInfoga / theHarvester are
  mapped as CODE but flagged `local_tool_not_installed` — the planner lists
  them as planned-not-run; nothing pretends they executed.

## Honest limitations
- Username presence proves a profile *page* exists, not that the subject
  owns it; findings are worded accordingly.
- Suspended or JS-walled profiles can read as UNKNOWN (by design — never
  guessed); markerless sites cap at CANDIDATE no matter how clean the 200.
- The REPORTED tier is now emitted by the username runner (CANDIDATE =
  200 without a confirming marker); it remains the landing tier for v2
  browser-agent claims before confirmation.
- No feed-service writer yet: findings are files (`out/*.json`), shaped for
  the feed but not posted to it.

## Recommended v2 steps
1. Wire the Wayback CDX runner (CODE, no key) — first REPORTED/VERIFIED
   archive signal for organization/username subjects.
2. BROWSER-AGENT runner pack for the official TX public-record sources,
   reusing the osint module's documented endpoints and dossier contract.
3. Install + wrap sherlock (or maigret) behind the same finding shape to
   scale username coverage from 10 sites to hundreds.
4. Feed-service writer so briefs/findings land on the Dash (needs the
   Feed+Dash deployment decision, Airam's).
5. Place-watch mode (repeat place plans; demographics/construction deltas)
   — scheduling requires its own owner approval.
GPT's review of BUILD-20261118-001 should sharpen v1.1/v2 scope when it lands.
