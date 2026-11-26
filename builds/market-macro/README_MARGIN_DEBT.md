# FINRA margin debt — sensor #103 (`margin_debt.py`)

Wave 5 deficit-sweep addition (2026-11-26).

## Why it exists

The 100-sensor catalog had no margin-debt / leverage gauge at all —
no sensor covered how much investors owe their brokers, a standard
market-risk series. FINRA publishes it monthly, free, keyless, as
one XLSX that it overwrites in place:

```
https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx
```

## What it does

Fetches the workbook and parses it with stdlib `zipfile` +
`xml.etree` (an .xlsx is a ZIP of XML). Columns as published:

- Year-Month
- Debit Balances in Customers' Securities Margin Accounts
- Free Credit Balances in Customers' Cash Accounts
- Free Credit Balances in Customers' Securities Margin Accounts

Values are in $ millions, per FINRA's table. Rows before ~2000
carry only the first three columns; the missing margin free-credit
field is recorded as null, never zero-filled. The workbook lists
newest first; the collector sorts ascending before taking the
recent window.

## Run

```sh
python3 margin_debt.py --months 12 --out evidence/margin_debt_run_20261126.json
```

## Live evidence (2026-11-26)

358 monthly rows (Jan 1997 – Oct 2026). Latest Oct 2026: margin
debit $1,448,360M, free credit cash $210,290M, free credit margin
$212,890M. Nov 2025 debit was $1,214,321M (12-month window).

## Caveats

- One file, overwritten monthly — there is no per-vintage archive
  in the URL; the collector records the run date with the data.
- The 2021-03 path segment is the file's upload path, not the data
  vintage; the contents are current (Oct 2026 at the Nov 26 run).
