#!/usr/bin/env python3
"""FINRA margin debt collector — Pineapple sensor #103
(Wave 5 deficit sweep, 2026-11-26).

Why this sensor exists: the 100-sensor catalog has no margin-debt /
leverage gauge at all — no sensor covers how much investors owe
their brokers, a standard market-risk series. FINRA publishes it
monthly, free, keyless, as one XLSX:

    https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx

(One stable URL; FINRA overwrites the same file each month.)

The file is a plain .xlsx — a ZIP of XML — so it is parsed with
stdlib ``zipfile`` + ``xml.etree`` only. Columns, as published:

    Year-Month | Debit Balances in Customers' Securities Margin
                 Accounts | Free Credit Balances in Customers' Cash
                 Accounts | Free Credit Balances in Customers'
                 Securities Margin Accounts

Values are in $ millions, per FINRA's table. Rows before ~2000 carry
only the first three columns (no margin-account free-credit column);
the missing field is recorded as null, never zero-filled.

Labels
------
VERIFIED  row with a parseable month and debit balance.
REPORTED  row present but the debit balance is missing/unparseable.
UNKNOWN   the workbook could not be fetched or parsed at all.

Stdlib only. No credentials, no writes outside the output path given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

USER_AGENT = "Pineapple Research research@example.com"
FINRA_XLSX_URL = ("https://www.finra.org/sites/default/files/"
                  "2021-03/margin-statistics.xlsx")

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _cell_text(cell: ET.Element, strings: list[str]) -> str | None:
    kind = cell.get("t")
    if kind == "s":
        val = cell.find("m:v", NS)
        if val is None or val.text is None:
            return None
        try:
            return strings[int(val.text)]
        except (ValueError, IndexError):
            return None
    if kind == "inlineStr":
        inline = cell.find("m:is", NS)
        if inline is None:
            return None
        return "".join(inline.itertext()) or None
    val = cell.find("m:v", NS)
    if val is None:
        return None
    return val.text


def parse_margin_xlsx(data: bytes) -> tuple[list[dict], str]:
    """Parse the FINRA margin-statistics workbook bytes into rows.

    Returns (rows, status). Each row: {date, debit_balances_m,
    free_credit_cash_m, free_credit_margin_m, label}."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        shared = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        strings = ["".join(item.itertext())
                   for item in shared.findall("m:si", NS)]
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        return [], f"ERROR_{type(exc).__name__}"
    rows: list[dict] = []
    sheet_rows = sheet.findall("m:sheetData/m:row", NS)
    if not sheet_rows:
        return [], "ERROR_NO_ROWS"
    for row in sheet_rows[1:]:  # first row is the header
        cells = [_cell_text(c, strings) for c in row.findall("m:c", NS)]
        if not cells or not cells[0]:
            continue
        date = cells[0].strip()

        def _num(text: str | None) -> float | None:
            if text is None:
                return None
            try:
                return float(text.replace(",", "").strip())
            except ValueError:
                return None

        debit = _num(cells[1]) if len(cells) > 1 else None
        cash = _num(cells[2]) if len(cells) > 2 else None
        margin = _num(cells[3]) if len(cells) > 3 else None
        rows.append({
            "date": date,
            "debit_balances_m": debit,
            "free_credit_cash_m": cash,
            "free_credit_margin_m": margin,
            "label": "VERIFIED" if debit is not None else "REPORTED",
        })
    return rows, "OK"


def fetch_workbook(url: str = FINRA_XLSX_URL,
                   timeout: int = 30) -> tuple[bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), "OK"
    except urllib.error.HTTPError as exc:
        return None, f"HTTP_{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"ERROR_{type(exc).__name__}"


def collect(months: int = 12, url: str = FINRA_XLSX_URL) -> dict:
    run_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data, status = fetch_workbook(url)
    if data is None:
        return {
            "sensor": "103",
            "name": "FINRA margin debt (deficit sweep)",
            "run_utc": run_utc,
            "source": url,
            "fetch_status": status,
            "observations": [],
            "summary": {"observations_total": 0, "verified": 0,
                        "reported": 0, "history_rows": 0,
                        "note": "workbook fetch failed"},
        }
    rows, parse_status = parse_margin_xlsx(data)
    # The workbook lists newest first; sort ascending so "recent" is
    # actually recent and "latest" is the newest month.
    rows.sort(key=lambda r: r["date"])
    recent = rows[-months:] if months > 0 else rows
    verified = sum(1 for r in recent if r["label"] == "VERIFIED")
    return {
        "sensor": "103",
        "name": "FINRA margin debt (deficit sweep)",
        "run_utc": run_utc,
        "source": url,
        "fetch_status": parse_status,
        "observations": recent,
        "summary": {
            "observations_total": len(recent),
            "verified": verified,
            "reported": len(recent) - verified,
            "history_rows": len(rows),
            "latest": recent[-1] if recent else None,
            "unit": "$ millions, as published by FINRA",
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Collect FINRA margin debt (sensor #103).")
    ap.add_argument("--out", default=None,
                    help="Write result JSON here (default: stdout).")
    ap.add_argument("--months", type=int, default=12,
                    help="Recent months to emit (default 12).")
    ap.add_argument("--url", default=FINRA_XLSX_URL,
                    help="Workbook URL override (default: FINRA).")
    args = ap.parse_args(argv)
    result = collect(months=args.months, url=args.url)
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}: "
              f"{result['summary']['observations_total']} observations "
              f"({result['fetch_status']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
