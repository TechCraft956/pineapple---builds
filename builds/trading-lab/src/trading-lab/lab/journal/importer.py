"""Import trade executions from an unknown, variable prop-firm CSV/Excel export.

The platform's export schema is not under our control and changes without
notice (a column gets renamed, a broker migration reorders fields, a new
"order type" column appears). Rather than hardcode one schema, this module
*scores* each source column against known aliases for the fields we need and
builds the mapping at import time -- and it always hands that mapping back so
a human can see exactly what was guessed and override it, instead of trusting
a black box.

Two input shapes are handled, detected rather than configured:

* **fills** -- one row per execution (buy/sell), which must be paired into
  round turns. Pairing is FIFO per symbol: the oldest open lot is closed
  first, partial fills split across matches, and commission is attributed to
  each matched slice in proportion to the quantity it covers.
* **round_turns** -- the export already has one row per closed trade (an
  ``entry price`` / ``exit price`` pair). No pairing is needed; each row
  becomes one :class:`~lab.core.types.Trade` directly.

Platform symbols (``ESZ6``, ``/ES``, ``ES 12-26``, ...) are normalised to the
lab-canonical symbol via :func:`lab.core.instruments.get_instrument`. Anything
that cannot be mapped is *reported*, not dropped: it shows up in
:attr:`ImportResult.unmapped_symbols` and :attr:`ImportResult.warnings` so a
silent gap in the journal is never mistaken for a day with no trades.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from lab.core.instruments import get_instrument
from lab.core.types import ExitReason, LONG, SHORT, Trade

__all__ = [
    "ImportResult",
    "import_executions",
    "normalise_symbol",
    "infer_column_mapping",
]

# ---------------------------------------------------------------------------
# Column-mapping heuristics
# ---------------------------------------------------------------------------

#: Canonical field -> normalised alias strings we score source columns against.
#: Order does not matter; every field is scored against every column.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": (
        "timestamp", "time", "datetime", "date time", "fill time", "filled time",
        "execution time", "order time", "trade time", "transaction time", "date",
        "fill datetime",
    ),
    "entry_timestamp": (
        "entry time", "entry date", "open time", "opened time", "opened",
        "buy time", "entry timestamp", "entry datetime",
    ),
    "exit_timestamp": (
        "exit time", "exit date", "close time", "closed time", "closed",
        "sell time", "exit timestamp", "exit datetime",
    ),
    "symbol": ("symbol", "instrument", "contract", "ticker", "product", "market"),
    "side": (
        "side", "b s", "buy sell", "direction", "action", "order type",
        "buy sell type", "long short",
    ),
    "qty": (
        "qty", "quantity", "size", "contracts", "filled qty", "fill qty",
        "shares", "lots", "volume", "filled quantity",
    ),
    "price": (
        "price", "fill price", "avg price", "average price", "execution price",
        "avg fill price", "average fill price",
    ),
    "entry_price": ("entry price", "buy price", "open price", "avg entry price"),
    "exit_price": ("exit price", "sell price", "close price", "avg exit price"),
    "fee": ("fee", "fees", "commission", "comm", "commissions", "commission fee"),
    "pnl": (
        "pnl", "p l", "profit", "net pnl", "realized pnl", "realised pnl",
        "net profit", "profit loss", "gain loss",
    ),
}

_MAPPING_THRESHOLD = 0.6


def _normalise_colname(c: Any) -> str:
    """Lowercase, strip punctuation, collapse whitespace -- for fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(c).strip().lower()).strip()


def _score(col: str, alias: str) -> float:
    if not col or not alias:
        return 0.0
    if col == alias:
        return 1.0
    if alias in col or col in alias:
        return 0.85
    return SequenceMatcher(None, col, alias).ratio()


def _best_score(col: str, aliases: tuple[str, ...]) -> float:
    return max((_score(col, a) for a in aliases), default=0.0)


