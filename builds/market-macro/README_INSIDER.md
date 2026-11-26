# Insider buying, 13F, SEC filings — sensor #18 (`insider.py`)

## What it does

Two legs, both keyless via the shared EDGAR client:

1. **Market-wide leg** — the SEC daily master index for the last N
   days (`--days`, default 5). Every Form 4 (insider trades), 13F-HR
   (institutional holdings) and 13D/G filing is counted; up to
   `--max-form4` (default 25) Form 4 ownership-document XMLs are
   parsed into transactions (owner, buy/sell code, shares, price).
2. **Watchlist leg** — submissions JSON for 12 large-cap CIKs
   (AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, XOM, WMT, BRK,
   UNH — a seed list, not exhaustive coverage). Recent Form 4 and
   13F-HR filings per name.

Form 4 codes: P = open-market purchase, S = open-market sale,
A = grant/award, M = option exercise, G = gift, F = tax withholding,
D = disposition. Only P/S with a parsed price count as market trades
in the summary; all codes are listed as filed.

## Run

```sh
python3 insider.py --days 5 --max-form4 25 --out evidence/insider_run_20261126.json
```

## Live evidence (2026-11-26)

3,928 observations. Form 4 filings Nov 23–25: 1,347 / 1,389 / 1,140;
37 13F-HR filings in the window. 52 insider transactions parsed
from 25 Form 4 XMLs (11 buys P, 25 sells S, rest F/D/M). Watchlist:
120 recent Form 4 / 13F-HR filings across the 12 names. Nov 26
index not yet posted (HTTP 403, UNKNOWN); Nov 22 was a Sunday
(no index).

## Caveats

- The index lists filings, not transaction detail — detail exists
  only for the parsed subset. Unparsed filings are counted, never
  invented.
- 13F holdings detail (the information table) is NOT parsed in v1;
  13F-HR filings are recorded at filing level.
- Same-day runs see no index yet (posted end-of-day).
