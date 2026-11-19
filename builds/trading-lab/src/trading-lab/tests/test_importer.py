"""Tests for lab.journal.importer: column-mapping heuristics, FIFO pairing,
round-turn detection, and symbol normalisation."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.journal.importer import (
    ImportResult,
    import_executions,
    infer_column_mapping,
    normalise_symbol,
)

# ---------------------------------------------------------------------------
# Three different plausible column layouts for the same two fills
# (buy 1 ES @ 4500.00, sell 1 ES @ 4502.00, $2.00 commission per side).
# ---------------------------------------------------------------------------

LAYOUT_A = """Time,Symbol,Side,Qty,Price,Commission
2026-08-03 13:31:00,ES,Buy,1,4500.00,2.00
2026-08-03 13:45:00,ES,Sell,1,4502.00,2.00
"""

LAYOUT_B = """fill_datetime,Contract,B/S,Filled Qty,Fill Price,Fees
2026-08-03T13:31:00Z,ESZ6,B,1,4500.00,2.00
2026-08-03T13:45:00Z,ESZ6,S,1,4502.00,2.00
"""

LAYOUT_C = """Execution Time,Instrument,Action,Size,Avg Fill Price,Commission Fee
2026-08-03 08:31:00-05:00,/ES,Buy to Open,1,4500.00,2.00
2026-08-03 08:45:00-05:00,/ES,Sell to Close,1,4502.00,2.00
"""

EXPECTED_PNL = 1 * (4502.00 - 4500.00) * 50.0 - 4.00  # point_value=50, total commission=4


@pytest.mark.parametrize("layout_csv", [LAYOUT_A, LAYOUT_B, LAYOUT_C], ids=["layout_a", "layout_b", "layout_c"])
def test_three_layouts_map_and_pair_correctly(tmp_path, layout_csv):
    path = tmp_path / "export.csv"
    path.write_text(layout_csv)

    result = import_executions(path)

    assert isinstance(result, ImportResult)
    assert result.layout == "fills"
    # every essential field must have been mapped to *some* source column
    for field in ("timestamp", "symbol", "side", "qty", "price"):
        assert field in result.column_mapping, result.column_mapping

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.symbol == "ES"
    assert trade.qty == 1
    assert trade.commission == pytest.approx(4.00)
    assert trade.pnl == pytest.approx(EXPECTED_PNL)
    assert not result.unmapped_symbols


def test_mapping_is_returned_for_inspection_and_override():
    mapping = infer_column_mapping(["Fill Time", "Contract", "Buy/Sell", "Filled Qty", "Fill Price", "Comm"])
    assert mapping["timestamp"] == "Fill Time"
    assert mapping["symbol"] == "Contract"
    assert mapping["qty"] == "Filled Qty"
    assert mapping["price"] == "Fill Price"


def test_ambiguous_export_raises_clear_error(tmp_path):
    path = tmp_path / "junk.csv"
    path.write_text("col1,col2,col3\n1,2,3\n")
    with pytest.raises(ValueError) as exc_info:
        import_executions(path)
    msg = str(exc_info.value)
    assert "col1" in msg and "col2" in msg and "col3" in msg  # lists the columns it saw


# ---------------------------------------------------------------------------
# FIFO pairing: scale-in then scale-out, commission attributed to the cent.
# ---------------------------------------------------------------------------


def test_fifo_pairing_scale_in_and_scale_out(tmp_path):
    # Two buys (scale-in) at different prices, then two sells (scale-out).
    csv = """Time,Symbol,Side,Qty,Price,Commission
2026-08-03 13:30:00,ES,Buy,1,4500.00,2.00
2026-08-03 13:31:00,ES,Buy,1,4501.00,2.00
2026-08-03 13:40:00,ES,Sell,1,4505.00,2.00
2026-08-03 13:41:00,ES,Sell,1,4506.00,2.00
"""
    path = tmp_path / "scale.csv"
    path.write_text(csv)

    result = import_executions(path)
    assert result.layout == "fills"
    assert len(result.trades) == 2  # FIFO: each entry lot pairs with its own exit slice

    t1, t2 = sorted(result.trades, key=lambda t: t.entry_price)

    # FIFO: oldest lot (4500) is closed first, against the first sell (4505).
    assert t1.entry_price == pytest.approx(4500.00)
    assert t1.exit_price == pytest.approx(4505.00)
    assert t1.commission == pytest.approx(4.00)  # 2.00 entry + 2.00 exit
    assert t1.pnl == pytest.approx((4505 - 4500) * 50 - 4.00)

    assert t2.entry_price == pytest.approx(4501.00)
    assert t2.exit_price == pytest.approx(4506.00)
    assert t2.commission == pytest.approx(4.00)
    assert t2.pnl == pytest.approx((4506 - 4501) * 50 - 4.00)

    # total commission attributed across trades == total commission paid on the fills
    total_input_commission = 2.00 + 2.00 + 2.00 + 2.00
    assert sum(t.commission for t in result.trades) == pytest.approx(total_input_commission)


def test_fifo_pairing_partial_fill_within_one_exit(tmp_path):
    # Buy 2 in one fill, then two separate partial sells (scale-out from one lot).
    csv = """Time,Symbol,Side,Qty,Price,Commission
