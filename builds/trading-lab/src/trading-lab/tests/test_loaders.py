"""``load_bars`` — the one entry point every other module uses for bars.

The properties worth pinning here are economic, not cosmetic: the free tier
meters bulk history, so "does a second call re-download anything" is a question
with a bill attached. And the quality gate has to fire on the frames that would
otherwise silently produce a beautiful backtest.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from lab.core.config import LabConfig
from lab.data.loaders import DataQualityError, align, load_bars, load_local


class RecordingSource:
    """A ``MarketDataSource`` double that serves a fixed frame and counts calls."""

    def __init__(self, bars: pd.DataFrame):
        self.bars = bars
        self.calls: list[tuple] = []

    def candles(self, symbol, timeframe, start=None, end=None, limit=None, order=None):
        self.calls.append((symbol, timeframe, start, end))
        df = self.bars
        if start is not None:
            df = df.loc[df.index >= start]
        if end is not None:
            df = df.loc[df.index <= end]
        return df.copy()


def make_bars(n: int = 600, start: str = "2026-01-05 00:00", freq: str = "1min") -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC", name="ts")
    close = 5000 + np.cumsum(np.repeat(0.25, n)) % 20
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 100.0),
        },
        index=idx,
    )


@pytest.fixture
def cfg(tmp_path) -> LabConfig:
    return LabConfig(root=tmp_path, data_dir=tmp_path / "data", results_dir=tmp_path / "results").ensure_dirs()


def test_first_call_fetches_and_second_call_does_not(cfg):
    bars = make_bars()
    src = RecordingSource(bars)
    window = dict(start=bars.index[0], end=bars.index[-1])

    first = load_bars("ES", "1m", cfg=cfg, source=src, **window)
    assert len(first) == len(bars)
    assert len(src.calls) >= 1

    calls_after_first = len(src.calls)
    second = load_bars("ES", "1m", cfg=cfg, source=src, **window)

    # The whole point of cache-first: a repeat of an already-cached window
    # costs nothing. The free tier meters bulk exports, so a loader that
    # re-fetches is not merely slow, it burns quota.
    assert len(src.calls) == calls_after_first
    pd.testing.assert_frame_equal(first[list("open high low close volume".split())],
                                  second[list("open high low close volume".split())])


def test_extending_the_window_fetches_only_the_new_edge(cfg):
    bars = make_bars(600)
    src = RecordingSource(bars)

    load_bars("ES", "1m", start=bars.index[0], end=bars.index[299], cfg=cfg, source=src)
    src.calls.clear()

    load_bars("ES", "1m", start=bars.index[0], end=bars.index[-1], cfg=cfg, source=src)

    assert len(src.calls) == 1
    _, _, gap_start, _ = src.calls[0]
    # The refetch starts at the cached edge, not at the beginning of history.
    assert gap_start is not None and gap_start >= bars.index[290]


def test_quality_gate_rejects_a_frame_full_of_impossible_jumps(cfg):
    # A units mismatch or an unadjusted rollover looks exactly like this. It
    # must not reach a strategy.
    bars = make_bars(200)
    bars.iloc[::5, bars.columns.get_loc("close")] += 5_000.0
    bars["high"] = bars[["open", "close"]].max(axis=1) + 0.5
    bars["low"] = bars[["open", "close"]].min(axis=1) - 0.5

    with pytest.raises(DataQualityError) as exc:
        load_bars("ES", "1m", start=bars.index[0], end=bars.index[-1], cfg=cfg, source=RecordingSource(bars))
    assert "median true range" in str(exc.value)


def test_empty_history_raises_with_a_next_step_not_an_empty_frame(cfg):
    empty = make_bars(0)
    with pytest.raises(DataQualityError) as exc:
        load_bars(
            "ES", "1m",
            start=pd.Timestamp("2026-01-05", tz="UTC"),
            end=pd.Timestamp("2026-01-06", tz="UTC"),
            cfg=cfg, source=RecordingSource(empty),
        )
    msg = str(exc.value)
    assert "no bars" in msg
    assert "SymbolResolver" in msg  # tells the reader what to check next


def test_unknown_symbol_fails_before_any_network_call(cfg):
    src = RecordingSource(make_bars())
    with pytest.raises(KeyError):
        load_bars("NOTREAL", "1m", cfg=cfg, source=src)
    assert src.calls == []


def test_quality_summary_is_attached_to_the_returned_frame(cfg):
    bars = make_bars()
    df = load_bars("ES", "1m", start=bars.index[0], end=bars.index[-1], cfg=cfg, source=RecordingSource(bars))
    quality = df.attrs.get("quality")
    assert quality is not None
    assert quality.n_bars == len(df)
    assert quality.symbol == "ES"


def test_load_local_round_trips_csv_and_parquet(tmp_path):
    bars = make_bars(120)

    csv_path = tmp_path / "bars.csv"
    bars.to_csv(csv_path)
    from_csv = load_local(csv_path)
    assert len(from_csv) == len(bars)
    assert from_csv.index.tz is not None

    pq_path = tmp_path / "bars.parquet"
    bars.to_parquet(pq_path)
    from_pq = load_local(pq_path)
    assert len(from_pq) == len(bars)


def test_load_local_accepts_vendor_column_spellings(tmp_path):
    # A user export with 'Time'/'O'/'H'/'L'/'C'/'Vol' must not require hand-editing.
    bars = make_bars(50).reset_index()
    bars.columns = ["Time", "O", "H", "L", "C", "Vol"]
    path = tmp_path / "odd.csv"
    bars.to_csv(path, index=False)

    out = load_local(path)
    assert list(out.columns[:5]) == ["open", "high", "low", "close", "volume"]
    assert len(out) == 50


def test_load_local_rejects_an_unrecognised_file_type(tmp_path):
    path = tmp_path / "bars.txt"
    path.write_text("nope")
    with pytest.raises(ValueError):
        load_local(path)


def test_align_inner_joins_so_no_symbol_sees_a_bar_it_did_not_have():
    a = make_bars(100)
    b = make_bars(100).iloc[20:]  # starts later
    out = align({"ES": a, "NQ": b})

    assert len(out) == 80
    assert "ES_close" in out.columns and "NQ_close" in out.columns
    assert out.index[0] == b.index[0]
    assert out.index.is_monotonic_increasing


def test_resolution_failure_against_a_real_catalog_is_announced(cfg):
    # A source that *has* a catalog but cannot resolve the symbol is a genuine
    # problem: the fetch then silently uses the lab spelling, and the failure
    # surfaces later as "no history" rather than "bad lookup". Say so up front.
    class BrokenCatalogSource(RecordingSource):
        def catalog(self, category=None):
            raise RuntimeError("catalog unavailable")

    bars = make_bars(120)
    src = BrokenCatalogSource(bars)
    with pytest.warns(RuntimeWarning, match="could not resolve"):
        load_bars("ES", "1m", start=bars.index[0], end=bars.index[-1], cfg=cfg, source=src)


def test_a_source_without_a_catalog_is_not_warned_about(cfg):
    # The common case (a test double, or a vendor symbol that already matches
    # the lab spelling) must stay quiet, or the warning above becomes noise.
    bars = make_bars(120)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        load_bars("ES", "1m", start=bars.index[0], end=bars.index[-1], cfg=cfg, source=RecordingSource(bars))


def test_align_requires_at_least_one_frame():
    with pytest.raises(ValueError):
        align({})
