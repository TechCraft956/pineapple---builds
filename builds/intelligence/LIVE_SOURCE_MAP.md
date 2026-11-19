# LIVE_SOURCE_MAP — 04_INTELLIGENCE modules group

Prepared 2026-11-17 as part of the 04_INTELLIGENCE build (BUILD-20261117-010).
**This is a plan, not a live wiring.** No live data was fetched and no walled
source was re-probed in this build. Verdicts marked **VERIFIED LIVE** come
from the GEOINT build's evidence (`~/workspace/pineapple/builds/geoint/BUILD_REPORT.md`,
verified 2026-11-17 by direct probing) and are reused here by reference.
Everything else is **UNVERIFIED** (documented in code, never probed) or
**WALLED** (probed once by GEOINT and found unreachable — not re-probed here).

Fallback for walled/unverified portals (per the brief's routing):
**BROWSER-AGENT** on the owner's signed-in session, or **manual export**
(bulk roll / shapefile / CSV download loaded into the module's `data/`
file with the same schema as the sample). Live wiring of any radar is a
later, separately-approved step; nothing here contacts any portal.

## Already verified live (GEOINT build, 2026-11-17 — reused, not re-probed)

| Portal | What GEOINT verified | Relevance here |
|---|---|---|
| Starr CAD parcels (BIS FeatureServer) | `utility.arcgis.com/.../StarrCADWebService/FeatureServer/0 "Parcels"` — real parcels returned for a Roma envelope; fields `prop_id, geo_id, file_as_name (owner), legal_acreage, market, land_val, imprv_val, situs_*, legal_desc` | `cad_appraisal` live path for Starr County (adapter: `builds/geoint/adapters/`) |
| Willacy CAD parcels (BIS FeatureServer) | Same BIS schema as Starr (except `Block` vs `block`; county code `"GWI"`) — real parcels for a Raymondville envelope | `cad_appraisal` live path for Willacy County |
| FEMA NFHL MapServer, layer 28 "Flood Hazard Zones" | `hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer` — AE polygons returned (DFIRM 48061C); service flaky, 4× connection resets, retries recover | Flood context for `cad_appraisal` / `county_records` parcels (join semantics in GEOINT report) |
| TxGIO StratMap parcels (identify only) | `feature.geographic.texas.gov/.../stratmap_land_parcels_48_most_recent/MapServer` — `/0/query` envelope returns 0 features; **`/MapServer/identify` at a point works** (McAllen → Hidalgo parcel, Brownsville → Cameron parcel) | Fallback parcel lookup for Hidalgo + Cameron, whose own CAD REST is walled (see below) |

## Walled (GEOINT-probed once, not re-probed here)

| Portal | Verdict | Fallback |
|---|---|---|
| Hidalgo CAD — `gis.hidalgoad.org`, `esearch.hidalgoad.org` | **WALLED.** GIS host serves a bare Apache Tomcat default page; `/arcgis/rest/services` → 404. Appraisal data lives in the True Automation PropAccess JS portal (`propaccess.trueautomation.com/Search.aspx?cid=84`), which exposes no public REST. Not on BIS GIS. | TxGIO StratMap identify (verified live) for parcel lookup; BROWSER-AGENT on the owner's session for PropAccess detail; yearly appraisal-roll export into `data/parcels.json` |
| Cameron CAD — `cameroncad.org`, `esearch.cameroncad.org` | **WALLED / UNREACHABLE.** Main site unreachable via curl (HTTP 000); `http://` → 403; esearch unreachable; not on BIS GIS. District publishes a data/GIS download page with a parcel shapefile (bulk fallback) and a JS map search. | TxGIO StratMap identify (verified live); bulk parcel shapefile download; BROWSER-AGENT for the JS map search |

## Per-module live portals (unverified — documented in code, not probed)

### cad_appraisal
- Hidalgo CAD esearch `https://esearch.hidalgoad.org/` — **WALLED** (see above).
- Cameron CAD esearch `https://esearch.cameroncad.org/` — **WALLED** (see above).
- Starr CAD `https://www.starrcad.org/` — **VERIFIED LIVE** via BIS REST (GEOINT).
- Willacy CAD `https://willacycad.org/` — **VERIFIED LIVE** via BIS REST (GEOINT).
- TX Comptroller PTAD `https://comptroller.texas.gov/taxes/property-tax/` — UNVERIFIED.
- Live path (later): `data/parcels.json`, same schema as `data/sample_parcels.json`.

### county_records
- Hidalgo County Clerk `https://www.hidalgocounty.us/162/County-Clerk`, Constable sales `.../1817/Constable-Sales`, Tax Office `https://www.hidalgocountytax.org/`, Commissioners agendas `.../AgendaCenter` — UNVERIFIED.
- Cameron County Clerk `https://www.cameroncountyclerk.com/`, Tax Office `https://www.cameroncountytax.com/`, Commissioners `https://www.cameroncounty.us/` — UNVERIFIED.
- Starr `https://www.co.starr.tx.us/`, Willacy `https://www.co.willacy.tx.us/`, Brooks `https://www.co.brooks.tx.us/`, Zapata `https://www.co.zapata.tx.us/` — UNVERIFIED (county sites; Jim Hogg / Kenedy have no URL in code — clerk postings only).
- Tax-sale firms: Linebarger `https://actweb.acttax.com/`, MVBA `https://www.mvbalaw.com/tax-sales/`, Perdue Brandon `https://pbfcm.com/tax-sales/` — UNVERIFIED (public sale lists).
- County surplus `https://www.publicsurplus.com/` — UNVERIFIED.
- Live path (later): wire `_fetch_live()` (currently an intentional stub) to the same record shape as `data/sample_events.json`.

### code_violations
- McAllen code enforcement `https://www.mcallen.net/departments/code-enforcement`, Edinburg `https://www.cityofedinburg.com/`, Brownsville `https://www.cob.us/` — UNVERIFIED. Fallback: BROWSER-AGENT / manual portal export.

### delinquent_tax
- Hidalgo County Tax `https://www.hidalgocountytax.org/`, Cameron County Tax `https://www.cameroncountytax.com/` — UNVERIFIED.
- Perdue Brandon `https://www.pbfcm.com/`, Linebarger `https://www.lgbs.com/` — UNVERIFIED (delinquent-tax sale listings).

### economic_checker
- No live portals named in code — indicators are pasted/manual (`input/indicators.json`). Live path (later): a small fetcher for mortgage rates / oil / permits / announcements; not part of this build.

### local_econ
- McAllen permits `https://www.mcallen.net/departments/development-services`, McAllen bids `https://www.mcallen.net/departments/purchasing/bids` — UNVERIFIED.
- Edinburg permits `https://www.cityofedinburg.com/departments/planning_and_zoning`, Edinburg agendas `https://www.cityofedinburg.com/government/city_council/agendas_and_minutes` — UNVERIFIED.
- Brownsville permits `https://www.cob.us/197/Building-Inspection`, Brownsville agendas `https://www.cob.us/AgendaCenter` — UNVERIFIED.
- Harlingen permits `https://www.myharlingen.us/179/Permits-Licensing` — UNVERIFIED.
- Cameron County bids `https://www.cameroncountytx.gov/purchasing/` — UNVERIFIED.
- TxDOT lettings `https://www.txdot.gov/business/letting-bids.html`, TxDOT Pharr District `https://www.txdot.gov/about/districts/pharr.html` — UNVERIFIED.
- SAM.gov `https://sam.gov/content/opportunities`, grants.gov `https://www.grants.gov/search-grants`, EDA `https://www.eda.gov/funding`, Texas econ-dev `https://gov.texas.gov/business/page/economic-development-finance` — UNVERIFIED.
- McAllen EDC `https://www.medc.org/news`, Edinburg EDC `https://edinburgedc.com/news/` — UNVERIFIED.
- Every sample record carries its portal in `real_source`; live path (later) is per-portal pulls into the same signal shape.

### osint
- TX SOS SOSDirect `https://www.sos.state.tx.us/corp/sosda/index.shtml`, Comptroller taxable-entity search `https://mycpa.cpa.state.tx.us/coa/`, TDLR `https://www.tdlr.texas.gov/LicenseSearch/`, TREC `https://www.trec.texas.gov/apps/license-holder-search/`, TABC `https://www.tabc.texas.gov/services/public-inquiry/`, TxDMV `https://prod.txapps.texas.gov/tlc-search/app/license-search` — UNVERIFIED.
- Hidalgo County Clerk `https://www.hidalgocountyclerk.us/`, Cameron County Clerk `https://www.cameroncountyclerk.com/`, Starr County Clerk `https://www.co.starr.tx.us/page/starr.County.Clerk`, TX SOS UCC `https://direct.sos.state.tx.us/ucc/ucc-search.asp` — UNVERIFIED.
- Note: several of these (SOSDirect, TABC) are official lookups intended for manual/public use; wiring must respect each site's robots.txt and terms of service. Ethics gate applies to live data exactly as to sample data.

### political_tracker
- No live portals named in code — agenda text is pasted/scraped (`input/agenda_items.json`). OFFLINE by design. Live path (later): a scraper feeding the same input file; city/county agenda portals are the same ones listed under `local_econ` (UNVERIFIED).

### preforeclosure
- Hidalgo County Clerk `https://www.hidalgocounty.us/162/County-Clerk`, Cameron County Clerk `https://www.cameroncountyclerk.com/`, TDHCA `https://www.tdhca.texas.gov/` — UNVERIFIED. Fallback: BROWSER-AGENT / manual Notice-of-Sale postings.

### recon_engine
- No live portals named in code — intake is manual (`input/leads.json`) from auctions, estate/moving sales, public records, county filings, surplus. Live path (later): feeds from the specialized radars above once they are wired.

### utility_shutoffs
- McAllen Public Works `https://www.mcallen.net/departments/public-works`, Brownsville PUB `https://www.brownsville-pub.com/` — UNVERIFIED. Property-condition signal only; strongest cross-referenced with `delinquent_tax` / `code_violations` on the same parcel.

## Summary counts
- Portals verified live (GEOINT, reused): 4 (Starr CAD REST, Willacy CAD REST, FEMA NFHL layer 28, TxGIO StratMap identify).
- Portals walled (GEOINT-probed, not re-probed): 2 (Hidalgo CAD REST, Cameron CAD REST) — both have a verified fallback (StratMap identify) plus BROWSER-AGENT / bulk-export options.
- Portals unverified (documented in code, never probed): all remaining city/county/tax-sale-firm/state portals listed above (~45 URLs).
- Live data fetched in this build: none. Walled sources re-probed: none.
