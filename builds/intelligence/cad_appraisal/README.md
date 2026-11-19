# CAD Appraisal — County Appraisal District Property Intelligence

> **CAD = County Appraisal District** (the Texas property-tax authority), **not** computer-aided design.

Rio Grande Valley property intelligence. Given a parcel/account, returns the public
appraisal record and a computed **equity-vs-comps** signal, then flags acquisition
candidates for the real-estate radar.

Layer: `04_INTELLIGENCE/cad_appraisal/`
Status: **sample** (synthetic data; flip to `live` once wired — see below).
Pure Python 3.11 **stdlib only**. Read-only. Offline.

---

## What it does

Per parcel it returns: **owner, situs address, market value, land/improvement split,
year built, acreage, years owned**, and an **equity-vs-comps signal**:

```
comp_value          = living_area_sqft  ×  comp_median_value_per_sqft   (neighborhood comp)
under_assessed_pct  = (comp_value − CAD_market_value) / comp_value × 100
                      positive  => CAD appraises BELOW comps => latent equity on acquisition
```

`items()` flags candidates for the real-estate radar:

| Flag | Trigger | Why it matters |
|------|---------|----------------|
| `under_assessed` | CAD market ≥ 8% below comps | Built-in equity at acquisition |
| `high_equity` | land+improvement (or market) ≥ $200k | Owner has room to deal |
| `long_owned` | held ≥ 25 years | Low loan balance, tired owner |
| `estate_or_trust` | owner name contains estate/trust/heirs | Probate-adjacent, motivated heirs |
| `raw_land` | no improvement and ≥ 5 acres | Development / land-flip candidate |

---

## Run

```bash
python cad_appraisal.py                          # flagged radar candidates (JSON)
python cad_appraisal.py --account P504217         # full record for one Hidalgo account
python cad_appraisal.py --account 44-0820-0155-0023-00   # a Cameron account
python cad_appraisal.py --list                    # list all sample accounts
python cad_appraisal.py --snapshot                # write items to 00_PROCESSED
python cad_appraisal.py --selftest                # health summary; exit 0 on success
```

## Files

```
cad_appraisal/
├── cad_appraisal.py            # module (PLUGIN, items(), lookup(), describe(), selftest)
├── README.md
└── data/
    └── sample_parcels.json     # ~12 RGV parcels (Hidalgo + Cameron), clearly SAMPLE
```

Outputs are written **only** to this folder or `00_PROCESSED/cad_appraisal_items.json`.

---

## How it plugs into the decision brief

Exposes the standard Pineapple contract:

- `PLUGIN` — module-level dict (`id, name, category, authority, status, inputs, outputs, sources, safety`).
- `items() -> list[dict]` — each item carries the keys the **Decision Engine**
  (`decision_engine.py`) consumes: `title, category, source, action, est_value,
  risk ("LOW"/"MED"/"HIGH"), location, url, confidence` (plus `flags, owner,
  account, under_assessed_pct, years_owned, …` as ignored extras).

Items use `category: "ASSETS"`, so the brief files them under the **ASSETS** decision
bucket alongside `real_estate_radar`. The radar can consume the flagged accounts
directly (situs + signal + est_value) as enriched leads. The pre-registered
`county_records` source slot in `07_NETWORK/registry/source_plugins.json` (status
`planned`) is the intended home for this once promoted to `live`.

> Note: this module does **not** modify any existing file (registry, server, brief).
> Wiring it into the registry is a separate, deliberate step by the operator.

---

## REAL live sources (offline here — wire these for production)

All public. No live network calls are made by this module.

**Primary (RGV counties):**
- **Hidalgo County AD** — property search: <https://esearch.hidalgoad.org/> · main: <https://www.hidalgoad.org/>
- **Cameron County AD** — property search: <https://esearch.cameroncad.org/> · main: <https://www.cameroncad.org/>
- **Starr County AD** — <https://www.starrcad.org/>
- **Willacy County AD** — <https://willacycad.org/>
- Neighbors: Brooks CAD, Kenedy CAD, Jim Hogg CAD, Zapata CAD (county-named CADs)

**Statewide context:**
- Texas Comptroller, Property Tax Assistance Division — <https://comptroller.texas.gov/taxes/property-tax/>

### Wiring to live data

Many Texas CADs run **esearch** portals (True Automation / TrueProdigy) with per-account
detail pages, and publish a **yearly appraisal roll / data download** (fixed-width or CSV).
To go live: scrape per-account detail or load the yearly export into
`data/parcels.json` using the **same schema** as `data/sample_parcels.json`
(`account, geo_id, cad, owner, situs, land_value, improvement_value, market_value,
assessed_value, year_built, living_area_sqft, acreage, last_deed_year, homestead,
comp_median_value_per_sqft`). The module loads `data/parcels.json` automatically when
present, otherwise falls back to the sample. Then set `PLUGIN["status"] = "live"`.

Derive `comp_median_value_per_sqft` in production from sold comps or CAD neighborhood
codes rather than the hand-set sample medians.

---

## Safety

READ-ONLY. Public appraisal records only. **SAMPLE data is synthetic** and every owner
is suffixed `(sample)` — do not treat owners/values as real. This module only **flags**
candidates; it does no skip-tracing and contacts no one. Verify against the live CAD
before any outreach or offer.
