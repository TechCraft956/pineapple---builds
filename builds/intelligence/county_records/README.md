# County Records Radar

`04_INTELLIGENCE/county_records/`

Surfaces high-ROI **public-record** events across the Rio Grande Valley and
neighbor counties, ranks them, and feeds them to the Pineapple decision engine.

## What it surfaces

| Event type | Source kind | Why it matters |
|---|---|---|
| `tax_delinquent` | County tax office delinquent rolls / struck-off resale lists | Cheap basis; below-market acquisition |
| `constable_sale` | Constable & sheriff tax-judgment sale postings | Firm sale dates, tax-judgment titles |
| `foreclosure_posting` | Substitute-trustee / lien Notices of Sale (first-Tuesday) | Larger tickets, distress pricing |
| `county_auction` | County surplus / fleet / equipment auctions | Equipment flips, low entry |
| `commissioners_agenda` | Commissioners court agenda packets | Early signal of infra/zoning/ROW moves |

**Counties:** Core RGV — Hidalgo, Cameron, Starr, Willacy. Neighbors — Brooks,
Kenedy, Jim Hogg, Zapata.

## Status: SAMPLE (offline)

Ships with ~15 fabricated, clearly-marked sample events in
`data/sample_events.json`. It **never** fetches live data. `_fetch_live()` is a
stub kept disabled to honor the offline guarantee. Addresses, account/case
numbers, owners, and dollar amounts are synthetic — do not act on them.

## Real live sources (for wiring later)

All official / public record. Documented in code (`REAL_SOURCES` + header) and in
`data/sample_events.json` `_meta.real_sources`.

- Hidalgo County Clerk public notices — https://www.hidalgocounty.us/162/County-Clerk
- Hidalgo Constable sales — https://www.hidalgocounty.us/1817/Constable-Sales
- Hidalgo Tax Office delinquent roll — https://www.hidalgocountytax.org/
- Hidalgo Commissioners Court agendas — https://www.hidalgocounty.us/AgendaCenter
- Cameron County Clerk — https://www.cameroncountyclerk.com/
- Cameron Tax Office / struck-off resale — https://www.cameroncountytax.com/
- Cameron Commissioners Court — https://www.cameroncounty.us/
- Starr County — https://www.co.starr.tx.us/
- Willacy County — https://www.co.willacy.tx.us/
- Brooks County — https://www.co.brooks.tx.us/
- Zapata County — https://www.co.zapata.tx.us/
- Linebarger struck-off — https://actweb.acttax.com/
- MVBA tax sales — https://www.mvbalaw.com/tax-sales/
- Perdue Brandon tax sales — https://pbfcm.com/tax-sales/
- County surplus auctions — https://www.publicsurplus.com/
- Legal basis: TX Tax Code ch. 34 (struck-off/resale), TX Property Code 51.002 (Notice of Sale)

## Ranking

Composite 0–100 score per event:

```
score = (0.45*value_spread + 0.20*type_weight + 0.15*location + 0.20*urgency) * risk_mult
```

- **value_spread**: `assessed_value − acquisition_cost` (min_bid, else amount_owed), curved to ~$150k.
- **type_weight**: tax-delinquent/constable highest, surplus lowest.
- **location**: core RGV counties weighted above neighbors.
- **urgency**: days to sale/meeting date (≤7d = max).
- **risk_mult**: LOW 1.0 / MED 0.9 / HIGH 0.78. Murky title (heir/probate/estate) escalates risk.

`confidence` capped at 0.85 because the data is sample.

## Usage

```bash
python county_records.py --selftest    # health check, exit 0 on success
python county_records.py               # printed ranked radar
python county_records.py --json        # ranked items() as JSON
python county_records.py --publish     # write 00_PROCESSED/county_records_items.json
```

Pure Python 3.11 stdlib. No third-party deps.

## How it plugs into the decision brief

- Exposes `PLUGIN` (id `county_records`, category `ASSETS`, status `sample`) and
  `items() -> list[dict]`. Each item carries the decision-engine contract:
  `title, category, source, action, est_value, risk, location, url, confidence`
  plus extras (`score`, `event_type`, `county`, `auction_date`, …).
- Asset events map to category **ASSETS**; commissioners-court signals map to
  **OPPORTUNITIES** — matching the decision engine's buckets.
- `--publish` writes `00_PROCESSED/county_records_items.json` (the only file it
  writes outside its own folder). The decision engine / brief can ingest that
  file, or call `items()` directly.
- Writes are guarded: `_assert_safe_write` refuses any path outside this module
  folder or `00_PROCESSED`.

## Safety

Read-only toward records. Surfaces leads only — files no bids, contacts no
owners, takes no legal action. Tax/foreclosure sales carry title, redemption-
period, and as-is risk. Verify every record on the official source and consult
counsel before acting.
