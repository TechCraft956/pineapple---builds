"""Tests for lab.journal.journal: append-only ledger semantics and queries."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from lab.core.types import ExitReason, Trade
from lab.journal.journal import JOURNAL_COLUMNS, Journal


def _make_trade(**overrides) -> Trade:
    defaults = dict(
        symbol="ES", strategy="asia_sweep", direction=1,
        entry_ts=pd.Timestamp("2026-08-03 13:31:00", tz="UTC"), entry_price=4500.25,
        exit_ts=pd.Timestamp("2026-08-03 13:50:00", tz="UTC"), exit_price=4505.00,
        qty=1.0, pnl=232.5, commission=4.0, slippage_cost=0.0, risk_dollars=100.0,
        exit_reason=ExitReason.TARGET, mfe=250.0, mae=-25.0, tag="asia_high_sweep",
    )
    defaults.update(overrides)
    return Trade(**defaults)


def test_log_trade_round_trips_through_parquet_and_csv(tmp_path):
    journal = Journal(tmp_path)
    row_id = journal.log_trade(
        _make_trade(), version="v1", theoretical_entry=4500.00,
        adherence_flags={"sized_per_plan": True}, notes="clean execution",
    )
    assert journal.parquet_path.exists()
    assert journal.csv_path.exists()

    df = journal.load()
    assert list(df.columns) == list(JOURNAL_COLUMNS)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["row_id"] == row_id
    assert row["status"] == "executed"
    assert row["strategy"] == "asia_sweep"
    assert row["version"] == "v1"
    assert row["symbol"] == "ES"
    assert row["pnl"] == pytest.approx(232.5)
    # slippage: entry filled 0.25 above theoretical, long -> adverse, 1 tick (ES tick=0.25)
    assert row["slippage_ticks"] == pytest.approx(1.0)
    assert json.loads(row["adherence_flags"]) == {"sized_per_plan": True}

    csv_df = pd.read_csv(journal.csv_path)
    assert len(csv_df) == 1
    assert csv_df.iloc[0]["row_id"] == row_id


def test_log_skipped_records_a_deliberate_pass(tmp_path):
    journal = Journal(tmp_path)
    journal.log_skipped(
        day="2026-08-03", strategy="asia_sweep", version="v1", symbol="ES",
        direction=1, reason="already at daily loss lock",
    )
    df = journal.load()
    assert len(df) == 1
    assert df.iloc[0]["status"] == "skipped"
    assert "daily loss lock" in df.iloc[0]["notes"]


def test_append_only_amendment_never_mutates_original(tmp_path):
    journal = Journal(tmp_path)
    row_id = journal.log_trade(_make_trade(), version="v1", emotional_state="calm")

    new_id = journal.amend(row_id, reason="mis-tagged setup on entry", tag="corrected_tag")

    df = journal.load()
    assert len(df) == 2  # original row is never removed or rewritten
    original_row = df[df["row_id"] == row_id].iloc[0]
    amended_row = df[df["row_id"] == new_id].iloc[0]

    assert original_row["tag"] == "asia_high_sweep"  # untouched
    assert original_row["status"] == "executed"
    assert amended_row["status"] == "amendment"
    assert amended_row["amends_row_id"] == row_id
    assert amended_row["tag"] == "corrected_tag"
    assert "mis-tagged setup on entry" in amended_row["notes"]
    # fields not part of the amendment are carried forward from the original
    assert amended_row["symbol"] == "ES"
    assert amended_row["pnl"] == pytest.approx(232.5)


def test_amend_unknown_row_id_raises(tmp_path):
    journal = Journal(tmp_path)
    with pytest.raises(KeyError):
        journal.amend("does-not-exist", reason="x")


def test_query_helpers_filter_correctly(tmp_path):
    journal = Journal(tmp_path)
    journal.log_trade(
        _make_trade(strategy="asia_sweep", entry_ts=pd.Timestamp("2026-08-01 13:00", tz="UTC"),
                    exit_ts=pd.Timestamp("2026-08-01 13:10", tz="UTC")),
        version="v1", tag="a",
    )
    journal.log_trade(
        _make_trade(strategy="asia_sweep", entry_ts=pd.Timestamp("2026-08-05 13:00", tz="UTC"),
                    exit_ts=pd.Timestamp("2026-08-05 13:10", tz="UTC")),
        version="v2", tag="b",
    )
    journal.log_trade(
        _make_trade(strategy="london_break", entry_ts=pd.Timestamp("2026-08-05 06:00", tz="UTC"),
                    exit_ts=pd.Timestamp("2026-08-05 06:10", tz="UTC")),
        version="v1", tag="a",
        adherence_flags={"sized_per_plan": False},
    )

    assert len(journal.by_strategy("asia_sweep")) == 2
    assert len(journal.by_strategy("asia_sweep", version="v2")) == 1
    assert len(journal.by_tag("a")) == 2
    assert len(journal.by_date_range("2026-08-04", "2026-08-06")) == 2
    assert len(journal.by_date_range("2026-07-01", "2026-07-31")) == 0

    flagged = journal.by_adherence("sized_per_plan", value=False)
    assert len(flagged) == 1
    assert flagged.iloc[0]["strategy"] == "london_break"
    assert len(journal.by_adherence("sized_per_plan", value=True)) == 0


def test_load_on_fresh_journal_is_empty_with_correct_shape(tmp_path):
    journal = Journal(tmp_path / "does" / "not" / "exist" / "yet")
    df = journal.load()
    assert len(df) == 0
    assert list(df.columns) == list(JOURNAL_COLUMNS)
