"""Tests for lab.data.cache.BarCache: round-trip, gap-only refetch, dedupe,
and corrupt-file handling. All I/O happens under pytest's tmp_path -- never
the repo's real data/ directory."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from lab.data.cache import BarCache


def _bars(start: str, n: int, *, freq: str = "1h", price0: float = 5000.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    closes = [price0 + i for i in range(n)]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [100.0] * n,
        },
        index=idx,
    )
    df.index.name = "ts"
    return df


@pytest.fixture
def cache(tmp_path: Path) -> BarCache:
    return BarCache(root=tmp_path)


def test_write_read_round_trip(cache: BarCache) -> None:
    bars = _bars("2024-01-02", 24)
    meta = cache.write("ES", "1h", bars, source="test")

    out = cache.read("ES", "1h")
    pd.testing.assert_frame_equal(out[list(bars.columns)], bars, check_freq=False)
    assert meta.row_count == 24
    assert meta.symbol == "ES" and meta.timeframe == "1h"
    assert cache.path_for("ES", "1h").exists()
    assert cache.meta_path_for("ES", "1h").exists()

    reloaded_meta = cache.meta("ES", "1h")
    assert reloaded_meta is not None
    assert reloaded_meta.fingerprint == meta.fingerprint


def test_read_missing_symbol_returns_empty_frame(cache: BarCache) -> None:
    out = cache.read("NQ", "1h")
    assert len(out) == 0
    assert isinstance(out.index, pd.DatetimeIndex)
    assert str(out.index.tz) == "UTC"
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]


def test_missing_ranges_empty_cache_wants_full_span(cache: BarCache) -> None:
    start = pd.Timestamp("2024-01-02", tz="UTC")
    end = pd.Timestamp("2024-01-03", tz="UTC")
    assert cache.missing_ranges("ES", "1h", start, end) == [(start, end)]


def test_missing_ranges_only_asks_for_the_gap(cache: BarCache) -> None:
    day1 = _bars("2024-01-02", 24)  # covers 2024-01-02 00:00 -> 2024-01-02 23:00
    cache.write("ES", "1h", day1, source="test")

    wider_end = pd.Timestamp("2024-01-04", tz="UTC")
    gaps = cache.missing_ranges("ES", "1h", pd.Timestamp("2024-01-02", tz="UTC"), wider_end)

    # cache already covers the requested start, so the only gap is the tail
    # past the last cached bar -- a fetch should never re-ask for day1.
    assert len(gaps) == 1
    g_start, g_end = gaps[0]
    assert g_start == day1.index[-1]
    assert g_end == wider_end

    # covering the whole requested window (including before the cache) should
    # produce a gap only on that earlier edge, on top of the tail gap.
    earlier_start = pd.Timestamp("2024-01-01", tz="UTC")
    gaps2 = cache.missing_ranges("ES", "1h", earlier_start, wider_end)
    assert len(gaps2) == 2
    assert gaps2[0] == (earlier_start, day1.index[0])
    assert gaps2[1] == (day1.index[-1], wider_end)

    # a request fully inside the cached span needs nothing at all.
    assert cache.missing_ranges("ES", "1h", day1.index[2], day1.index[5]) == []


def test_append_is_idempotent_and_dedupes_on_overlap(cache: BarCache) -> None:
    first = _bars("2024-01-02", 12, price0=5000.0)
    cache.append("ES", "1h", first, source="test")

    # second batch overlaps the last 4 bars of `first` with *different* close
    # prices -- simulating a vendor correction on a re-fetch -- plus 8 new bars.
    second = _bars("2024-01-02 08:00", 12, price0=9999.0)
    meta = cache.append("ES", "1h", second, source="test")

    out = cache.read("ES", "1h")
    assert meta.row_count == 20  # 12 + 12 - 4 overlapping
    assert len(out) == 20
    assert not out.index.duplicated().any()
    assert out.index.is_monotonic_increasing

    # the overlapping timestamps must carry the *newer* append's values.
    overlap_ts = second.index[0]
    assert out.loc[overlap_ts, "close"] == second.loc[overlap_ts, "close"]

    # calling append again with the exact same second batch changes nothing.
    meta2 = cache.append("ES", "1h", second, source="test")
    assert meta2.row_count == meta.row_count
    assert meta2.fingerprint == meta.fingerprint


def test_append_with_empty_frame_is_a_noop(cache: BarCache) -> None:
    bars = _bars("2024-01-02", 5)
    cache.write("ES", "1h", bars, source="test")
    empty = bars.iloc[0:0]
    cache.append("ES", "1h", empty, source="test")
    out = cache.read("ES", "1h")
    assert len(out) == 5


def test_corrupt_parquet_file_is_quarantined_not_raised(cache: BarCache, tmp_path: Path) -> None:
    bars = _bars("2024-01-02", 5)
    cache.write("ES", "1h", bars, source="test")
    path = cache.path_for("ES", "1h")
    path.write_bytes(b"not a parquet file, definitely not")

    with pytest.warns(UserWarning, match="corrupt|failed to read"):
        out = cache.read("ES", "1h")

    assert len(out) == 0
    # the bad file should be moved aside, not left in place to break the next read.
    assert not path.exists()
    quarantined = list((tmp_path / "ES").glob("1h.corrupt-*.parquet"))
    assert len(quarantined) == 1

    # cache is usable again after quarantine -- a fresh write just works.
    cache.write("ES", "1h", bars, source="test")
    out2 = cache.read("ES", "1h")
    assert len(out2) == 5


def test_clear_single_timeframe_leaves_others(cache: BarCache) -> None:
    bars = _bars("2024-01-02", 5)
    cache.write("ES", "1h", bars, source="test")
    cache.write("ES", "1d", bars, source="test")
    cache.clear("ES", "1h")
    assert len(cache.read("ES", "1h")) == 0
    assert len(cache.read("ES", "1d")) == 5


def test_clear_all_timeframes_for_symbol(cache: BarCache) -> None:
    bars = _bars("2024-01-02", 5)
    cache.write("ES", "1h", bars, source="test")
    cache.write("ES", "1d", bars, source="test")
    cache.clear("ES")
    assert len(cache.read("ES", "1h")) == 0
    assert len(cache.read("ES", "1d")) == 0
