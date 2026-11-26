# PINEAPPLE — 50-Sensor Candidate Inventory

> **SUPERSEDED 2026-11-26 by [`SENSOR_INVENTORY_100.md`](SENSOR_INVENTORY_100.md)** — Gemini's 100-sensor expansion audit (Doc + Bridge AGENT CHAT row 55) expanded this catalog to 100 sensors (#1–100) with verified corrections applied. This 50-sensor doc is retained for history only; the 100-doc is the current source of truth.

**Status:** candidate inventory + reconciliation. **Not a build order.** No subscriptions, signups, API keys, Bridge assignments, production changes, or new code have been created by this document.

**Direction (Airam, 2026-11-25 ~23:24 CT):** Pineapple is a general-purpose intelligence system, not just a trading system. Trading is ONE division alongside regional economics, business, assets, infrastructure, government, technology and personal capital.

**Sources:** the previous 25 trading sensors (#1–25, Premium Sensor Research Initiative) and the 25 broader sensors (#26–50, expansion doc), both pasted by Airam 2026-11-25. Overlaps are reconciled against the workspace, not rebuilt.

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
| CANDIDATE | 17 |
| UNVERIFIED | 0 |
| **Total** | **50** |

**BUILT (9):** #8 gamma exposure · #26 county appraisal/GIS · #32 ERCOT grid · #37 border crossings/freight · #44 patents/IP · #45 scientific research · #46 marketplace price intelligence · #47 industrial surplus/liquidation · #50 product recalls.

**Where the inventory already is:** the non-trading half is much further along than the expansion doc assumed — 6 of the 9 BUILT sensors are in #26–50, and 13 of the 25 broader sensors are PARTIAL rather than greenfield. The trading half is thinner than its 25-sensor list suggests: only 1 of #1–25 is fully BUILT (#8); 11 are PARTIAL (research notes, per-name checks, or a pricing rule rather than a live feed) and 13 are CANDIDATE.

### Top 3 overlaps — things that looked new but already exist

1. **#45 Scientific research and #50 Product recalls — already built in `regint-free-regional`.** The expansion doc cites OpenAlex and openFDA as accessible data for these functions, but both functions are already wired: `~/workspace/pineapple/builds/regint-free-regional/src/science.py` (arXiv + Crossref, regional topics) and `~/workspace/pineapple/builds/regint-free-regional/src/recalls.py` (CPSC + NHTSA + openFDA, verified live 2026-11-26). What is genuinely new here is only OpenAlex as an additional source for #45 — not the sensor itself.
2. **#35 Maritime AIS — three sources, one already live.** The expansion doc lists AISStream as the free-first alternative, but Public Watch (`~/workspace/pineapple/builds/public-watch/`) already has the AIS Trail port-pages leg LIVE (6 Gulf ports, 101 arrivals + 100 departures on first parse, 13 tankers in port), an AISStream listener built (`aisstream_listener.py`, auth-blocked — AUTH_FAILED on two different keys, 2026-11-25), and Open Waters (`ais.openwaters.io`, keyless REST) verified live 2026-11-25/26 returning positions for all 13 seeded yachts, wiring in progress. The sensor is PARTIAL, not a new build.
3. **The property cluster (#26, #27, #47) — already three packages deep.** #26 county appraisal/GIS is BUILT twice over (`builds/regint-assets/` — Starr CAD, 40,801 parcels live, owner categories 2026-11-25 — and `builds/intelligence/cad_appraisal/`). #27 tax liens/foreclosures/auctions and #47 industrial surplus/liquidation are both served by the same live Auction Watch (Bond & Bond, Public Surplus, GSA, GovPlanet, Starr County tax sales) plus `builds/intelligence/delinquent_tax.py` and the town-deal-finder's struck-off lane. What is missing is a direct lien/foreclosure feed (LGBS unreachable) — not the auction/surplus machinery.

---

## Division structure

**PINEAPPLE HQ** — shared intelligence and coordination. Eight divisions; each sensor has one primary division (cross-division sensors noted in the row).

| Division | Sensors |
|---|---|
| Market Intelligence | #1–13, #19, #20, #21 |
| Capital Intelligence | #14–18, #22, #23, #24, #25, #29, #30 |
| Geospatial Intelligence | #26, #28, #34, #37 |
| Infrastructure Intelligence | #32, #33, #35, #36, #38 |
| Government Intelligence | #31, #39, #40, #41, #42, #43 |
| Commercial Intelligence | #27, #46, #47, #48 |
| Technology Intelligence | #44, #45 |
| Lifestyle Intelligence | #49, #50 |

---

## The 50 sensors

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
| 8 | Gamma exposure by strike | Walls, flips, max pain, dealer positioning | Free model / premium comparison | **BUILT.** `~/workspace/pineapple/lab/gamma_forward_log.csv` (24 columns, 12 rows; ZeroGEX source, pre-open capture, cron `pineapple-lab-gamma-log` weekdays 07:45 CT): walls, flips, max pain, pin strike, regime, top GEX strike, volume-profile confluence. 5 of 5 sessions scored (gamma REACTION 1/10 vs placebo 0/10 — too early to call an edge). GPT's additive scoring package (direction/proximity, magnet vs repulsion, unresolved-flip meaning, max pain daily, regime in plain English, top GEX headline; 11/11 synthetic tests) delivered 2026-11-25 — merge into the log still pending (schema review). |
| 9 | Vanna and charm exposure | How gamma shifts with price and time | Free model | **CANDIDATE.** Vanna/charm are not captured in the gamma log or any Lab file. |
| 10 | 0DTE positioning and flow | Same-day expiry positioning and flow | Premium candidate | **PARTIAL.** Policy only: 0DTE is paper-only, never auto-executed (live window 1–5 DTE). The Lab info pack carries a flow note per Top-5 name (evidence or "not captured" — never invented). No 0DTE positioning feed. |
| 11 | Unusual sweeps and block trades | Institutional flow prints | Premium candidate | **PARTIAL.** Qualitative only: the Aleks Rosme options-flow analysis (`~/workspace/pineapple/lab/2026-11-17_optionsflow_tiktok_analysis.md`) feeds the Lab info pack's flow note. No live sweeps/blocks feed. |
| 12 | Volatility surface, skew and expected move | IV regime, skew, expected move per name | Build ourselves | **PARTIAL.** Per-name IV context is in every Lab info pack (e.g. ATM IV recorded per Top-5 name) and the gamma log tags IV regime. No vol-surface or skew model is built. |
| 13 | Options liquidity and execution quality | Whether a structure is actually tradable at the quoted price | Chain data | **PARTIAL.** The five quote-sanity checks gate every Lab structure (bid≤mid≤ask; natural≥mid debit / ≤mid credit; 0<natural<width; no zero-bid-and-ask leg; >~40% natural-vs-mid gap = named quality downgrade). No per-structure liquidity scoring beyond that downgrade rule. |

### Institutional positioning and market structure (#14–20) — Capital Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 14 | Futures open-interest changes | Positioning shifts in futures | Free (CME) | **CANDIDATE.** CME named as a free source; no OI collector found. |
| 15 | CFTC institutional positioning | What commercials, funds and non-reportables hold | Free (CFTC) | **CANDIDATE.** No CFTC collector found. |
| 16 | Off-exchange equity transactions | Dark-pool / ATS prints | Free delayed / premium | **CANDIDATE.** FINRA named as a free delayed source; no collector found. |
| 17 | Short interest and short-sale activity | Crowding and squeeze setup | Free (FINRA) | **CANDIDATE.** No short-interest collector found. |
| 18 | Insider buying, 13F and SEC filings | Institutional disclosures and insider signal | Free (SEC EDGAR) | **CANDIDATE.** No EDGAR/13F/insider collector found. |
| 19 | Market breadth and participation | Whether a move is broad or narrow | Free or existing access | **PARTIAL.** The Lab's 3×/weekday TradingView screener counts (Moonshot / Breakout / Volatility) are a rough breadth read, captured in every snapshot (`~/workspace/pineapple/lab/screener_snapshots/`). No breadth model (advance/decline, % above MA) is built. |
| 20 | Sector rotation and relative strength | Where capital rotates between sectors | Build ourselves | **CANDIDATE.** No rotation/relative-strength model found. |

### Macro and alternative intelligence (#21–25) — Market / Capital Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 21 | VIX term structure and volatility regime | Volatility regime and term-structure shape | Free reference data | **PARTIAL.** The gamma log tags session types including VIX_EXPIRY (Nov 18 session scored). No VIX term-structure feed or regime model. |
| 22 | Fed liquidity, reserves and funding stress | Liquidity regime behind risk assets | Free (FRED) | **CANDIDATE.** No FRED/Fed collector found. |
| 23 | Treasury auctions, yields and bond pressure | Government financing pressure and rates | Free (US Treasury) | **CANDIDATE.** No Treasury collector found. |
| 24 | Economic releases and surprise detection | Macro catalysts and consensus surprises | Free actuals; consensus access varies | **PARTIAL.** Per-name catalyst checks exist in every Lab info pack (earnings, FDA, deals). No macro release calendar or surprise-vs-consensus detection. |
| 25 | Physical energy and commodity fundamentals | Oil/gas fundamentals behind energy names | Free public sources (EIA) | **PARTIAL.** The CAPINT mineral pilot (`~/workspace/pineapple/builds/capint-pilots/CAPINT-20261125-MINERAL-PILOT.md`) carries official RRC county production (Starr Jan 2026: 1,370,576 Mcf gas, 15,507 bbl oil; Apr 2026: 1,505,447 Mcf) and lease observations. No live EIA collector. |

### Regional economics and capital movement (#26–31)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 26 | County appraisal and GIS | Property concentration, valuations, commercial expansion | County CAD, QGIS (free-first vs Regrid) | **BUILT.** `~/workspace/pineapple/builds/regint-assets/` — Starr CAD GIS live, 40,801 polygons (40,812 parcels counted 2026-11-25), $5.176B total market value; owner-category classifier built 2026-11-25 (`parcels.py`, tests 32/32) with dashboard surfacing approved and applied. `~/workspace/pineapple/builds/intelligence/cad_appraisal/cad_appraisal.py` is a second, earlier collector. Also `~/workspace/pineapple/builds/town-vitals/` (Census demographics per town). |
| 27 | Tax liens, foreclosures and auctions | Distressed-asset opportunities | County records, public listings (free-first vs PropStream) | **PARTIAL.** Auction Watch is live (cron `pineapple-auction-watch` Mon/Wed/Fri ~08:10 CT; Bond & Bond, Public Surplus, GSA, GovPlanet, Starr County tax sales; state in `~/workspace/goals/pineapple-deal-scout-resale-arbitrage-hunting/hidden_files/auction_watch.md`). `~/workspace/pineapple/builds/intelligence/delinquent_tax/delinquent_tax.py` exists. The town-deal-finder's struck-off lane runs on second-hand data (~44 parcels; LGBS tax-sale site unreachable from here) — no direct lien/foreclosure feed. |
| 28 | Building permits | Early indications of development | Census Building Permits Survey | **PARTIAL.** Adjacent only: `~/workspace/pineapple/builds/intelligence/code_violations/code_violations.py` (code violations, not permits). The Census Building Permits Survey has not been wired; no permit feed exists. |
| 29 | Mineral rights and well activity | Energy investment and royalty opportunities | Texas Railroad Commission | **PARTIAL.** CAPINT mineral pilot (above, #25): RRC official county production + 3 lease observations; finding was that no documented Starr/RGV mineral-interest listing for sale exists in accessible public sources. Town-deal-finder mineral lane: 2 mineral-keyword parcels in Starr CAD. No live well-activity feed. Working interests excluded per Airam's rule. |
| 30 | Business registrations and UCC filings | New businesses and secured financing activity | SOSDirect (owner account step) | **PARTIAL.** `~/workspace/pineapple/builds/regint-public-sector/` adapter is an offline build with a manually transcribed snapshot (3 TEA district salary observations + 6 DPS agency listings verified from public sources); live integration unverified. SOSDirect is a named unblock in `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`. No live UCC feed. |
| 31 | Government contracts and grants | Who receives funding and upcoming opportunities | USAspending | **PARTIAL.** Same regint-public-sector adapter as #30 (offline, snapshot-based). USAspending has not been wired live. |

### Infrastructure and physical-world intelligence (#32–38) — Infrastructure Intelligence

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 32 | ERCOT grid intelligence | Congestion, scarcity, generation, electricity costs | ERCOT keyless APIs | **BUILT.** `~/workspace/pineapple/builds/regint-grid/` (tests 23/23): ERCOT keyless APIs live; the R2 net-load ramp rule fired live (conf 0.8). Caveat: visibility gap — the grid-context reader in the home-energy package reports STALE (last grid output Nov 19) and Airam has not been seeing ERCOT output; the sensor-visibility design (bridge row 91, GPT package delivered 2026-11-25) is the fix path. |
| 33 | Water rights and reservoir conditions | Agricultural and development constraints | Texas TCEQ GIS, USGS, IBWC | **PARTIAL.** `~/workspace/pineapple/builds/regint-sensors-pilot/` water/flood lane: new USGS api.waterdata.usgs.gov only — Roma + RGC gauges return temperature/conductance; **stage/discharge return zero rows everywhere (recorded UNKNOWN, never zero-filled)**. `~/workspace/pineapple/builds/lake-capacities/` exists. IBWC flow reports are image-only PDFs (0 extractable text) per `builds/regint-free-regional/src/gaps.py`. No water-rights feed. |
| 34 | Satellite imagery and land changes | Construction, expansion, environmental changes | Sentinel, Landsat (free-first vs Planet) | **PARTIAL.** `~/workspace/pineapple/builds/regint-sensors-pilot/` satellite lane: NASA HLS + Sentinel-2 STAC catalogs. Degraded — HLS answered all 4 AOIs on 2026-11-25 08:35 CT with 2 usable scenes (RGC S30 21% cloud, Brownsville S30 25%); Sentinel-2 STAC failed all 4 AOIs with IncompleteRead. Imagery downloads need Airam's free Copernicus account (owner step). |
| 35 | Maritime AIS | Commercial shipping and supply-chain movements | AISStream (free-first vs MarineTraffic) | **PARTIAL.** `~/workspace/pineapple/builds/public-watch/` maritime lane: AIS Trail public port pages LIVE (6 Gulf ports, last-7-days arrivals + departures; first run 101 arrivals, 13 tankers in port). AISStream listener built (`aisstream_listener.py`, tests 84/84) but AUTH_FAILED on two different keys (2026-11-25) — vault surrogate not swapped into WebSocket JSON frames is the confirmed cause; Mac-side run is the fix path (handoff `~/workspace/pineapple/HANDOFF_CODEX_AISSTREAM_MAC.md`, bridge AGENT CHAT row 52). Open Waters (`ais.openwaters.io`, keyless REST) verified live 2026-11-25/26 returning positions for all 13 seeded yachts; wiring in progress. AIS Trail REST API: 401 without a key (verified 2026-11-25); free key is an owner signup. |
| 36 | Aviation ADS-B and FAA disruptions | Transportation activity and disruption risks | ADS-B (FlightAware), FAA status | **PARTIAL.** ADS-B side BUILT: Public Watch flight lanes, hourly cron, 66 tails, Texas/RGV + Tier P ping rules, 470+ findings logged. FAA disruption side missing: the FAA airport-status feed (soa.smext.faa.gov) does not complete TLS from this environment (per `builds/regint-free-regional/src/gaps.py`). |
| 37 | Border crossings and freight | Regional trade and commercial demand | CBP, BTS Socrata | **BUILT.** `~/workspace/pineapple/builds/regint-sensors-pilot/` Border Flow lane — the strongest lane: CBP `bwt.cbp.gov/api/bwtnew` + BTS Socrata, 152 records/run (e.g. 2026-11-25 08:35 CT: 116 verified / 12 reported / 24 unknown; BTS 90/90 verified). BTS lag measured ~2 months. Shadow pilot, logs-only, Day-30 review ~2026-12-20. |
| 38 | Weather and natural hazards | Flooding, drought, outages, operational risks | Free public sources (NWS, FEMA) | **PARTIAL.** `~/workspace/pineapple/builds/geoint/adapters/fema.py` exists (FEMA adapter in the geoint package). Live FEMA NFHL is unreachable from this environment (town-deal-finder DESIGN.md: NFHL REST + msc.fema.gov both fail; manual lookup only). No live weather collector verified; wildfire feeds are blocked too (NASA FIRMS needs a free MAP_KEY; InciWeb public JSON now 404s — both per `gaps.py`). |

### Government and institutional intelligence (#39–43) — Government Intelligence

Scope rule (Airam): legitimate public institutional records only — not private-person surveillance.

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 39 | Public budgets and expenditures | Where cities, counties and districts allocate money | TEA financial datasets, public budgets | **PARTIAL.** `~/workspace/pineapple/builds/regint-public-sector/` offline adapter + snapshot (3 TEA district salary observations from 2024–25 reporting, manually transcribed 2026-11-25). Live integration unverified; TEA PDF parsing needs pdftotext. No live budget feed. |
| 40 | Courts and commercial litigation | Business risks and material legal developments | CourtListener (free token, owner signup) | **CANDIDATE.** Courts lane is dark until Airam's free CourtListener signup (item in `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`, top-3 value unlock). No collector exists. |
| 41 | Law enforcement public records | Agency staffing, budgets, public credential information | Texas DPS, TCOLE | **PARTIAL.** Same regint-public-sector snapshot: 6 DPS agency listings (police/sheriff/constable, from the Texas DPS approved IBR list). TCOLE employment/license/training verification is a named extension in the adapter README, not built. |
| 42 | School districts | Enrollment, compensation, funding, construction | TEA datasets | **PARTIAL.** Same regint-public-sector snapshot (3 TEA district salary observations). `~/workspace/pineapple/builds/school-assistant/` exists. BUILD-20261117-008 (School Scraper adoption) is AWAITING_AIRAM. No live enrollment/funding feed. |
| 43 | Legislation and regulatory changes | Upcoming opportunities, obligations and risks | Congress.gov, api.data.gov (free key, owner signup) | **CANDIDATE.** No legislation collector exists. The api.data.gov key (one key unlocks FEC + Congress.gov) is an owner signup in the pending-actions register. |

### Technology, commerce and personal opportunities (#44–50)

| # | Sensor | What it unlocks | Acquisition (free-first) | Reconciliation |
|---|---|---|---|---|
| 44 | Patents and intellectual property | Expiring protections and product inspiration | USPTO ODP (free, key held) | **BUILT.** `~/workspace/pineapple/builds/patent-radar/` (adapter v1.2.0, tests 48/48): USPTO ODP API live via connector `custom.uspto-odp`; datasets total 737 records (`data/live_patents.json` 38, `live_patents_marketable.json` 45, `live_patents_vintage.json` 69, `scrappy_google_patents.json` 585, all labeled PRESUMED_EXPIRED_SCRAPPY). Carries the required warning: idea engine, not a legal-status authority. Open: review/merge Gemini's Sweep 2 (28 pre-2010 design patents, Google Doc + bridge AGENT CHAT row 33). |
| 45 | Scientific research and emerging technology | Innovations before widespread commercialization | OpenAlex, arXiv, Crossref | **BUILT.** `~/workspace/pineapple/builds/regint-free-regional/src/science.py`: arXiv (export.arxiv.org) + Crossref (api.crossref.org), regional-topic queries (Rio Grande water, border trade, Starr County agriculture). OpenAlex is the only unwired source named for this sensor. |
| 46 | Marketplace price intelligence | Resale spreads, inventory opportunities, depreciation | Facebook Marketplace (free) | **BUILT.** Deal Scout (`~/workspace/pineapple/integration/`, adapter v0.5, sweep cron ~4h): Roma 60 mi + Laredo, seen store ~4,993 IDs (2026-11-25), alert gate est. net ≥$100 AND ≥1.5× (or >$1,500 priced ≥35% under comps), FOR YOU track (5 personal categories, learns only from Airam's explicit feedback). Zero flips closed to date; the realized-flip outcome ledger is still unbuilt. |
| 47 | Industrial surplus and liquidation | Machinery, vehicles, tools and equipment | Public Surplus, GSA, GovPlanet (free) | **BUILT.** Auction Watch (same live system as #27): Public Surplus, GSA Auctions, GovPlanet, Bond & Bond, Starr County tax sales; buy-boxes (engine-drive welder ≤$2,500, trailers with anchors, ≥20 kW diesel gensets, pre-emissions Class 8 trucks, struck-off parcels). Latest run 2026-11-25: Haulmark trailer closing, all three tracked Kenworths PASSED at the Nov 21 Bond sale, Dec 12 Cameron County catalog live (87 lots, zero matches). |
| 48 | Supply-chain and import intelligence | Product demand, suppliers, sourcing opportunities | ImportYeti (free-first vs Panjiva) | **CANDIDATE.** ImportYeti named as the free alternative; no collector found. |
| 49 | Travel and airfare intelligence | Unusually inexpensive flights and accommodation | Public fare searches (free-first vs flight data APIs) | **CANDIDATE.** No travel/airfare collector found. |
| 50 | Product recalls and reliability | Vehicle, equipment and consumer-product risks | openFDA, CPSC, NHTSA (free) | **BUILT.** `~/workspace/pineapple/builds/regint-free-regional/src/recalls.py`: CPSC (saferproducts.gov, date-range query — verified 2026-11-26: Nov 1–25 2026 → 94 KB in 1.3 s), NHTSA (api.nhtsa.gov, recalls by vehicle for seeded work trucks), openFDA (api.fda.gov enforcement, Texas-filtered). |

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

CME (futures volume and open interest) · CFTC (institutional positioning) · Cboe (options statistics and volatility) · OCC (options volume and open interest) · FRED/ALFRED (macro data and historical release vintages) · FINRA (short activity and off-exchange reporting) · SEC EDGAR (corporate events and institutional disclosures) · OFR (financial-system stress) · US Treasury (bond auctions and government financing) · EIA (physical oil and gas fundamentals). None of these ten has a live collector in the workspace yet — each maps to a CANDIDATE or PARTIAL sensor above (#14–18, #22, #23, #25).

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
Land transactions (#26) + electricity demand (#32) + building permits (#28) + satellite changes (#34) + water availability (#33) + government funding (#31) → identify and investigate emerging development clusters, capital flows, constraints and commercial opportunities. **Status of the pieces:** #26 BUILT, #32 BUILT, #37 BUILT (border/freight demand), #28/#31/#33/#34 PARTIAL. The synthesis layer itself is not built.

### Example 2: 3D-printing opportunities
Patents (#44, BUILT) + marketplace demand (#46, BUILT) + manufacturing costs → product opportunities. The manufacturing-costs leg has no sensor yet; the print queue and filament inventory exist (`~/workspace/pineapple/builds/print-queue/`).

### Example 3: Emerging business opportunities
Government awards (#31, PARTIAL) + company registrations (#30, PARTIAL) + hiring activity (no sensor yet) → emerging businesses. Hiring activity is a gap: no sensor covers it.

---

## Research priorities (in order)

1. **Sensor inventory audit** — determine what Muse, Everest, Gemini and GPT already built so we don't duplicate work. *This document is the first pass of that audit (workspace-verified). The cross-agent half (what Gemini/GPT built on the bridge) is still open.*
2. **Regional capital radar** — combine property, business, public spending, infrastructure and permit data, beginning with Starr County and the RGV. *Pieces: #26 BUILT, #27/#28/#29/#30/#31 PARTIAL, #32/#37 BUILT. Synthesis not built.*
3. **Independent market data** — repair and strengthen futures and options intelligence. *#7 PARTIAL (no independent chain feed), #14–18 CANDIDATE, #1 PARTIAL (research only).*
4. **Opportunity engine** — connect auctions, resale, patents, suppliers and manufacturing economics. *#44/#46/#47 BUILT, #27 PARTIAL, #48 CANDIDATE, manufacturing economics unbuilt. `~/workspace/pineapple/opportunity-engine/` exists as a directory (empty in this check).*
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
25 raw and derived sensors (trading half) → data verification (freshness, coverage, provenance) → quant research (backtests, predictive contribution) → PINEAPPLE Intelligence Engine (confluence, contradictions, regime, scenarios) → NEXT briefing, visual dashboard, research laboratory. The same pipeline applies to the broader 25: raw sensors → verification → synthesis → briefing/dashboard.

---

## Gaps and owner-side unblocks this inventory surfaces

- **#40 courts** needs the free CourtListener token (top-3 value unlock, `~/workspace/pineapple/PENDING_OWNER_ACTIONS.md`).
- **#43 legislation** needs the free api.data.gov key (same register; one key unlocks FEC + Congress.gov).
- **#34 satellite downloads** need the free Copernicus account (+ NASA Earthdata alongside it).
- **#35 maritime** needs no new signup if Open Waters wiring completes; the AIS Trail REST key remains an optional free signup; the AISStream Mac-side run needs Airam to paste the key into the Mac env file himself.
- **#28 permits** has no free keyless path verified yet — the Census Building Permits Survey is the named starting point.
- **Hiring activity** (needed for synthesis example 3) has no sensor in the 50 and no collector anywhere in the workspace — a candidate for a future #51.
- **Sensor visibility** is a cross-cutting gap, not a sensor: REGINT lanes (ERCOT especially) run but Airam does not see output. The visibility contract from GPT's 2026-11-25 gamma package (dashboard/digest surfacing) applies to every lane, not just gamma.

---

*Inventory compiled 2026-11-26 from Airam's two pasted documents and workspace verification. Reconciliation statuses reflect files on disk as of this pass; a status changes only when a package, test run, or live capture proves it.*
