# Central bank policy rates & FX — sensor #64 (`rates_fx.py`)

## What it does

Two keyless legs, stdlib only:

1. **BIS central bank policy rates (WS_CBPOL)** via the BIS Stats
   API v2 (SDMX-JSON). Monthly series for 14 economies (US, XM,
   GB, JP, CN, CH, CA, AU, IN, BR, MX, KR, ZA, SE) plus daily US
   and euro-area series where the BIS publishes them.
2. **ECB Data Services** (SDW API, JSON-data format): daily euro
   foreign-exchange reference rates (EXR) for 12 currencies, plus
   EURIBOR 3M / 1Y from the FM dataflow.

## The BIS URL form matters

The dataflow path MUST be:

```
https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/<FREQ>.<AREA>?lastNObservations=3
```

with header `Accept: application/vnd.sdmx.data+json;version=1.0.0`.
Verified failure modes (2026-11-26): the short path
`/data/WS_CBPOL/...` returns HTTP 500 ("Could not find structure
type"), a plain request without the Accept header returns 406, and
`?format=json` / `?format=csv` return 406 / 500. The `dataflow`
resource itself is not listable (501).

The BIS reports the FOMC target-range midpoint for the US (3.875 =
3.75–4.00% after the 16 Sep 2026 cut) — the collector records the
BIS value as filed and never re-derives it.

## Run

```sh
python3 rates_fx.py --last-n 3 --out evidence/rates_fx_run_20261126.json
```

## Live evidence (2026-11-26)

90 observations, all VERIFIED. BIS: 16 series (14 monthly + daily
US/XM). US policy rate 3.625 (Aug 2026) → 3.875 (Sep, Oct); euro
area 2.25 → 2.50. ECB: 12 FX reference rates (USD/EUR 1.0963 /
1.0935 / 1.0975, Nov 24–26) + EURIBOR 3M ~2.63%, 1Y ~3.24%.

## Caveats

- The ECB's own key policy rates (MRO / deposit facility) have no
  stable SDW key in this API — guessed keys (`ECBDFR_`, `ECBMRR_`)
  404 and are recorded UNKNOWN, not worked around. EURIBOR is the
  euro-area rate leg.
- BIS monthly series lag ~1 month (latest Oct 2026 at the Nov 26
  run); daily US/XM series run to Nov 24.