def infer_column_mapping(
    columns: Sequence[Any], *, threshold: float = _MAPPING_THRESHOLD
) -> dict[str, str]:
    """Score every source column against every known field's aliases.

    Returns ``{canonical_field: source_column}``. Assignment is greedy by
    descending score: exact-name matches (score 1.0) are always claimed before
    fuzzy ones, so a genuine ``"entry price"`` column is never stolen by the
    generic ``price`` field just because "price" is a substring of it. A field
    with no column scoring above ``threshold`` is simply absent from the
    mapping -- callers decide whether that is fatal.
    """
    norm_cols = {str(c): _normalise_colname(c) for c in columns}
    triples: list[tuple[float, str, str]] = []
    for field_name, aliases in FIELD_ALIASES.items():
        for col, norm in norm_cols.items():
            score = _best_score(norm, aliases)
            if score >= threshold:
                triples.append((score, field_name, col))
    # Highest score first; stable tie-break on field name keeps this deterministic.
    triples.sort(key=lambda t: (-t[0], t[1]))
    mapping: dict[str, str] = {}
    used_cols: set[str] = set()
    for _, field_name, col in triples:
        if field_name in mapping or col in used_cols:
            continue
        mapping[field_name] = col
        used_cols.add(col)
    return mapping


def _resolve_layout(mapping: dict[str, str], columns: Sequence[Any]) -> str:
    has_round_turn = all(
        f in mapping for f in ("entry_timestamp", "exit_timestamp", "entry_price", "exit_price")
    )
    has_fills = "timestamp" in mapping and "price" in mapping
    if has_round_turn:
        return "round_turn"
    if has_fills and "symbol" in mapping and "qty" in mapping:
        return "fills"
    raise ValueError(
        "could not confidently map this export's columns to a known execution "
        "schema.\n"
        f"columns seen: {list(columns)}\n"
        f"best-guess mapping so far: {mapping}\n"
        "Expected at least a timestamp, symbol, quantity and price column for a "
        "fills export, or entry_timestamp/exit_timestamp/entry_price/exit_price "
        "for a round-turn export. Rename the offending column(s) or pass a "
        "cleaned DataFrame instead."
    )


# ---------------------------------------------------------------------------
# Symbol normalisation
# ---------------------------------------------------------------------------

_MONTH_CODES = "FGHJKMNQUVXZ"
_MONTH_CODE_RE = re.compile(rf"^/?([A-Za-z]{{1,3}})[{_MONTH_CODES}]\d{{1,2}}$")
_LEADING_LETTERS_RE = re.compile(r"^/?([A-Za-z]{1,3})\b")


