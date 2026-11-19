# Selector verification log — 3D Trend Scraper (BUILD-20261117-003)

Every selector recorded with its verification date, per the GPT-folded
hardening (2026-11-17). Statuses: VERIFIED (live, dated) / RETAINED
(from recovered code + recorded data, live re-check pending) /
PROVISIONAL (written, not yet live-confirmed) / NOT VERIFIED.

## Thingiverse — 2026-11-17

| Selector | Status | Evidence |
| --- | --- | --- |
| Search page fetch | BLOCKED | `browser.open` on `thingiverse.com/search?q=miniature…` returned HTTP 403 (anti-bot) on 2026-11-17. Not retried. |
| `div.ThingCard__card` | RETAINED | The recovered scraper used it against the live homepage; card text structure (author, likes, downloads, remixes, title) verified against the recorded real paste `data/trends_input.txt` (2025-01-31 recording, re-checked 2026-11-17). |
| `h3.ThingCard__title` | RETAINED | Same as above. |
| `a[href*='/thing:']` (model link) | RETAINED | Same as above; URL shape `thingiverse.com/thing:<id>` confirmed in the recording. |
| Licence on model page ("License: …") | PROVISIONAL | Extraction is regex over page text for CC strings; no live model page was fetchable on 2026-11-17. Licence is proven per model, never inherited. |
| **Live re-verification** | PENDING | Needs a browser-agent run on the owner's signed-in session (brief routing: JS-heavy, anti-bot-sensitive). |

## Printables — 2026-11-17 (live text fetch)

| Selector | Status | Evidence |
| --- | --- | --- |
| `a[href^="/model/"]` on search page | VERIFIED 2026-11-17 | `printables.com/search/models?q=miniature` returned model links; first result "Honeycomb Wall Miniature Paint Holder …" at `/model/589261-…`. |
| `<title>` → "<title> by <author> \| …" | VERIFIED 2026-11-17 | Model page `/model/589261-…` title contains author `dasfrodo`. |
| `<h1>` title | VERIFIED 2026-11-17 | Same fetch: H1 holds the model title. |
| Description text | VERIFIED 2026-11-17 | Same fetch: "These are various holders for miniature / acrylic paints." |
| Rating `N/5 (R ratings, V reviews)` | VERIFIED 2026-11-17 | Same fetch: "Rating: 4.8571428571/5 (21 ratings, 32 reviews)". |
| Licence text on model page | NOT VERIFIED | Licence and likes/downloads counts are NOT in the server-rendered text fetch (client-rendered). Parser leaves them unknown (⇒ not sellable) rather than inventing them. Selenium path to confirm. |

## Google Trends — 2026-11-17

| Item | Status | Evidence |
| --- | --- | --- |
| pytrends `interest_over_time` CSV shape | VERIFIED (recorded) | `data/google_trends_results.csv` is a real pytrends recording (Oct–Nov 2024, 5 terms); `parse_trends_csv` tested against it. |
| Refreshed terms (miniatures, organizers, tools, household, toys/games) | CODE ONLY | Terms changed in code; no live pytrends call was made in this build (rate-limit caution; live is opt-in). |

## GrabCAD — 2026-11-17

| Selector | Status | Evidence |
| --- | --- | --- |
| `button[data-sort='recent']`, `a.modelLink`, `a.download` | NOT VERIFIED | From the recovered code only. Login DEFERRED; no live attempt made, no credentials used. |

## Reddit

Removed. The README claimed Reddit; no Reddit scraper ever existed in the
repo. The claim was deleted rather than implemented (no credentials, no
verified endpoint). If Reddit is wanted later, it is a new brief, not a
gap in this one.

## Fixture provenance

- `thingiverse_paste_2026-11-17.txt` — verbatim copy of the recorded
  `data/trends_input.txt` (real paste, 2025-01-31).
- `thingiverse_search_2026-11-17.html` — SYNTHETIC: reproduces the
  recovered selectors + real card text from the paste. Not a raw capture
  (live fetch 403'd).
- `printables_search_2026-11-17.html` — first result verified live
  2026-11-17; other cards synthetic, same structure.
- `printables_model_2026-11-17.html` — title/author/description/rating
  verbatim from the live fetch 2026-11-17; no licence line (none surfaced).
- `google_trends_2026-11-17.csv` — verbatim copy of the recorded
  `data/google_trends_results.csv` (real pytrends output, Oct–Nov 2024).
- `licence_cases.json` — synthetic licence cases for the filter test.
