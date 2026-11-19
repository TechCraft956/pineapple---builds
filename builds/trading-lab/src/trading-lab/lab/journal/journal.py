"""The append-only trade journal: one row per executed trade or skipped setup.

A backtest tells you what a rule *would* have done. The journal records what a
human actually did with it -- including the setups they saw and chose not to
take, because a journal that only records taken trades cannot measure
hesitation (see :func:`lab.journal.adherence.hesitation_analysis`).

Append-only, deliberately
--------------------------
History here is never mutated. Logging an amendment (a corrected note, a
flag you got wrong, a re-tagged setup) writes a **new row** with
``status="amendment"`` and ``amends_row_id`` pointing at the row it corrects;
the original row is untouched. This is the same principle
:class:`~lab.core.types.BacktestResult` follows with ``data_fingerprint`` --
silently rewriting old numbers after the fact is the fastest way to fool
yourself, and a trade journal is exactly the record you most need to trust.

Storage
-------
Parquet (``journal/entries.parquet``) is the source of truth; a CSV mirror
(``journal/entries.csv``) is written alongside it purely so a human can open
the journal in a spreadsheet and read it. The CSV is regenerated on every
write and is **not** read back automatically -- if you hand-edit it, call
:meth:`Journal.reload_from_csv` explicitly to promote those edits, so a stray
spreadsheet autocorrect can never silently rewrite the parquet history.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from lab.core.config import LAB_ROOT
from lab.core.instruments import get_instrument
from lab.core.types import Trade

__all__ = ["Journal", "JOURNAL_COLUMNS"]

#: Canonical column order. Every row -- executed, skipped or an amendment --
#: has exactly these columns; unused fields are "" (text) or NaN (numeric).
JOURNAL_COLUMNS: tuple[str, ...] = (
    "row_id", "logged_at", "trading_day", "status", "amends_row_id",
    "strategy", "version", "tag", "symbol", "direction",
    "signal_ts", "theoretical_entry",
    "entry_ts", "entry_price", "exit_ts", "exit_price", "qty",
    "pnl", "commission", "mfe", "mae",
    "slippage_ticks", "slippage_dollars",
    "in_plan", "model_approved",
    "adherence_flags", "emotional_state", "notes",
)

_TEXT_DEFAULTS = {
    "amends_row_id": "", "strategy": "", "version": "", "tag": "", "symbol": "",
    "adherence_flags": "{}", "emotional_state": "", "notes": "",
}


def _empty_row() -> dict[str, Any]:
    row: dict[str, Any] = {c: float("nan") for c in JOURNAL_COLUMNS}
    row.update(_TEXT_DEFAULTS)
    for ts_col in ("signal_ts", "entry_ts", "exit_ts"):
        row[ts_col] = pd.NaT
    row["in_plan"] = None
    row["model_approved"] = None
    return row


@dataclass(slots=True)
class Journal:
    """Append-only trade/skip ledger backed by ``journal/entries.parquet``.

    Parameters
    ----------
    root:
        Directory holding ``entries.parquet`` / ``entries.csv``. Defaults to
        ``<repo>/journal`` (matches ``LabConfig.journal_dir``'s default so a
        bare ``Journal()`` and the configured lab agree on where history
        lives without either module importing the other).
    """

    root: Path = LAB_ROOT / "journal"

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def parquet_path(self) -> Path:
        return self.root / "entries.parquet"

    @property
    def csv_path(self) -> Path:
        return self.root / "entries.csv"

    # ---- reading ----------------------------------------------------------

    def load(self) -> pd.DataFrame:
        """The full, append-only history. Empty (but correctly-shaped) if none yet."""
        if not self.parquet_path.exists():
            return pd.DataFrame(columns=list(JOURNAL_COLUMNS))
        return pd.read_parquet(self.parquet_path)

    def reload_from_csv(self) -> pd.DataFrame:
        """Promote hand-edits made to the CSV mirror into the parquet source of truth.

        Never called automatically -- the CSV is a read/annotate surface, not
        a second writer, until you explicitly say otherwise.
        """
        if not self.csv_path.exists():
            raise FileNotFoundError(f"no CSV mirror at {self.csv_path}")
        df = pd.read_csv(self.csv_path, parse_dates=["logged_at", "signal_ts", "entry_ts", "exit_ts"])
        for ts_col in ("logged_at", "signal_ts", "entry_ts", "exit_ts"):
            df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
        df.to_parquet(self.parquet_path, index=False)
        df.to_csv(self.csv_path, index=False)
        return df

    # ---- writing ------------------------------------------------------

    def _append_row(self, row: dict[str, Any]) -> str:
        df_row = pd.DataFrame([row], columns=list(JOURNAL_COLUMNS))
        existing = self.load()
        combined = pd.concat([existing, df_row], ignore_index=True) if len(existing) else df_row
        combined.to_parquet(self.parquet_path, index=False)
        combined.to_csv(self.csv_path, index=False)
        return str(row["row_id"])

    def log_trade(
        self,
        trade: Trade,
        *,
        version: str,
        tag: str = "",
        signal_ts: pd.Timestamp | None = None,
        theoretical_entry: float | None = None,
        in_plan: bool = True,
        model_approved: bool | None = None,
        adherence_flags: Mapping[str, bool] | None = None,
        emotional_state: str = "",
        notes: str = "",
    ) -> str:
        """Log one executed round turn. Returns the new row's ``row_id``.

        ``version`` is mandatory: a strategy without a version string cannot
        be told apart from the version it was before someone changed a rule,
        which defeats the entire point of a journal that reconciles intent
        against reality across strategy revisions.
        """
        from lab.core.sessions import trading_day  # local: keep import light

        row = _empty_row()
        row["row_id"] = uuid.uuid4().hex
        row["logged_at"] = pd.Timestamp.now(tz="UTC")
        row["trading_day"] = str(trading_day(trade.entry_ts))
        row["status"] = "executed"
        row["strategy"] = trade.strategy
        row["version"] = version
        row["tag"] = tag or trade.tag
        row["symbol"] = trade.symbol
        row["direction"] = float(trade.direction)
        row["signal_ts"] = trade.signal_ts if trade.signal_ts is not None else signal_ts
        row["theoretical_entry"] = theoretical_entry if theoretical_entry is not None else float("nan")
        row["entry_ts"] = trade.entry_ts
        row["entry_price"] = trade.entry_price
        row["exit_ts"] = trade.exit_ts
        row["exit_price"] = trade.exit_price
        row["qty"] = trade.qty
        row["pnl"] = trade.pnl
        row["commission"] = trade.commission
        row["mfe"] = trade.mfe
        row["mae"] = trade.mae

        if theoretical_entry is not None:
            inst = get_instrument(trade.symbol)
            slip_price = trade.direction * (trade.entry_price - theoretical_entry)
            row["slippage_ticks"] = inst.ticks(slip_price)
            row["slippage_dollars"] = inst.dollars(slip_price, trade.qty)

        row["in_plan"] = bool(in_plan)
        row["model_approved"] = None if model_approved is None else bool(model_approved)
        row["adherence_flags"] = json.dumps(dict(adherence_flags or {}))
        row["emotional_state"] = emotional_state
        row["notes"] = notes
        return self._append_row(row)

    def log_skipped(
        self,
        *,
        day: "str | pd.Timestamp",
        strategy: str,
        version: str,
        tag: str = "",
        symbol: str = "",
        direction: int | None = None,
        signal_ts: pd.Timestamp | None = None,
        theoretical_entry: float | None = None,
        reason: str = "",
        emotional_state: str = "",
        notes: str = "",
    ) -> str:
        """Log a valid setup that was deliberately passed on.

        This is the row type that makes hesitation visible: without it, the
        journal can only ever show trades that happened, and a system that
        quietly stops taking its own signals looks identical to a system with
        no signals at all.
        """
        row = _empty_row()
        row["row_id"] = uuid.uuid4().hex
        row["logged_at"] = pd.Timestamp.now(tz="UTC")
        row["trading_day"] = str(pd.Timestamp(day).date())
        row["status"] = "skipped"
        row["strategy"] = strategy
        row["version"] = version
        row["tag"] = tag
        row["symbol"] = symbol
        row["direction"] = float("nan") if direction is None else float(direction)
        row["signal_ts"] = signal_ts
        row["theoretical_entry"] = float("nan") if theoretical_entry is None else theoretical_entry
        row["emotional_state"] = emotional_state
        row["notes"] = (reason + ("\n" + notes if notes else "")).strip()
        return self._append_row(row)

    def amend(self, row_id: str, *, reason: str, **changes: Any) -> str:
        """Append a corrected copy of ``row_id``. The original is never touched.

        ``changes`` may set any journal column; anything unset is copied
        forward from the row being amended. ``reason`` is mandatory and is
        appended to the new row's notes, so the audit trail explains itself
        without cross-referencing a chat log.
        """
        df = self.load()
        match = df.loc[df["row_id"] == row_id]
        if match.empty:
            raise KeyError(f"no journal row with row_id {row_id!r}")
        original = match.iloc[-1].to_dict()
        new_row = {**original, **changes}
        new_row["row_id"] = uuid.uuid4().hex
        new_row["logged_at"] = pd.Timestamp.now(tz="UTC")
        new_row["status"] = "amendment"
        new_row["amends_row_id"] = row_id
        prior_notes = str(original.get("notes") or "")
        new_row["notes"] = (prior_notes + f"\n[amendment: {reason}]").strip()
        return self._append_row(new_row)

    # ---- querying -----------------------------------------------------

    def query(
        self,
        *,
        start: "str | pd.Timestamp | None" = None,
        end: "str | pd.Timestamp | None" = None,
        strategy: str | None = None,
        version: str | None = None,
        tag: str | None = None,
        status: str | None = None,
    ) -> pd.DataFrame:
        """General-purpose filter over the full history. All filters AND together."""
        df = self.load()
        if start is not None:
            df = df[df["trading_day"] >= str(pd.Timestamp(start).date())]
        if end is not None:
            df = df[df["trading_day"] <= str(pd.Timestamp(end).date())]
        if strategy is not None:
            df = df[df["strategy"] == strategy]
        if version is not None:
            df = df[df["version"] == version]
        if tag is not None:
            df = df[df["tag"] == tag]
        if status is not None:
            df = df[df["status"] == status]
        return df.reset_index(drop=True)

    def by_date_range(self, start: "str | pd.Timestamp", end: "str | pd.Timestamp") -> pd.DataFrame:
        return self.query(start=start, end=end)

    def by_strategy(self, strategy: str, version: str | None = None) -> pd.DataFrame:
        return self.query(strategy=strategy, version=version)

    def by_tag(self, tag: str) -> pd.DataFrame:
        return self.query(tag=tag)

    def by_adherence(self, flag: str, value: bool = True) -> pd.DataFrame:
        """Rows whose ``adherence_flags`` JSON has ``flag`` set to ``value``.

        Rows that never recorded that flag are excluded (neither true nor
        false is not the same as false).
        """
        df = self.load()

        def _matches(flags_json: Any) -> bool:
            if not isinstance(flags_json, str) or not flags_json:
                return False
            try:
                flags = json.loads(flags_json)
            except json.JSONDecodeError:
                return False
            return flag in flags and bool(flags[flag]) == value

        mask = df["adherence_flags"].apply(_matches)
        return df[mask].reset_index(drop=True)