def normalise_symbol(raw: Any, symbol_map: Mapping[str, str] | None = None) -> str | None:
    """Map a platform symbol string to the lab-canonical symbol, or ``None``.

    Tries, in order: an explicit user-supplied override in ``symbol_map``; the
    raw text as-is (handles plain roots and the vendor-decoration suffixes
    :func:`~lab.core.instruments.get_instrument` already tolerates); stripping
    a leading ``/`` (continuous-contract notation, e.g. ``/ES``); stripping a
    futures month+year code (e.g. ``ESZ6`` -> ``ES``); and finally the leading
    letters of the string (handles ``"ES 12-26"``-style vendor formats).
    Returns ``None`` -- never raises -- when nothing resolves, so the caller
    can report it instead of the whole import blowing up on one bad row.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if symbol_map and text in symbol_map:
        text = symbol_map[text]

    candidates = [text, text.lstrip("/")]
    m = _MONTH_CODE_RE.match(text.upper())
    if m:
        candidates.append(m.group(1))
    m2 = _LEADING_LETTERS_RE.match(text)
    if m2:
        candidates.append(m2.group(1))

    for cand in candidates:
        if not cand:
            continue
        try:
            return get_instrument(cand).symbol
        except KeyError:
            continue
    return None


# ---------------------------------------------------------------------------
# Side / direction parsing
# ---------------------------------------------------------------------------

_SIDE_LONG = {
    "b", "buy", "bot", "bought", "long", "l", "cover", "buy to cover",
    "buy to open", "buy to close",
}
_SIDE_SHORT = {
    "s", "sell", "sld", "sold", "short", "sh", "sell short", "sell to open",
    "sell to close",
}


def _side_to_direction(val: Any) -> float:
    s = str(val).strip().lower()
    if s in _SIDE_LONG:
        return float(LONG)
    if s in _SIDE_SHORT:
        return float(SHORT)
    if "buy" in s or "long" in s:
        return float(LONG)
    if "sell" in s or "short" in s:
        return float(SHORT)
    return np.nan


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_frame(path_or_frame: "str | Path | pd.DataFrame") -> pd.DataFrame:
    if isinstance(path_or_frame, pd.DataFrame):
        return path_or_frame.copy()
    path = Path(path_or_frame)
    if not path.exists():
        raise FileNotFoundError(f"execution export not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in (".xlsx", ".xls"):
        try:
            return pd.read_excel(path)
        except ImportError as exc:
            raise ImportError(
                f"{path} is an Excel export but no Excel engine (e.g. openpyxl) "
                "is installed in this environment. Re-export as CSV, or install "
                "openpyxl."
            ) from exc
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    raise ValueError(
        f"unrecognised export format {suffix!r} for {path}; expected .csv, "
        ".xlsx/.xls, .parquet or .json"
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ImportResult:
    """Everything :func:`import_executions` produced, guessed mapping included.

    ``column_mapping`` is returned even on success so the caller can see and
    override what the heuristic decided -- "trust but verify" for a process
    that is, at its core, pattern-matching column names.
    """

    trades: list[Trade]
    column_mapping: dict[str, str]
    layout: str  # "fills" | "round_turn"
    n_source_rows: int
    n_rows_skipped: int
    unmapped_symbols: dict[str, int]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# fills -> round turns (FIFO)
# ---------------------------------------------------------------------------


def _pair_fills_fifo(
    df: pd.DataFrame,
    mapping: dict[str, str],
    symbol_map: Mapping[str, str] | None,
    default_strategy: str,
) -> tuple[list[Trade], dict[str, int], int]:
    ts_col, sym_col = mapping["timestamp"], mapping["symbol"]
    qty_col, price_col = mapping["qty"], mapping["price"]
    side_col = mapping.get("side")
    fee_col = mapping.get("fee")

    work = pd.DataFrame(
        {
            "ts_norm": pd.to_datetime(df[ts_col], utc=True, errors="coerce"),
            "symbol_raw": df[sym_col].astype(str).str.strip(),
            "qty_norm": pd.to_numeric(df[qty_col], errors="coerce"),
            "price_norm": pd.to_numeric(df[price_col], errors="coerce"),
            "fee_norm": pd.to_numeric(df[fee_col], errors="coerce").fillna(0.0)
            if fee_col
            else 0.0,
        }
    )
    if side_col:
        work["dir_norm"] = df[side_col].map(_side_to_direction)
    else:
        # No side column: fall back to signed quantity, which several
        # platforms use in place of an explicit buy/sell column.
        work["dir_norm"] = np.sign(work["qty_norm"])
        work["qty_norm"] = work["qty_norm"].abs()

    bad = (
        work["ts_norm"].isna()
        | work["price_norm"].isna()
        | work["qty_norm"].isna()
        | work["dir_norm"].isna()
        | (work["qty_norm"] <= 0)
    )
    n_skipped = int(bad.sum())
    work = work.loc[~bad].sort_values("ts_norm", kind="stable")

    trades: list[Trade] = []
    unmapped: dict[str, int] = {}

    for raw_symbol, grp in work.groupby("symbol_raw", sort=False):
        canonical = normalise_symbol(raw_symbol, symbol_map)
        if canonical is None:
            unmapped[raw_symbol] = unmapped.get(raw_symbol, 0) + len(grp)
            continue
        inst = get_instrument(canonical)
        queue: list[dict[str, Any]] = []  # homogeneous-direction FIFO open lots

        for row in grp.itertuples(index=False):
            ts, price, qty, direction, fee = (
                row.ts_norm, row.price_norm, row.qty_norm, row.dir_norm, row.fee_norm,
            )
            fee_per_unit = fee / qty if qty else 0.0
            remaining = float(qty)
            while remaining > 1e-9:
                if queue and queue[0]["direction"] != direction:
                    lot = queue[0]
                    matched = min(remaining, lot["qty"])
                    entry_commission = lot["fee_per_unit"] * matched
                    exit_commission = fee_per_unit * matched
                    pnl = (
                        lot["direction"] * (price - lot["price"]) * inst.point_value * matched
                        - entry_commission
                        - exit_commission
                    )
                    trades.append(
                        Trade(
                            symbol=canonical,
                            strategy=default_strategy,
                            direction=int(lot["direction"]),
                            entry_ts=lot["ts"],
                            entry_price=float(lot["price"]),
                            exit_ts=ts,
                            exit_price=float(price),
                            qty=matched,
                            pnl=float(pnl),
                            commission=float(entry_commission + exit_commission),
                            slippage_cost=0.0,
                            risk_dollars=0.0,
                            exit_reason=ExitReason.MANUAL,
                            meta={"symbol_raw": raw_symbol, "source": "importer_fifo"},
                        )
                    )
                    lot["qty"] -= matched
                    remaining -= matched
                    if lot["qty"] <= 1e-9:
                        queue.pop(0)
                else:
                    # Either the queue is empty, or this fill extends a
                    # same-direction position (scale-in): open/extend a lot.
                    queue.append(
                        {
                            "ts": ts, "price": float(price), "qty": remaining,
                            "direction": direction, "fee_per_unit": fee_per_unit,
                        }
                    )
                    remaining = 0.0

    return trades, unmapped, n_skipped


# ---------------------------------------------------------------------------
# already-paired round-turn rows
# ---------------------------------------------------------------------------


def _rows_to_trades_round_turn(
    df: pd.DataFrame,
    mapping: dict[str, str],
    symbol_map: Mapping[str, str] | None,
    default_strategy: str,
) -> tuple[list[Trade], dict[str, int], int]:
    if "symbol" not in mapping:
        raise ValueError(
            "round-turn export has no recognisable symbol column; "
            f"columns seen: {list(df.columns)}"
        )
    if "side" not in mapping and "qty" not in mapping:
        raise ValueError(
            "round-turn export has neither a side/direction column nor a "
            "quantity column to infer direction from a sign; "
            f"columns seen: {list(df.columns)}"
        )

    entry_ts = pd.to_datetime(df[mapping["entry_timestamp"]], utc=True, errors="coerce")
    exit_ts = pd.to_datetime(df[mapping["exit_timestamp"]], utc=True, errors="coerce")
    entry_price = pd.to_numeric(df[mapping["entry_price"]], errors="coerce")
    exit_price = pd.to_numeric(df[mapping["exit_price"]], errors="coerce")
    symbol_raw = df[mapping["symbol"]].astype(str).str.strip()

    if "qty" in mapping:
        qty = pd.to_numeric(df[mapping["qty"]], errors="coerce")
    else:
        qty = pd.Series(1.0, index=df.index)

    if "side" in mapping:
        direction = df[mapping["side"]].map(_side_to_direction)
    else:
        direction = np.sign(qty)
        qty = qty.abs()

    fee = (
        pd.to_numeric(df[mapping["fee"]], errors="coerce").fillna(0.0)
        if "fee" in mapping
        else pd.Series(0.0, index=df.index)
    )
    pnl_col = (
        pd.to_numeric(df[mapping["pnl"]], errors="coerce") if "pnl" in mapping else None
    )

    bad = (
        entry_ts.isna() | exit_ts.isna() | entry_price.isna() | exit_price.isna()
        | qty.isna() | direction.isna() | (qty <= 0)
    )
    n_skipped = int(bad.sum())

    trades: list[Trade] = []
    unmapped: dict[str, int] = {}

    for i in df.index[~bad]:
        raw_symbol = symbol_raw.loc[i]
        canonical = normalise_symbol(raw_symbol, symbol_map)
        if canonical is None:
            unmapped[raw_symbol] = unmapped.get(raw_symbol, 0) + 1
            continue
        inst = get_instrument(canonical)
        d = int(direction.loc[i])
        q = float(qty.loc[i])
        commission = float(fee.loc[i])
        if pnl_col is not None and pd.notna(pnl_col.loc[i]):
            pnl = float(pnl_col.loc[i])
        else:
            pnl = d * (exit_price.loc[i] - entry_price.loc[i]) * inst.point_value * q - commission
        trades.append(
            Trade(
                symbol=canonical,
                strategy=default_strategy,
                direction=d,
                entry_ts=entry_ts.loc[i],
                entry_price=float(entry_price.loc[i]),
                exit_ts=exit_ts.loc[i],
                exit_price=float(exit_price.loc[i]),
                qty=q,
                pnl=pnl,
                commission=commission,
                slippage_cost=0.0,
                risk_dollars=0.0,
                exit_reason=ExitReason.MANUAL,
                meta={"symbol_raw": raw_symbol, "source": "importer_round_turn"},
            )
        )

    return trades, unmapped, n_skipped


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------


def import_executions(
    path_or_frame: "str | Path | pd.DataFrame",
    symbol_map: Mapping[str, str] | None = None,
    *,
    default_strategy: str = "",
    mapping_threshold: float = _MAPPING_THRESHOLD,
) -> ImportResult:
    """Import a platform execution export into :class:`~lab.core.types.Trade` objects.

    ``path_or_frame`` may be a path to a CSV/Excel/Parquet/JSON export, or an
    already-loaded DataFrame. ``symbol_map`` overrides the automatic symbol
    normalisation for specific raw strings (``{"MY-ES-FUT": "ES"}``), checked
    before the built-in heuristics.

    Column mapping and row layout (fills vs. already-paired round turns) are
    both inferred; see module docstring. Every :class:`ImportResult` carries
    the inferred ``column_mapping`` and reports (never silently drops) rows it
    could not parse or symbols it could not resolve.
    """
    raw = _load_frame(path_or_frame)
    if raw.empty:
        raise ValueError("execution export has no rows")

    mapping = infer_column_mapping(list(raw.columns), threshold=mapping_threshold)
    layout = _resolve_layout(mapping, raw.columns)

    if layout == "round_turn":
        trades, unmapped, n_skipped = _rows_to_trades_round_turn(
            raw, mapping, symbol_map, default_strategy
        )
    else:
        trades, unmapped, n_skipped = _pair_fills_fifo(
            raw, mapping, symbol_map, default_strategy
        )

    warnings: list[str] = []
    if unmapped:
        warnings.append(
            "could not resolve symbol(s) to a known instrument -- excluded from "
            "trades, not silently dropped: "
            + ", ".join(f"{s!r} ({n} rows)" for s, n in sorted(unmapped.items()))
        )
    if n_skipped:
        warnings.append(
            f"{n_skipped} of {len(raw)} source rows had an unparseable "
            "timestamp/price/quantity/side and were excluded"
        )

    return ImportResult(
        trades=trades,
        column_mapping=mapping,
        layout=layout,
        n_source_rows=len(raw),
        n_rows_skipped=n_skipped,
        unmapped_symbols=unmapped,
        warnings=warnings,
    )
