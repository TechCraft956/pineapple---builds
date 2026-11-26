# Corporate events & 8-K calendar — sensor #60 (`events_8k.py`)

## What it does

1. **Market-wide leg** — the SEC daily master index for the last N
   days, filtered to 8-K / 8-K/A filings. Every 8-K is listed with
   company, CIK, filing date and accession.
2. **Item leg** — up to `--max-items` (default 20) 8-K filing texts
   are fetched and their Item numbers extracted (1.01 material
   agreement, 2.01 acquisition, 2.02 results, 2.03 debt, 5.02
   executive changes, 7.01 Regulation FD, 8.01 other events, 9.01
   exhibits, etc.). Items are taken from the filing text as filed;
   the collector does not interpret them.
3. **Watchlist leg** — submissions JSON for the same 12-name seed
   list as #18, recent 8-K filings per name.

## Run

```sh
python3 events_8k.py --days 5 --max-items 20 --out evidence/events_8k_run_20261126.json
```

## Live evidence (2026-11-26)

683 8-K filings (Nov 23–25: 245 / 253 / 185). 20 parsed for items:
9.01 ×12, 1.01 ×5, 7.01 ×5, 8.01 ×4, 5.02 ×4, 2.03 ×3, 2.02 ×2,
3.02 ×2, 3.03 ×2, 5.03 ×1. Watchlist: 60 recent 8-Ks.

## Caveats

- Item numbers are NOT in the master index or the submissions JSON —
  an 8-K whose text was not fetched (cap hit or fetch failure) is
  listed with items UNKNOWN, never guessed.
- The 8-K item parser searches up to 250k chars of the filing text:
  real 8-K .txt files are mostly HTML/CSS boilerplate (a 650 KB
  filing had its first item heading past 30k chars); the first
  version's 6k window found zero items in all 20 parsed filings.
- An 8-K/A amendment's items are whatever the amendment text says.