2026-08-03 13:30:00,ES,Buy,2,4500.00,4.00
2026-08-03 13:40:00,ES,Sell,1,4503.00,2.00
2026-08-03 13:41:00,ES,Sell,1,4506.00,2.00
"""
    path = tmp_path / "partial.csv"
    path.write_text(csv)

    result = import_executions(path)
    assert len(result.trades) == 2
    t1, t2 = sorted(result.trades, key=lambda t: t.exit_price)

    # entry commission (4.00 total / 2 contracts = 2.00/unit) split across both exits
    assert t1.commission == pytest.approx(2.00 + 2.00)  # 1 unit entry + its exit fee
    assert t2.commission == pytest.approx(2.00 + 2.00)
    assert t1.qty == 1 and t2.qty == 1
    total_input_commission = 4.00 + 2.00 + 2.00
    assert sum(t.commission for t in result.trades) == pytest.approx(total_input_commission)


# ---------------------------------------------------------------------------
# Already-paired round-turn export
# ---------------------------------------------------------------------------


def test_round_turn_export_detected_and_parsed(tmp_path):
    csv = """Entry Time,Exit Time,Symbol,Side,Qty,Entry Price,Exit Price,Commission,Net PnL
2026-08-03 13:30:00,2026-08-03 13:45:00,ES,Long,1,4500.00,4502.00,4.00,96.00
2026-08-03 14:00:00,2026-08-03 14:10:00,ES,Short,2,4510.00,4508.00,8.00,192.00
"""
    path = tmp_path / "round_turns.csv"
    path.write_text(csv)

    result = import_executions(path)
    assert result.layout == "round_turn"
    assert len(result.trades) == 2

    long_trade = next(t for t in result.trades if t.direction == 1)
    assert long_trade.pnl == pytest.approx(96.00)  # pnl column is authoritative when present
    short_trade = next(t for t in result.trades if t.direction == -1)
    assert short_trade.qty == 2
    assert short_trade.pnl == pytest.approx(192.00)


# ---------------------------------------------------------------------------
# Symbol normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ESZ6", "ES"),
        ("/ES", "ES"),
        ("ES 12-26", "ES"),
        ("ES", "ES"),
        ("MESZ6", "MES"),
        ("CL1!", "CL"),
    ],
)
def test_normalise_symbol_variants(raw, expected):
    assert normalise_symbol(raw) == expected


def test_normalise_symbol_uses_explicit_override():
    assert normalise_symbol("MY-CUSTOM-ES", {"MY-CUSTOM-ES": "ES"}) == "ES"


def test_unmapped_symbol_is_reported_not_dropped(tmp_path):
    csv = """Time,Symbol,Side,Qty,Price,Commission
2026-08-03 13:30:00,ZW,Buy,1,650.00,2.00
2026-08-03 13:45:00,ZW,Sell,1,652.00,2.00
"""
    path = tmp_path / "unknown.csv"
    path.write_text(csv)

    result = import_executions(path)
    assert result.trades == []
    assert result.unmapped_symbols == {"ZW": 2}
    assert any("ZW" in w for w in result.warnings)


def test_accepts_dataframe_directly():
    df = pd.DataFrame(
        {
            "Time": ["2026-08-03 13:31:00", "2026-08-03 13:45:00"],
            "Symbol": ["ES", "ES"],
            "Side": ["Buy", "Sell"],
            "Qty": [1, 1],
            "Price": [4500.00, 4502.00],
            "Commission": [2.00, 2.00],
        }
    )
    result = import_executions(df)
    assert len(result.trades) == 1
