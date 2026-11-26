# PINEAPPLE — 100-Sensor Candidate Inventory

**Status:** candidate inventory + reconciliation. **Not a build order.** No subscriptions, signups, API keys, Bridge assignments, production changes, or new code have been created by this document.

**Supersedes:** `SENSOR_INVENTORY_50.md` (2026-11-26, 50 sensors) — that doc is retained for history; this is the current catalog.

**Direction (Airam, 2026-11-25 ~23:24 CT):** Pineapple is a general-purpose intelligence system, not just a trading system. Trading is ONE division alongside regional economics, business, assets, infrastructure, government, technology and personal capital.

**Sources:** the previous 25 trading sensors (#1–25, Premium Sensor Research Initiative) and the 25 broader sensors (#26–50, expansion doc), both pasted by Airam 2026-11-25; plus Gemini's 100-sensor expansion audit delivered 2026-11-26 ([PINEAPPLE — 100-Sensor Expansion & Cross-Agent Audit](https://docs.google.com/document/d/1NJ26vX1ZLY3tDJv0vJV5QR-zpyk48jX_jhdOYtffrOY/edit), Bridge AGENT CHAT row 55, CHAT-GEMINI-20261126-001). Overlaps are reconciled against the workspace, not rebuilt. Gemini's claims are carried only where they check out against workspace files or Drive — see the corrections below.

**Verified corrections applied in this pass (Muse, 2026-11-26):**
- **#46 outcome ledger is NOT BUILT.** Gemini's audit marks the "Deal Scout Outcome Ledger" BUILT (created 2026-11-23). Verified: a Google Sheet of that name does exist in Drive (found 2026-11-26) with a LEDGER tab holding exactly 5 seeded WATCH lots (GSA Haulmark #413525, Public Surplus MEP-807A #4129958, Bond & Bond Lots 152/155/156) — zero realized flips, zero closed deals, not wired into the Deal Scout pipeline, and no copy exists in the workspace. A seeded shell with no outcomes is not a built outcome ledger. Recorded as NOT BUILT / open work. #46 itself stays BUILT as marketplace price intelligence (Deal Scout).
- **FINRA (#16/#17) keyless claim is UNVERIFIED.** FINRA developer APIs usually require a key. The ATS/Reg SHO data is public as downloadable files; the `api.finra.org` endpoints Gemini cites must be verified keyless before any build treats them as keyless. Do not present FINRA as confirmed keyless.
- **#44 Sweep 3 is Gemini-reported, not merged.** The Sweep 3 Doc (52 net-new pre-2010 US design patents) and `PINEAPPLE_Sweep3_Starter_Kit.zip` (3 STL/OpenSCAD starter models) both exist in Drive (verified 2026-11-26). Neither is merged into the local Patent Radar datasets; Sweep 2's 28 patents are also still unmerged.
- **Haulmark lot numbers reconciled.** Gemini cites "GSA Haulmark #383633" and Auction Watch records "#413525" — same trailer: #413525 is the GSA auction ID, #383633 appears in the listing title (confirmed in the ledger Sheet's LEDGER tab).
- **Endpoints verified live 2026-11-26 (bridge RESULT-CLAUDE-20261126-001/002):** CFTC COT, Treasury auctions, NY Fed SOFR (3.94% as of Nov 24), NHTSA vPIC — all HTTP 200 with real data. Caveat recorded: Treasury returns literal `"null"` strings for unset price fields — adapters must treat those as missing, not zero.

**Status key:**
- **BUILT** — a working package/collector exists in the workspace and has produced live or verified data.
- **PARTIAL** — something real exists (research, offline adapter, a live lane with gaps, a blocked feed) but the sensor is not fully operating.
- **CANDIDATE** — nothing built yet; no evidence of a collector in the workspace.
- **UNVERIFIED** — status could not be established from the files in this pass (none in this inventory — every sensor was checked at least against the package records; see the per-row evidence note).

---

## Reconciliation summary

| Status | Count |
|---|---|
| BUILT | 9 |
| PARTIAL | 24 |
| CANDIDATE | 67 |
| UNVERIFIED | 0 |
| **Total** | **100** |

**BUILT (9, unchanged from the 50-inventory):** #8 gamma exposure · #26 county appraisal/GIS · #32 ERCOT grid · #37 border crossings/freight · #44 patents/IP · #45 scientific research · #46 marketplace price intelligence · #47 industrial surplus/liquidation · #50 product recalls.

**Where the inventory already is:** the non-trading half is much further along than the expansion doc assumed — 6 of the 9 BUILT sensors are in #26–50, and 13 of the 25 broader sensors are PARTIAL rather than greenfield. The trading half is thinner than its 25-sensor list suggests: only 1 of #1–25 is fully BUILT (#8); 11 are PARTIAL (research notes, per-name checks, or a pricing rule rather than a live feed) and 13 are CANDIDATE. The 50 new sensors (#51–100) are all CANDIDATE — none has a collector yet — but 4 of their key endpoints (#15, #22, #23, #94) were verified live on 2026-11-26, so the next builds start from confirmed data, not documentation.

### Top 3 overlaps — things that looked new but already exist

1. **#45 Scientific research and #50 Product recalls — already built in `regint-free-regional`.** The expansion doc cites OpenAlex and openFDA as accessible data for these functions, but both functions are already wired: `~/workspace/pineapple/builds/regint-free-regional/src/science.py` (arXiv + Crossref, regional topics) and `~/workspace/pineapple/builds/regint-free-regional/src/recalls.py` (CPSC + NHTSA + openFDA, verified live 2026-11-26). What is genuinely new here is only OpenAlex as an additional source for #45 — not the sensor itself. (Update 2026-11-26: OpenAlex's polite pool with `mailto=` was retired Feb 2026; singleton DOI lookups remain free.)
2. **#35 Maritime AIS — three sources, one already live.** The expansion doc lists AISStream as the free-first alternative, but Public Watch (`~/workspace/pineapple/builds/public-watch/`) already has the AIS Trail port-pages leg LIVE (6 Gulf ports, 101 arrivals + 101 departures on the 2026-11-26 fix verification, 11 tankers in port), an AISStream listener built (`aisstream_listener.py`, auth-blocked — AUTH_FAILED on two different keys, 2026-11-25), and Open Waters (`ais.openwaters.io`, keyless REST) WIRED 2026-11-25, verified live returning positions for all 13 seeded yachts (tests 108/108). The sensor is PARTIAL, not a new build.
3. **The property cluster (#26, #27, #47) — already three packages deep.** #26 county appraisal/GIS is BUILT twice over (`builds/regint-assets/` — Starr CAD, 40,801 parcels live, owner categories 2026-11-25 — and `builds/intelligence/cad_appraisal/`). #27 tax liens/foreclosures/auctions and #47 industrial surplus/liquidation are both served by the same live Auction Watch (Bond & Bond, Public Surplus, GSA, GovPlanet, Starr County tax sales) plus `builds/intelligence/delinquent_tax.py` and the town-deal-finder's struck-off lane. What is missing is a direct lien/foreclosure feed (LGBS unreachable) — not the auction/surplus machinery. Gemini's #81 (Starr County deeds/liens/DBAs) is the direct-feed candidate for this gap.

---

## Division structure

**PINEAPPLE HQ** — shared intelligence and coordination. Eight divisions; each sensor has one primary division (cross-division sensors noted in the row). #100 is the HQ-level synthesis aggregator.

| Division | Sensors |
|---|---|
| Market Intelligence | #1–13, #19, #20, #21, #59, #64, #66, #67, #68 |
| Capital Intelligence | #14–18, #22, #23, #24, #25, #29, #30, #51, #55, #60, #61, #62, #63, #65, #70, #71, #72, #85 |
| Geospatial Intelligence | #26, #28, #34, #37, #58, #81, #95 |
| Infrastructure Intelligence | #32, #33, #35, #36, #38, #52, #54, #74, #76, #77, #78, #79, #80, #99 |
| Government Intelligence | #31, #39, #40, #41, #42, #43, #53, #57, #73, #75, #82, #83, #97 |
| Commercial Intelligence | #27, #46, #47, #48, #87, #93, #94, #98 |
| Technology Intelligence | #44, #45, #56, #69, #88, #89, #90, #91, #92 |
| Lifestyle Intelligence | #49, #50, #84, #86, #96 |
| PINEAPPLE HQ (synthesis) | #100 |

---

## The 100 sensors

### Market microstructure (#1–6) — Market Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 1 | Aggressor-side CVD and delta | Distinguish genuine buying/selling pressure from price moves that only look bullish/bearish | Existing access / verify | **PARTIAL.** Research only: Codex matched-horizon study (1,174 events, acceptance 47.3% vs rejection 49.7% continuation — no independent edge established) and the CVD/FVG separation work (`~/workspace/pineapple/lab/2026-11-20_profit_stack_fragment_analysis.md`); GPT's 2026-11-25 gamma package includes a combined God Mode + RSI + Williams %R + CVD backtest design (offline, no live integration). No live aggressor-side feed. TradingView's actual aggressor-side availability on our Essential plan is still uninvestigated. |
| 2 | Order-book imbalance | Real-time supply/demand skew at the touch | Existing depth feed / verify | **CANDIDATE.** No order-book collector or imbalance model found in `lab/` or `builds/trading-lab/`. |
| 3 | Liquidity heatmap | Where resting liquidity sits and thins | Emulate with depth data | **CANDIDATE.** No heatmap build found; emulation path (record order-book snapshots) is design only. |
| 4 | Iceberg and absorption detection | Hidden size and absorption at levels | Premium candidate | **CANDIDATE.** No detection build found. |
| 5 | Microprice and liquidity depletion | Short-horizon fair value and depletion signals | Build ourselves | **CANDIDATE.** No microprice model found. |
| 6 | Execution quality, spread and slippage | Whether fills actually cost what the model assumes | Build ourselves | **PARTIAL.** The Lab prices every structure on the natural executable quote (debit = long ask − short bid; credit = short bid − long ask) with five quote-sanity checks (`~/workspace/pineapple/TRADE_PROPOSAL_SPEC.md`, approved 2026-11-20). That is a pricing rule, not a measured execution-quality feed — no per-trade slippage/spread tracking exists. |

### Options intelligence (#7–13) — Market Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 7 | Independent options-chain feed | Chains not dependent on one broker's view | Account-included or delayed | **PARTIAL.** The Lab pulls Robinhood + TradingView chains 3×/weekday (`~/workspace/pineapple/lab/`, run scripts `build_options_rows_202611*.py`, workbook Options tab). No independent feed (Tradier, Databento) is wired; the chain source is broker/platform-dependent. |
| 8 | Gamma exposure by strike | Walls, flips, max pain, dealer positioning | Free model / premium comparison | **BUILT.** `~/workspace/pineapple/lab/gamma_forward_log.csv` (24 columns, 14 rows as of 2026-11-26; ZeroGEX source, pre-open capture, cron `pineapple-lab-gamma-log` weekdays 07:45 CT): walls, flips, max pain, pin strike, regime, top GEX strike, volume-profile confluence. 6 sessions scored (gamma REACTION 2/12 vs placebo 0/12 — too early to call an edge). GPT's additive scoring package (direction/proximity, magnet vs repulsion, unresolved-flip meaning, max pain daily, regime in plain English, top GEX headline; 11/11 synthetic tests) delivered 2026-11-25 — merge into the log still pending (schema review). |
| 9 | Vanna and charm exposure | How gamma shifts with price and time | Free model | **CANDIDATE.** Vanna/charm are not captured in the gamma log or any Lab file. |
| 10 | 0DTE positioning and flow | Same-day expiry positioning and flow | Premium candidate | **PARTIAL.** Policy only: 0DTE is paper-only, never auto-executed (live window 1–5 DTE). The Lab info pack carries a flow note per Top-5 name (evidence or "not captured" — never invented). No 0DTE positioning feed. |
| 11 | Unusual sweeps and block trades | Institutional flow prints | Premium candidate | **PARTIAL.** Qualitative only: the Aleks Rosme options-flow analysis (`~/workspace/pineapple/lab/2026-11-17_optionsflow_tiktok_analysis.md`) feeds the Lab info pack's flow note. No live sweeps/blocks feed. |
| 12 | Volatility surface, skew and expected move | IV regime, skew, expected move per name | Build ourselves | **PARTIAL.** Per-name IV context is in every Lab info pack (e.g. ATM IV recorded per Top-5 name) and the gamma log tags IV regime. No vol-surface or skew model is built. |
| 13 | Options liquidity and execution quality | Whether a structure is actually tradable at the quoted price | Chain data | **PARTIAL.** The five quote-sanity checks gate every Lab structure (bid≤mid≤ask; natural≥mid debit / ≤mid credit; 0<natural<width; no zero-bid-and-ask leg; >~40% natural-vs-mid gap = named quality downgrade). No per-structure liquidity scoring beyond that downgrade rule. |

### Institutional positioning and market structure (#14–20) — Capital Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 14 | Futures open-interest changes | Positioning shifts in futures | Free (CME) | **CANDIDATE.** CME named as a free source; no OI collector found. Gemini 2026-11-26: direct CME paths are weak — anonymous FTP retired Jan 2024, CmeWS blocks IPs; `datamine.cmegroup.com` / `cmegroup.com/ftp/settle/` are the endpoints to test, but CFTC COT (#15) is the practical weekly OI path. |
| 15 | CFTC institutional positioning | What commercials, funds and non-reportables hold | Free (CFTC) | **CANDIDATE.** No CFTC collector found — but the endpoint is **verified live 2026-11-26** (bridge RESULT-CLAUDE-20261126-001/002, HTTP 200): `https://publicreporting.cftc.gov/resource/6dca-aqww.json` (legacy futures; also 72hh-3qpy, gpe5-46if). Weekly, Fri 3:30 p.m. ET. Watch the column typos in the feed (`noncomm_postions_spread_all`, `swap__positions_short_all`). In the approved Macro Starter Pack sample run (Bridge row 56). |
| 16 | Off-exchange equity transactions | Dark-pool / ATS prints | Free delayed / premium | **CANDIDATE.** No collector found. Gemini cites `https://api.finra.org/data/group/otcMarket/name/weeklySummary` (POST with `compareFilters` JSON body; GET ignores params). **Keyless status UNVERIFIED** — FINRA developer APIs usually require a key; verify before building. |
| 17 | Short interest and short-sale activity | Crowding and squeeze setup | Free (FINRA) | **CANDIDATE.** No short-interest collector found. Gemini cites `https://cdn.finra.org/equity/regsho/daily/` and `https://api.finra.org/data/group/otcMarket/name/EquityShortInterest`. **Keyless status UNVERIFIED** (same FINRA footnote as #16). Note: Reg SHO is short-sale *volume*, not short interest — do not conflate them. |
| 18 | Insider buying, 13F and SEC filings | Institutional disclosures and insider signal | Free (SEC EDGAR) | **CANDIDATE.** No EDGAR/13F/insider collector found. Gemini endpoint: `https://data.sec.gov/submissions/CIK##########.json` + `companyfacts.zip`; 10 req/s max, custom User-Agent required, no CORS. Keyless. Fourth leg of Gemini's Macro Starter Pack (not in the approved sample-run scope, Bridge row 56). |
| 19 | Market breadth and participation | Whether a move is broad or narrow | Free or existing access | **PARTIAL.** The Lab's 3×/weekday TradingView screener counts (Moonshot / Breakout / Volatility) are a rough breadth read, captured in every snapshot (`~/workspace/pineapple/lab/screener_snapshots/`). No breadth model (advance/decline, % above MA) is built. |
| 20 | Sector rotation and relative strength | Where capital rotates between sectors | Build ourselves | **CANDIDATE.** No rotation/relative-strength model found. |

### Macro and alternative intelligence (#21–25) — Market / Capital Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 21 | VIX term structure and volatility regime | Volatility regime and term-structure shape | Free reference data | **PARTIAL.** The gamma log tags session types including VIX_EXPIRY (Nov 18 session scored). No VIX term-structure feed or regime model. |
| 22 | Fed liquidity, reserves and funding stress | Liquidity regime behind risk assets | Free (FRED / NY Fed) | **CANDIDATE.** No FRED/Fed collector found — but the NY Fed endpoint is **verified live 2026-11-26** (bridge RESULT-CLAUDE-20261126-001/002, HTTP 200, SOFR 3.94% as of Nov 24): `https://markets.newyorkfed.org/api/rates/all/latest.json` and `/rp/reverserepo/all/results/latest.json`. Gemini caveat: FRED CSV (`fredgraph.csv`) hit systematic 403s in June 2026 — WALCL/WTREGEN need a free 32-character FRED API key. In the approved Macro Starter Pack sample run (Bridge row 56). |
| 23 | Treasury auctions, yields and bond pressure | Government financing pressure and rates | Free (US Treasury) | **CANDIDATE.** No Treasury collector found — but the endpoint is **verified live 2026-11-26** (bridge RESULT-CLAUDE-20261126-001/002, HTTP 200): `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query` (max `page[size]=10000`). Caveat: all JSON values return as strings, and unset price fields return literal `"null"` strings — adapters must treat those as missing, not zero. In the approved Macro Starter Pack sample run (Bridge row 56). |
| 24 | Economic releases and surprise detection | Macro catalysts and consensus surprises | Free actuals; consensus access varies | **PARTIAL.** Per-name catalyst checks exist in every Lab info pack (earnings, FDA, deals). No macro release calendar or surprise-vs-consensus detection. |
| 25 | Physical energy and commodity fundamentals | Oil/gas fundamentals behind energy names | Free public sources (EIA) | **PARTIAL.** The CAPINT mineral pilot (`~/workspace/pineapple/builds/capint-pilots/CAPINT-20261125-MINERAL-PILOT.md`) carries official RRC county production (Starr Jan 2026: 1,370,576 Mcf gas, 15,507 bbl oil; Apr 2026: 1,505,447 Mcf) and lease observations. No live EIA collector. |

### Regional economics and capital movement (#26–31)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 26 | County appraisal and GIS | Property concentration, valuations, commercial expansion | County CAD, QGIS (free-first vs Regrid) | **BUILT.** `~/workspace/pineapple/builds/regint-assets/` — Starr CAD GIS live, 40,801 polygons (40,812 parcels counted 2026-11-25), $5.176B total market value; owner-category classifier built 2026-11-25 (`parcels.py`, tests 32/32) with dashboard surfacing approved and applied. `~/workspace/pineapple/builds/intelligence/cad_appraisal/cad_appraisal.py` is a second, earlier collector. Also `~/workspace/pineapple/builds/town-vitals/` (Census demographics per town). |
| 27 | Tax liens, foreclosures and auctions | Distressed-asset opportunities | County records, public listings (free-first vs PropStream) | **PARTIAL.** Auction Watch is live (cron `pineapple-auction-watch` Mon/Wed/Fri ~08:10 CT; Bond & Bond, Public Surplus, GSA, GovPlanet, Starr County tax sales; state in `~/workspace/goals/pineapple-deal-scout-resale-arbitrage-hunting/hidden_files/auction_watch.md`). `~/workspace/pineapple/builds/intelligence/delinquent_tax/delinquent_tax.py` exists. The town-deal-finder's struck-off lane runs on second-hand data (~44 parcels; LGBS tax-sale site unreachable from here) — no direct lien/foreclosure feed. Gemini's #81 (Starr County deeds/liens/DBAs) is the direct-feed candidate for this gap. |
| 28 | Building permits | Early indications of development | Census Building Permits Survey | **PARTIAL.** Adjacent only: `~/workspace/pineapple/builds/intelligence/code_violations/code_violations.py` (code violations, not permits). **Keyless path identified 2026-11-26 (Gemini):** Census BPS flat files at `https://www2.census.gov/econ/bps/County/` (`coYYMMc.txt`) — State 48, County 427 (Starr), residential only. This avoids the May 2026 Census API key mandate. No permit collector is built yet. In the approved Starr/RGV Pack sample run (Bridge row 56). |
| 29 | Mineral rights and well activity | Energy investment and royalty opportunities | Texas Railroad Commission | **PARTIAL.** CAPINT mineral pilot (above, #25): RRC official county production + 3 lease observations; finding was that no documented Starr/RGV mineral-interest listing for sale exists in accessible public sources. Town-deal-finder mineral lane: 2 mineral-keyword parcels in Starr CAD. No live well-activity feed. Working interests excluded per Airam's rule. |
| 30 | Business registrations and UCC filings | New businesses and secured financing activity | SOSDirect (owner account step) | **PARTIAL.** `~/workspace/pineapple/builds/regint-public-sector/` adapter is an offline build with a manually transcribed snapshot (3 TEA district salary observations + 6 DPS agency listings verified from public sources); live integration unverified. SOSDirect is a named unblock in `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`. No live UCC feed. |
| 31 | Government contracts and grants | Who receives funding and upcoming opportunities | USAspending | **PARTIAL.** Same regint-public-sector adapter as #30 (offline, snapshot-based). **Keyless endpoint identified 2026-11-26 (Gemini):** `POST https://api.usaspending.gov/api/v2/search/spending_by_award/` — filter TX County 427. Caveats: 10k `hasNext` bug and Nov 2026 publish-stall issues reported. Not wired live yet. In Gemini's fuller Starr/RGV Pack (not in the approved sample-run scope, Bridge row 56). |

### Infrastructure and physical-world intelligence (#32–38) — Infrastructure Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 32 | ERCOT grid intelligence | Congestion, scarcity, generation, electricity costs | ERCOT keyless APIs | **BUILT.** `~/workspace/pineapple/builds/regint-grid/` (tests 23/23): ERCOT keyless APIs live; the R2 net-load ramp rule fired live (conf 0.8). Caveat: visibility gap — the grid-context reader in the home-energy package reports STALE (last grid output Nov 19) and Airam has not been seeing ERCOT output; the sensor-visibility design (bridge row 91, GPT package delivered 2026-11-25) is the fix path. |
| 33 | Water rights and reservoir conditions | Agricultural and development constraints | Texas TCEQ GIS, USGS, IBWC | **PARTIAL.** `~/workspace/pineapple/builds/regint-sensors-pilot/` water/flood lane: new USGS api.waterdata.usgs.gov only — Roma + RGC gauges return temperature/conductance; **stage/discharge return zero rows everywhere (recorded UNKNOWN, never zero-filled)**. `~/workspace/pineapple/builds/lake-capacities/` exists. IBWC flow reports are image-only PDFs (0 extractable text) per `builds/regint-free-regional/src/gaps.py`. No water-rights feed. |
| 34 | Satellite imagery and land changes | Construction, expansion, environmental changes | Sentinel, Landsat (free-first vs Planet) | **PARTIAL.** `~/workspace/pineapple/builds/regint-sensors-pilot/` satellite lane: NASA HLS + Sentinel-2 STAC catalogs. Degraded — HLS answered all 4 AOIs on 2026-11-25 08:35 CT with 2 usable scenes (RGC S30 21% cloud, Brownsville S30 25%); Sentinel-2 STAC failed all 4 AOIs with IncompleteRead. Imagery downloads need Airam's free Copernicus account (owner step). |
| 35 | Maritime AIS | Commercial shipping and supply-chain movements | AISStream (free-first vs MarineTraffic) | **PARTIAL.** `~/workspace/pineapple/builds/public-watch/` maritime lane: AIS Trail public port pages LIVE (6 Gulf ports, last-7-days arrivals + departures; port-leg transport fixed 2026-11-26 by switching to curl — 101 arrivals + 101 departures verified). AISStream listener built (`aisstream_listener.py`, tests 84/84) but AUTH_FAILED on two different keys (2026-11-25) — vault surrogate not swapped into WebSocket JSON frames is the confirmed cause; Mac-side run is the fix path (handoff `~/workspace/pineapple/HANDOFF_CODEX_AISSTREAM_MAC.md`, bridge AGENT CHAT row 52). Open Waters (`ais.openwaters.io`, keyless REST) WIRED 2026-11-25, verified live returning positions for all 13 seeded yachts (tests 108/108). AIS Trail REST API: 401 without a key (verified 2026-11-25); free key is an owner signup. |
| 36 | Aviation ADS-B and FAA disruptions | Transportation activity and disruption risks | ADS-B (FlightAware), FAA status | **PARTIAL.** ADS-B side BUILT: Public Watch flight lanes, hourly cron, 66 tails, Texas/RGV + Tier P ping rules, 470+ findings logged. FAA disruption side missing: the FAA airport-status feed (soa.smext.faa.gov) does not complete TLS from this environment (per `builds/regint-free-regional/src/gaps.py`). Gemini's #76 (FAA delays + NTSB incidents) is the candidate for the disruption half. |
| 37 | Border crossings and freight | Regional trade and commercial demand | CBP, BTS Socrata | **BUILT.** `~/workspace/pineapple/builds/regint-sensors-pilot/` Border Flow lane — the strongest lane: CBP `bwt.cbp.gov/api/bwtnew` + BTS Socrata, 152 records/run (e.g. 2026-11-25 08:35 CT: 116 verified / 12 reported / 24 unknown; BTS 90/90 verified). BTS lag measured ~2 months. Shadow pilot, logs-only, Day-30 review ~2026-12-20. Gemini's #58 (CBP Border Wait Times at Roma/RGC POEs) pairs with this lane — same source family, hourly granularity. |
| 38 | Weather and natural hazards | Flooding, drought, outages, operational risks | Free public sources (NWS, FEMA) | **PARTIAL.** `~/workspace/pineapple/builds/geoint/adapters/fema.py` exists (FEMA adapter in the geoint package). Live FEMA NFHL is unreachable from this environment (town-deal-finder DESIGN.md: NFHL REST + msc.fema.gov both fail; manual lookup only). No live weather collector verified; wildfire feeds are blocked too (NASA FIRMS needs a free MAP_KEY; InciWeb public JSON now 404s — both per `gaps.py`). Gemini's #57 (OpenFEMA v3) and #73 (NFIP v3 claims) and #74 (NWS + Drought Monitor) are the candidates for this lane. Note the 2026 breaking change: OpenFEMA v2 retired Oct 2026 — v3/NfipClaims migration is required. |

### Government and institutional intelligence (#39–43) — Government Intelligence

Scope rule (Airam): legitimate public institutional records only — not private-person surveillance.

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 39 | Public budgets and expenditures | Where cities, counties and districts allocate money | TEA financial datasets, public budgets | **PARTIAL.** `~/workspace/pineapple/builds/regint-public-sector/` offline adapter + snapshot (3 TEA district salary observations from 2024–25 reporting, manually transcribed 2026-11-25). Live integration unverified; TEA PDF parsing needs pdftotext. No live budget feed. |
| 40 | Courts and commercial litigation | Business risks and material legal developments | CourtListener (free token, owner signup) | **CANDIDATE.** Courts lane is dark until Airam's free CourtListener signup (item in `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`, top-3 value unlock). No collector exists. Gemini's #70 (bankruptcy dockets via CourtListener PACER APIs) depends on the same signup. |
| 41 | Law enforcement public records | Agency staffing, budgets, public credential information | Texas DPS, TCOLE | **PARTIAL.** Same regint-public-sector snapshot: 6 DPS agency listings (police/sheriff/constable, from the Texas DPS approved IBR list). TCOLE employment/license/training verification is a named extension in the adapter README, not built. |
| 42 | School districts | Enrollment, compensation, funding, construction | TEA datasets | **PARTIAL.** Same regint-public-sector snapshot (3 TEA district salary observations). `~/workspace/pineapple/builds/school-assistant/` exists. BUILD-20261117-008 (School Scraper adoption) is AWAITING_AIRAM. No live enrollment/funding feed. |
| 43 | Legislation and regulatory changes | Upcoming opportunities, obligations and risks | Congress.gov, api.data.gov (free key, owner signup) | **CANDIDATE.** No legislation collector exists. The api.data.gov key (one key unlocks FEC + Congress.gov) is an owner signup in the pending-actions register. Gemini's #83 (campaign finance + lobbying, OpenFEC + TEC) is adjacent — OpenFEC is keyless with a free key path. |

### Technology, commerce and personal opportunities (#44–50)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 44 | Patents and intellectual property | Expiring protections and product inspiration | USPTO ODP (free, key held) | **BUILT.** `~/workspace/pineapple/builds/patent-radar/` (adapter v1.2.0, tests 48/48): USPTO ODP API live via connector `custom.uspto-odp`; datasets total 737 records (`data/live_patents.json` 38, `live_patents_marketable.json` 45, `live_patents_vintage.json` 69, `scrappy_google_patents.json` 585, all labeled PRESUMED_EXPIRED_SCRAPPY). Carries the required warning: idea engine, not a legal-status authority. **Gemini-reported, NOT merged (2026-11-26):** Sweep 3 — 52 net-new pre-2010 US design patents ("PINEAPPLE — Patent Radar Scrappy Sweep 3", Doc in Drive) plus `PINEAPPLE_Sweep3_Starter_Kit.zip` (3 parametric OpenSCAD + verified watertight binary STL starter models and cost cards). Both artifacts verified to exist in Drive 2026-11-26; neither is merged into the local datasets. Sweep 2's 28 patents are also still unmerged (Google Doc + bridge AGENT CHAT row 33). 2026 breaking change: USPTO PTAB legacy retired Jan 6, 2026 — transition to api.uspto.gov with MFA + ODP profile activation (affects #69). |
| 45 | Scientific research and emerging technology | Innovations before widespread commercialization | OpenAlex, arXiv, Crossref | **BUILT.** `~/workspace/pineapple/builds/regint-free-regional/src/science.py`: arXiv (export.arxiv.org) + Crossref (api.crossref.org), regional-topic queries (Rio Grande water, border trade, Starr County agriculture). OpenAlex is the only unwired source named for this sensor. Gemini 2026-11-26: `https://api.openalex.org` — polite pool (`mailto=`) retired Feb 2026; singleton DOI lookups remain free. |
| 46 | Marketplace price intelligence | Resale spreads, inventory opportunities, depreciation | Facebook Marketplace (free) | **BUILT.** Deal Scout (`~/workspace/pineapple/integration/`, adapter v0.5, sweep cron ~4h): Roma 60 mi + Laredo, seen store 5,022 IDs (2026-11-26), alert gate est. net ≥$100 AND ≥1.5× (or >$1,500 priced ≥35% under comps), FOR YOU track (5 personal categories, learns only from Airam's explicit feedback). **Outcome ledger: NOT BUILT (open work).** A Gemini-created Google Sheet titled "PINEAPPLE — Deal Scout Outcome Ledger" exists in Drive (found 2026-11-26) with a LEDGER tab of 5 seeded WATCH lots and zero realized flips — a seeded shell, not a working ledger: not wired into the Deal Scout pipeline and no copy in the workspace. Zero Deal Scout flips have closed to date. |
| 47 | Industrial surplus and liquidation | Machinery, vehicles, tools and equipment | Public Surplus, GSA, GovPlanet (free) | **BUILT.** Auction Watch (same live system as #27): Public Surplus, GSA Auctions, GovPlanet, Bond & Bond, Starr County tax sales; buy-boxes (engine-drive welder ≤$2,500, trailers with anchors, ≥20 kW diesel gensets, pre-emissions Class 8 trucks, struck-off parcels). Latest run 2026-11-25: Haulmark trailer closing, all three tracked Kenworths PASSED at the Nov 21 Bond sale, Dec 12 Cameron County catalog live (87 lots, zero matches). **Gemini 2026-11-26:** independent comp and ceiling checks logged on the Bridge for GSA Haulmark #413525 (title #383633), Public Surplus MEP-807A #4129958, and Bond & Bond Lots 152/155/156 — the same 5 lots seeded in the outcome-ledger Sheet. Gemini's #94 (NHTSA vPIC VIN decoder) is the upgrade candidate for truck/trailer verification on this lane. |
| 48 | Supply-chain and import intelligence | Product demand, suppliers, sourcing opportunities | ImportYeti (free-first vs Panjiva) | **CANDIDATE.** ImportYeti named as the free alternative; no collector found. Gemini 2026-11-26: `https://api.census.gov/data/timeseries/intltrade/imports/hs` **requires a free Census key** and `https://datawebws.usitc.gov/dataweb` (USITC token expires every 6 months, MFA) — so the import path is NOT fully keyless. The Census key is already an owner-side item (not stored anywhere). |
| 49 | Travel and airfare intelligence | Unusually inexpensive flights and accommodation | Public fare searches (free-first vs flight data APIs) | **CANDIDATE.** No travel/airfare collector found. Gemini 2026-11-26: BTS Origin & Destination survey data at `https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data`; Amadeus Self-Service shut down July 17, 2026; `fast-flights` is the live-fare path. |
| 50 | Product recalls and reliability | Vehicle, equipment and consumer-product risks | openFDA, CPSC, NHTSA (free) | **BUILT.** `~/workspace/pineapple/builds/regint-free-regional/src/recalls.py`: CPSC (saferproducts.gov, date-range query — verified 2026-11-26: Nov 1–25 2026 → 94 KB in 1.3 s), NHTSA (api.nhtsa.gov, recalls by vehicle for seeded work trucks), openFDA (api.fda.gov enforcement, Texas-filtered). |

### Regional, labor, border and environmental (#51–58)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 51 | Hiring and labor market | Starr County (48427) / McAllen MSA wages, WARN layoffs, federal jobs, LEHD hires | BLS QCEW & TWC WARN | **CANDIDATE.** No collector found. Fills the hiring-activity gap named in the 50-inventory (needed for synthesis example 3). Capital Intelligence. |
| 52 | TxDOT traffic and work zones | AADT (41,922 stations) + 5-min live WZDx closures on US-83 / I-2 | TxDOT ArcGIS & DriveTexas Docs | **CANDIDATE.** No collector found. In Gemini's fuller Starr/RGV Pack (not in the approved sample-run scope, Bridge row 56). Infrastructure Intelligence. |
| 53 | EPA ECHO and TCEQ permits | CAA air, NPDES water, RCRA, TRI, SDWIS violations by county/ZIP | EPA ECHO Web Services | **CANDIDATE.** No collector found. Overlap with #75 reconciled: #53 is violations/permits, #75 is the facility registry. In Gemini's fuller Starr/RGV Pack (not in the approved sample-run scope, Bridge row 56). Government Intelligence. |
| 54 | FCC Broadband (BDC) and ULS | H3 res-9 broadband gaps, BEAD map, daily wireless/tower filings | FCC ULS & FCC BDC | **CANDIDATE.** No collector found. Overlap with #80 reconciled: #54 is coverage/filings, #80 is funding/awards. Infrastructure Intelligence. |
| 55 | Census Business Formation (BFS) | Monthly EIN business applications (county-level added June 2026) and CBP | Census BFS API | **CANDIDATE.** No collector found. Flag: BFS is served via api.census.gov — verify the key requirement under the May 2026 Census API key mandate before building. Capital Intelligence. |
| 56 | Tech and maker velocity | GitHub commits, HuggingFace models, PyPI/npm downloads (30d median for npm) | PyPI Stats API & GitHub Rate Limits | **CANDIDATE.** No collector found. Composite velocity view; overlaps #89–#91 reconciled (#56 is the composite, #89/#90/#91 are the per-source feeds). Technology Intelligence. |
| 57 | FEMA OpenFEMA (disasters and PA) | TX county disaster declarations, NFIP v3 claims, Public Assistance grants | OpenFEMA API | **CANDIDATE.** No collector found. Overlap with #73 reconciled: #57 is declarations + PA grants, #73 is the NFIP claims dataset itself. **Breaking change: OpenFEMA v2 retired Oct 2026 — v3/NfipClaims migration required.** Government Intelligence. |
| 58 | CBP Border Wait Times | Hourly passenger, commercial truck and pedestrian wait times at Roma/RGC POEs | CBP Border Wait Times | **CANDIDATE.** No collector found. Pairs with #37 Border Flow (same source family; hourly POE waits vs monthly BTS counts). Geospatial Intelligence. |

### Market and capital intelligence (#59–72)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 59 | Futures term structure / contango | Daily NYMEX crude/gas Contracts 1–4 strips (RCLC1, RNGWHHD) | EIA API v2 Docs | **CANDIDATE.** No collector found. Flag: EIA API v2 requires a free API key — verify before building. Market Intelligence. |
| 60 | Corporate event and 8-K calendar | <1s M&A, Item 1.01, exec changes, delisting catalysts | SEC EDGAR APIs | **CANDIDATE.** No collector found. Same keyless EDGAR path as #18. Capital Intelligence. |
| 61 | Dividends, splits and buybacks | Ex-div/split calendars + XBRL-tagged share repurchases | Nasdaq Dividends JSON | **CANDIDATE.** No collector found. Capital Intelligence. |
| 62 | IPO, SPAC and S-1 pipeline | S-1/F-1 registrations, SPAC S-4 mergers, 424B4 pricing | SEC Nightly Submissions ZIP | **CANDIDATE.** No collector found. Capital Intelligence. |
| 63 | Corporate bond and credit spreads | Daily ICE BofA HY/IG OAS + TRACE breadth/sentiment | FRED API Docs | **CANDIDATE.** No collector found. Flag: FRED API needs a free 32-character key (FRED CSV hit systematic 403s June 2026). Capital Intelligence. |
| 64 | Central bank policy rates and FX | Global policy rates (WS_CBPOL) and daily ECB FX reference rates | BIS Stats API v2 & ECB Data Services | **CANDIDATE.** No collector found. Market Intelligence. |
| 65 | ETF fund flows and holdings | Quarterly/monthly holdings (CUSIPs/weights) + weekly ETF flows | SEC Form N-PORT & ICI ETF Flows | **CANDIDATE.** No collector found. Capital Intelligence. |
| 66 | Ag commodities and South TX cattle | County crop/cattle inventories + daily TX livestock auctions | USDA NASS QuickStats & USDA AMS MMN | **CANDIDATE.** No collector found. Note: the USDA QuickStats key is a named owner-side unblock in `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`. Market Intelligence. |
| 67 | Metals, lithium and critical minerals | Production, reserves and import reliance for 90+ minerals | USGS MCS 2026 | **CANDIDATE.** No collector found. Market Intelligence. |
| 68 | Crypto on-chain and stablecoins | Protocol/chain TVL, stablecoin supply/pegs, DEX volume, spot prices | DeFiLlama API & CoinGecko Keyless | **CANDIDATE.** No collector found. Market intelligence only — no trading: Airam's crypto account is an intention, not an authorization, and no account exists. Market Intelligence. |
| 69 | Patent litigation and PTAB trials | IPR, PGR, CBM, and appeal proceedings | USPTO ODP PTAB Search | **CANDIDATE.** No collector found. **Breaking change: USPTO PTAB legacy retired Jan 6, 2026 — transition to api.uspto.gov with MFA + ODP profile activation.** Technology Intelligence. |
| 70 | Bankruptcy and restructuring | Federal bankruptcy dockets/trustees + public 8-K Item 1.03 | CourtListener PACER APIs | **CANDIDATE.** No collector found. Depends on the CourtListener signup (same unblock as #40). Capital Intelligence. |
| 71 | Municipal bond and TX local debt | TX city/county/ISD/water-district debt and bond elections | Texas BRB Local Debt | **CANDIDATE.** No collector found. Capital Intelligence (cross-division Government). |
| 72 | SBA 7(a)/504 small business loans | Loan-level approvals since FY1991 filterable to Starr County | SBA 7(a) & 504 FOIA | **CANDIDATE.** No collector found. In the approved Starr/RGV Pack sample run (Bridge row 56). Capital Intelligence. |

### Geospatial, infrastructure and government (#73–86)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 73 | FEMA NFIP flood claims (v3) | Redacted NFIP claims and payments by TX county (FIPS 48427) | OpenFEMA NFIP v3 Guide | **CANDIDATE.** No collector found. In the approved Starr/RGV Pack sample run (Bridge row 56). **Breaking change: OpenFEMA v2 retired Oct 2026 — v3 required.** Government Intelligence (cross-division Geospatial). |
| 74 | NOAA weather and Drought Monitor | 2.5 km NWS forecasts/alerts + weekly county D0–D4 drought | NWS API Docs & USDM Web Service | **CANDIDATE.** No collector found. In the approved Starr/RGV Pack sample run (Bridge row 56). Infrastructure Intelligence. |
| 75 | TCEQ and EPA facility registry | Envirofacts DMAP + EPA FRS (TX-TCEQ ACR) + TCEQ GIS Hub | EPA Envirofacts API & TCEQ GIS Hub | **CANDIDATE.** No collector found. Overlap with #53 reconciled: #75 is the facility registry, #53 is violations/permits. Government Intelligence. |
| 76 | FAA delays and NTSB incidents | Live MFE/HRL/BRO airport events + civil aviation accident DB | FAA Airport Status & NTSB Avdata | **CANDIDATE.** No collector found. The disruption half of #36 — but note the FAA airport-status feed does not complete TLS from this environment (per `builds/regint-free-regional/src/gaps.py`); verify the endpoint path before building. Infrastructure Intelligence. |
| 77 | Rail freight and grade crossings | National Highway-Rail Crossing Inventory and FRA GIS rail lines | DOT GCIS Crossing API | **CANDIDATE.** No collector found. Infrastructure Intelligence. |
| 78 | Pipeline and hazmat incidents | 30-day pipeline accidents + nightly DOT Form 5800.1 hazmat spills | PHMSA Pipeline Files | **CANDIDATE.** No collector found. Infrastructure Intelligence. |
| 79 | Bridge and dam safety inventory | 624k+ US bridge condition ratings + USACE dam hazard Swagger API | USACE NID API & BTS NBI | **CANDIDATE.** No collector found. Infrastructure Intelligence. |
| 80 | Broadband and TX BEAD funding | ISP availability by geography + Texas BEAD eligible/awarded maps | FCC BDC Download & TX BEAD Map | **CANDIDATE.** No collector found. Overlap with #54 reconciled: #80 is funding/awards, #54 is coverage/filings. Infrastructure Intelligence. |
| 81 | Starr County deeds, liens and DBAs | 1848–1984 KoFile deed index + modern records via TexasFile | Starr County Clerk & KoFile Starr TX | **CANDIDATE.** No collector found. The direct-feed candidate for the #27 lien/foreclosure gap. Geospatial Intelligence. |
| 82 | TX state procurement and DIR | State/ISD bid solicitations >$25k (ESBD) + DIR Socrata contracts | TxSmartBuy ESBD & TX DIR Contracts | **CANDIDATE.** No collector found. Government Intelligence. |
| 83 | Campaign finance and lobbying | Federal FEC receipts/expenditures + TX Ethics nightly ZIPs | OpenFEC API & TEC Database | **CANDIDATE.** No collector found. OpenFEC is keyless with a free key path. Government Intelligence. |
| 84 | Clinical trials and FDA/USDA recalls | ClinicalTrials v2 + USDA FSIS meat/poultry recalls + openFDA | ClinicalTrials.gov API & USDA FSIS Recalls | **CANDIDATE.** No collector found. Pairs with #50 (recalls). Lifestyle Intelligence. |
| 85 | DOL foreign labor (H-2A / H-1B) | Employer-level H-2A (high RGV ag relevance), H-2B, LCA and PERM .xlsx | DOL OFLC Performance | **CANDIDATE.** No collector found. Pairs with #51 (labor). Capital Intelligence. |
| 86 | Higher-ed and workforce outcomes | UTRGV / STC tuition, graduation rates, debt and post-grad earnings | College Scorecard API & Urban Institute API | **CANDIDATE.** No collector found. Lifestyle Intelligence. |

### Commercial, technology and lifestyle (#87–100)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 87 | Local POI and business changes | Storefront openings/closures, category density and building footprints | OSM Overpass API & Overture Maps | **CANDIDATE.** No collector found. Commercial Intelligence. |
| 88 | Domain, SSL and tech-stack | New subdomain/product launches (crt.sh) and domain registrar (RDAP) | crt.sh Guide & IANA RDAP | **CANDIDATE.** No collector found. Technology Intelligence. |
| 89 | Open-source and AI momentum | GitHub star/commit velocity + HuggingFace model downloads/likes | HuggingFace Hub API & GitHub Rate Limits | **CANDIDATE.** No collector found. Overlap with #56 reconciled (#56 is the composite velocity view). Technology Intelligence. |
| 90 | Developer package velocity | PyPI/npm library adoption curves and daily download spikes | PyPI JSON API & npm Registry API | **CANDIDATE.** No collector found. Overlap with #56 reconciled. Technology Intelligence. |
| 91 | 3D printing and maker demand | Hardware/accessory niches and remix velocity | Thingiverse Developers | **CANDIDATE.** No collector found. Pairs with #44 (patents → print opportunities). Note: Thingiverse/Printables sign-in authorized 2026-11-17 if needed for downloads; no login saved. Technology Intelligence. |
| 92 | Trademark and brand filings | Early brand/product launches and trademark prosecution status | USPTO TSDR FAQ & USPTO ODP Key | **CANDIDATE.** No collector found. Pairs with #44. Technology Intelligence. |
| 93 | E-commerce and attention demand | Category attention spikes (Wikimedia Pageviews; Trends API is gated alpha) | Wikimedia Analytics API & Google Trends Alpha | **CANDIDATE.** No collector found. Note: pytrends archived Apr 2025; Google Trends API is gated alpha. Commercial Intelligence. |
| 94 | Vehicle and equipment VIN baseline | Year, make, model, engine and plant for MY 1981+ trucks/trailers (50/batch) | NHTSA vPIC API | **CANDIDATE.** No collector found — but the endpoint is **verified live 2026-11-26** (bridge RESULT-CLAUDE-20261126-001/002, HTTP 200). Gemini-proposed upgrade for Deal Scout and Auction Watch truck/trailer verification; NOT yet approved for build. Commercial Intelligence. |
| 95 | Regional rent and affordability | County/ZIP Fair Market Rents and tract-level rent/income ratios | HUD FMR API & Census Key Signup | **CANDIDATE.** No collector found. Flag: HUD FMR API needs a free key; Census tract data needs the Census key (owner-side item, not stored anywhere). Geospatial Intelligence. |
| 96 | Healthcare capacity and CMS | Hospital star ratings, inspection penalties and 1.6M+ clinicians | CMS Provider Data Docs | **CANDIDATE.** No collector found. Lifestyle Intelligence. |
| 97 | Crime and public safety trends | National, state and agency-level violent/property crime and clearances | FBI Crime Data Explorer | **CANDIDATE.** No collector found. Scope rule: legitimate public institutional records only. Government Intelligence. |
| 98 | Consumer financial complaints | Daily company-level complaint surges across 18M+ CCDB filings | CFPB CCDB API | **CANDIDATE.** No collector found. Commercial Intelligence. |
| 99 | Utility rates and solar potential | TOU utility tariffs, demand charges and location PV kWh estimates | NLR PVWatts V8 & OpenEI URDB | **CANDIDATE.** No collector found. Pairs with #32 (ERCOT) and the home-energy sensor. Infrastructure Intelligence. |
| 100 | Personal opportunity aggregator | Cross-division synthesis (local + market + maker arbitrage) | Aggregates #87–#99 + #1–#86 (no standalone external API) | **CANDIDATE.** Not a feed — the synthesis layer itself. Build order is after the feeds it aggregates. PINEAPPLE HQ (synthesis). |

---

## Keyless endpoint upgrades (Gemini 2026-11-26, Section 2)

Free/keyless endpoints identified for previously gap sensors. "Verified live" means an HTTP 200 with real data was observed from this environment on 2026-11-26 (bridge RESULT-CLAUDE-20261126-001/002) — not just documented.

| Sensor | Endpoint | Status |
|---|---|---|
| #14 CME OI | `datamine.cmegroup.com`, `cmegroup.com/ftp/settle/` | Documented only; anonymous FTP retired Jan 2024, CmeWS blocks IPs — use #15 COT instead |
| #15 CFTC COT | `publicreporting.cftc.gov/resource/6dca-aqww.json` | **Verified live 2026-11-26** |
| #16 FINRA ATS | `api.finra.org/data/group/otcMarket/name/weeklySummary` (POST) | **Keyless UNVERIFIED** — verify before building |
| #17 FINRA Reg SHO | `cdn.finra.org/equity/regsho/daily/`, `api.finra.org/.../EquityShortInterest` | **Keyless UNVERIFIED** — verify before building |
| #18 SEC EDGAR | `data.sec.gov/submissions/CIK##########.json`, `companyfacts.zip` | Keyless (custom User-Agent, 10 req/s) |
| #22 NY Fed SOFR/ON RRP | `markets.newyorkfed.org/api/rates/all/latest.json`, `/rp/reverserepo/all/results/latest.json` | **Verified live 2026-11-26** (SOFR 3.94% as of Nov 24) |
| #23 Treasury auctions | `api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query` | **Verified live 2026-11-26** ("null"-string caveat) |
| #28 Census BPS permits | `www2.census.gov/econ/bps/County/` (`coYYMMc.txt`) | Keyless flat files; avoids May 2026 API key mandate |
| #31 USAspending | `POST api.usaspending.gov/api/v2/search/spending_by_award/` | Keyless; 10k `hasNext` bug + Nov 2026 publish stall |
| #45 OpenAlex | `api.openalex.org` | Keyless; polite pool retired Feb 2026 |
| #48 Imports | `api.census.gov/.../intltrade/imports/hs` (key required), `datawebws.usitc.gov/dataweb` (token, 6-mo expiry, MFA) | **Not fully keyless** |
| #49 Travel | `bts.gov/.../origin-and-destination-survey-data` | Keyless (survey data); live fares via fast-flights |
| #94 NHTSA vPIC | NHTSA vPIC API (50-VIN batch) | **Verified live 2026-11-26** |

---

## Premium providers worth evaluating (free-first)

**Rule: $0 additional recurring cost budget. Exhaust current access, public institutional data, free credits and independently calculated models first. Every paid sensor must pass the acceptance test below before any spend. Presence here is not a purchase recommendation.**

### Trading premium platforms

| Provider | Premium advantage | Priority | Status |
|---|---|---|---|
| Databento | Exchange-level historical trades, order-book events, futures and options data; $125 introductory historical-data credits | Very high — validate order-flow models against actual exchange data | Not evaluated; no account |
| Tradier | Options chains, Greeks, quotes, historical data; API included for brokerage account holders; sandbox data delayed | Very high — potential independent options-data source without a data subscription; account setup needs approval | Not evaluated; no account |
| Unusual Whales | Options flow, gamma, vanna, charm, off-exchange prints, AI-compatible API; free flow data delayed 2 trading days | High — compare proprietary exposure models against ours | Not evaluated; no account |
| Bookmap | Liquidity heatmaps, order-book visualization, advanced MBO tools; real-time futures data fees separate | Medium — determine whether the underlying data adds value before paying for visualization | Not evaluated; no account |
| Cboe DataShop | Historical options quotes and interval-level data | High for backtesting — potentially a one-time dataset purchase, not recurring | Not evaluated; no account |

### Broader premium providers

| Provider | Premium advantage | Free-first alternative | Status |
|---|---|---|---|
| Regrid | Standardized property and parcel data | County CAD, QGIS | Not evaluated — #26 already BUILT on county CAD; incremental value unproven |
| PropStream | Aggregated property and investment leads | County records, public listings | Not evaluated — #27 is PARTIAL on public sources |
| CoStar | Commercial property intelligence | Public listings, permits, CAD | Not evaluated |
| Planet | Higher-frequency satellite imagery | Sentinel, Landsat | Not evaluated — #34 is PARTIAL on free imagery |
| MarineTraffic | Enhanced commercial vessel coverage | AISStream / AIS Trail / Open Waters | Not evaluated — #35 already has three free sources in play; incremental value unproven |
| Panjiva | International supply-chain intelligence | ImportYeti | Not evaluated — #48 is CANDIDATE |
| PitchBook | Private-company and investment activity | SEC, company filings, USAspending | Not evaluated |
| Flight data APIs | Automated airfare discovery | Public fare searches | Not evaluated — #49 is CANDIDATE |

### Free institutional-grade sources (use before spending)

CME (futures volume and open interest) · CFTC (institutional positioning) · Cboe (options statistics and volatility) · OCC (options volume and open interest) · FRED/ALFRED (macro data and historical release vintages) · FINRA (short activity and off-exchange reporting) · SEC EDGAR (corporate events and institutional disclosures) · OFR (financial-system stress) · US Treasury (bond auctions and government financing) · EIA (physical oil and gas fundamentals). Endpoints for CFTC, Treasury, NY Fed and NHTSA were verified live 2026-11-26 (bridge RESULT-CLAUDE-20261126-001/002); **no live collector exists yet for any of the ten** — each maps to a CANDIDATE or PARTIAL sensor above (#14–18, #22, #23, #25).

### What we can emulate ourselves

| Commercial feature | Our alternative | Limitation |
|---|---|---|
| Gamma walls | Option Greeks × open interest | Dealer positioning is estimated |
| Max pain | Calculate from chain data | Not inherently predictive |
| Expected move | ATM straddle and IV models | Model-dependent |
| Heatmap | Record order-book snapshots | Requires depth data |
| CVD | TradingView or signed trades | Bar-based estimates differ from actual aggressor data |
| Market regime | Breadth, volatility, liquidity and trend model | Requires validation |
| Relative strength | Normalized returns and rolling correlation | No pairs execution |
| Unusual options scanner | Volume/OI, RVOL, IV and premium filters | Full intraday coverage requires a suitable feed |

No pairs-trading strategies or paired positions. Cross-market relationships and correlations may be observed and calculated for free without trading spreads.

---

## Premium sensor acceptance test

| Item | Rule |
|---|---|
| Monthly data budget | **$0** additional recurring cost |
| Annual expense | **$0** |
| Proposed monthly value hurdle (3×) | **$0** — research heuristic, not a projected trading return |
| Test protocol | Baseline comparison → historical testing → prospective paper testing |
| What is measured | Whether it improves expectancy, drawdown, false signals, execution quality, or research productivity |
| Paper fills | Favorable-but-plausible paper fills kept separate from realistic execution estimates (per the approved paper-research policy, 2026-11-24) |
| Preference | 10 genuinely informative sensors over 25 redundant ones |

---

## Combination / synthesis — where Pineapple becomes powerful

Individual sensors are useful. Combining independent information is where the advantage develops. The system must tell us **what changed, why it matters, what might happen next, and what we can reasonably do about it** — and must be taught to interpret **contradictions** between sensors rather than treating every bullish reading as another vote.

### Example 1: Regional development intelligence
Land transactions (#26) + electricity demand (#32) + building permits (#28) + satellite changes (#34) + water availability (#33) + government funding (#31) → identify and investigate emerging development clusters, capital flows, constraints and commercial opportunities. **Status of the pieces:** #26 BUILT, #32 BUILT, #37 BUILT (border/freight demand), #28/#31/#33/#34 PARTIAL. New adjacent pieces in the 100-catalog: #52 traffic, #53 permits/violations, #72 SBA loans, #73 flood claims, #74 weather/drought, #81 deeds/liens. The synthesis layer itself is not built.

### Example 2: 3D-printing opportunities
Patents (#44, BUILT) + marketplace demand (#46, BUILT) + manufacturing costs → product opportunities. The manufacturing-costs leg has no sensor yet; the print queue and filament inventory exist (`~/workspace/pineapple/builds/print-queue/`). New adjacent pieces: #91 maker demand, #92 trademarks, #56 tech velocity. Sweep 3 (52 patents) + starter models are unmerged — see #44.

### Example 3: Emerging business opportunities
Government awards (#31, PARTIAL) + company registrations (#30, PARTIAL) + hiring activity (#51, now a CANDIDATE sensor) → emerging businesses. Hiring activity is no longer an unmapped gap — #51 (BLS QCEW, TWC WARN) is the candidate. New adjacent pieces: #55 business formation, #82 state procurement, #83 campaign finance.

---

## Research priorities (in order)

1. **Sensor inventory audit** — determine what Muse, Everest, Gemini and GPT already built so we don't duplicate work. *This document is the reconciliation for the Gemini half (audit delivered 2026-11-26, Doc + bridge row 55). GPT's free-sensor inventory audit was also claimed on the bridge 2026-11-26 (RESULT rows; FREE-INVENTORY registry completed, FREE-MARKET build BLOCKED only on GPT's own retrieval — endpoints verified live from here). SENSOR-001 remains open until all three audits are reconciled into one list.*
2. **Regional capital radar** — combine property, business, public spending, infrastructure and permit data, beginning with Starr County and the RGV. *Pieces: #26 BUILT, #27/#28/#29/#30/#31 PARTIAL, #32/#37 BUILT. New: #51–#58, #72–#74, #81 all CANDIDATE. Synthesis not built.*
3. **Independent market data** — repair and strengthen futures and options intelligence. *#7 PARTIAL (no independent chain feed), #14–18 CANDIDATE (endpoints now verified for #15/#18), #1 PARTIAL (research only). New: #59–#65, #68 all CANDIDATE.*
4. **Opportunity engine** — connect auctions, resale, patents, suppliers and manufacturing economics. *#44/#46/#47 BUILT, #27 PARTIAL, #48 CANDIDATE, manufacturing economics unbuilt. `~/workspace/pineapple/opportunity-engine/` exists as a directory (empty in this check). New: #94 VIN baseline is the truck/trailer verification upgrade for this engine.*
5. **Premium data evaluation** — test whether paid sources reveal meaningful information unavailable through the free stack. *$0 budget rule applies; no vendor evaluated yet.*

## SENSOR missions (in priority order)

| Mission | Objective | Priority |
|---|---|---|
| SENSOR-001 | Audit existing feeds and eliminate redundant data | P0 |
| SENSOR-002 | Independent futures and options data access | P0 |
| SENSOR-003 | Institutional positioning and macro collectors | P1 |
| SENSOR-004 | Reconstruct premium gamma and flow models | P1 |
| SENSOR-005 | Order-book and microstructure research | P1 |
| SENSOR-006 | Sensor ablation and predictive-value testing | P1 |
| SENSOR-007 | Premium vendor cost-benefit comparison | P2 |
| SENSOR-008 | Unified intelligence dashboard | P2 |

### Intelligence architecture (target)
25 raw and derived sensors (trading half) → data verification (freshness, coverage, provenance) → quant research (backtests, predictive contribution) → PINEAPPLE Intelligence Engine (confluence, contradictions, regime, scenarios) → NEXT briefing, visual dashboard, research laboratory. The same pipeline applies to the broader 25 — and to the 50 new candidates: raw sensors → verification → synthesis → briefing/dashboard.

---

## Top 5 immediate keyless builds (Gemini 2026-11-26, Section 7)

| Pack | Sensors | Status |
|---|---|---|
| Macro & Positioning Starter Pack | #15 CFTC COT + #22 NY Fed SOFR/ON RRP + #23 Treasury auctions + #18 SEC EDGAR 8-K | **Sample run APPROVED by Airam 2026-11-26** (Bridge AGENT CHAT row 56, CHAT-MUSE-20261126-SENSOR-SAMPLE-001) — approved scope is #15/#22/#23; #18 is Gemini's fourth leg, not in the approved scope. Live keyless sample into a Google Sheet; Gemini to post the Sheet link + RESULTS note on the bridge. |
| Starr/RGV Regional Intelligence Pack | #28 Census BPS permits + #31 USAspending + #52 TxDOT + #53 EPA ECHO + #72 SBA loans + #73 NFIP claims + #74 NWS/drought | **Sample run APPROVED by Airam 2026-11-26** (same row 56) — approved scope is #28/#72/#73/#74; #31/#52/#53 are Gemini's additional legs, not in the approved scope. Live keyless sample into a Google Sheet. |
| Deal Scout & Auction Upgrade | #94 NHTSA vPIC (50-VIN batch decoder for every Bond & Bond / Public Surplus / Deal Scout truck and trailer asset) | Proposed by Gemini; **not yet approved** for build. Endpoint verified live 2026-11-26. |

---

## 2026 breaking changes and caveats (Gemini 2026-11-26, Section 7)

| Change | Effect | Sensors |
|---|---|---|
| OpenFEMA v2 retired Oct 2026 | Migration to v3/NfipClaims required | #38, #57, #73 |
| USPTO PTAB legacy retired Jan 6, 2026 | Transition to api.uspto.gov with MFA + ODP profile activation | #44, #69 |
| US Census API (api.census.gov) requires a free key as of May 2026 | Flat .txt BPS files remain accessible keyless; api.census.gov keyless calls fail (302 to `missing_key.html` from here) | #28, #55, #95 |
| OpenAlex polite pool (`mailto=`) retired Feb 2026 | Standard endpoints apply; singleton DOI lookups remain free | #45 |
| FRED CSV (`fredgraph.csv`) systematic 403s since June 2026 | Must use a free 32-character FRED API key | #22, #63 |
| Amadeus Self-Service shut down July 17, 2026 | Live fares via fast-flights instead | #49 |
| pytrends archived Apr 2025 | Google Trends API is gated alpha | #93 |
| **FIPS reference: Starr County is 48427 (not 48431)** | Use 48427 in every county filter | #28, #31, #51, #57, #72, #73 |

---

## Gaps and owner-side unblocks this inventory surfaces

- **#40 courts** needs the free CourtListener token (top-3 value unlock, `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`). Also gates #70.
- **#43 legislation** needs the free api.data.gov key (same register; one key unlocks FEC + Congress.gov). Also relevant to #83 (OpenFEC has its own free key path).
- **#34 satellite downloads** need the free Copernicus account (+ NASA Earthdata alongside it).
- **#35 maritime** needs no new signup if Open Waters wiring completes; the AIS Trail REST key remains an optional free signup; the AISStream Mac-side run needs Airam to paste the key into the Mac env file himself.
- **#28 permits** now has a verified keyless path (Census BPS flat files) — no signup needed for the sample run.
- **#48 imports** needs the free Census key (Intl Trade endpoint) — owner-side item, key not stored anywhere.
- **#55 business formation, #63 bond spreads, #95 rents** need free keys (Census / FRED / HUD) — all free, owner-side signups.
- **#59 term structure** needs the free EIA API key — verify before building.
- **#66 ag commodities** needs the USDA QuickStats key (named owner-side unblock in the pending-actions register).
- **#16/#17 FINRA** — key requirement must be verified before any build treats the endpoints as keyless.
- **Hiring activity** is now sensor #51 (CANDIDATE) — no longer an unmapped gap.
- **Sensor visibility** is a cross-cutting gap, not a sensor: REGINT lanes (ERCOT especially) run but Airam does not see output. The visibility contract from GPT's 2026-11-25 gamma package (dashboard/digest surfacing) applies to every lane, not just gamma.

---

*Inventory compiled 2026-11-26 from Airam's two pasted documents, workspace verification, and Gemini's 100-sensor expansion audit (Doc + Bridge AGENT CHAT row 55, CHAT-GEMINI-20261126-001). Reconciliation statuses reflect files on disk as of this pass; a status changes only when a package, test run, or live capture proves it. Supersedes SENSOR_INVENTORY_50.md.*
