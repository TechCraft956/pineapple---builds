# Panopticon v1 — FRESH BUILD (not a recovery)

Pineapple's OSINT / reconnaissance-intelligence system, built fresh on
Airam's explicit order of 2026-11-17 ("Panopticon should be made"). The
historical Panopticon implementation remains **NOT YET LOCATED** (absent
from all 9 recovered GitHub repos); this build claims no continuity with it.

Given a subject — username, person name, place, or organization — Panopticon
plans a recon pass over cataloged public sources, runs what can genuinely
run, normalizes findings with full provenance, and renders a brief that
strictly separates **VERIFIED / REPORTED / UNKNOWN**.

Ethics posture (inherited from the recovered `04_INTELLIGENCE/osint`
module): public data only; no logins or credentials; no private PII
compilation (in-code gate rejects banned fields); people-search aggregators
are purpose-gated and never automated; grey-area catalog items are mapped,
flagged `excluded`, and never run. Not a consumer report.

## Run
```bash
python3 panopticon.py selftest
python3 panopticon.py plan username somehandle --purpose "user-owned account audit"
python3 panopticon.py plan person "Jane Public" --purpose "due diligence before contracting"
python3 panopticon.py username somehandle --purpose "user-owned account audit" --out out
python3 panopticon.py place Roma, Texas --out out
python3 panopticon.py brief out/findings_<subject>.json
python3 -m unittest discover -s tests
```
Username enumeration requires a documented legitimate purpose (`--purpose`);
without one the plan/run is refused. A bare HTTP 200 with no confirming
body marker is reported as CANDIDATE (unconfirmed), never FOUND — only
GitHub, GitLab, Twitch, Hacker News, and Keybase have verified confirming
markers; Reddit, YouTube, Medium, Dev.to, and Codeberg stay CANDIDATE on
a 200. Place lookups honor Nominatim policy (identifiable UA, ≥1 req/s
throttle, local cache in `.cache/nominatim_cache.json`).
Python 3.12 stdlib only. See `BUILD_REPORT.md` for what works, what's
stubbed, and what's next. Build brief:
`~/workspace/pineapple/build-briefs/PANOPTICON_BUILD_BRIEF.md`
(bridge task BUILD-20261118-001).
