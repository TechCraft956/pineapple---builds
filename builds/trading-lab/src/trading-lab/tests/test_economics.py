"""Tests for lab.data.economics: calendar normalisation, high-impact windows,
and -- the important one -- the point-in-time guard that must never hand back
a release before its own publish timestamp."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from lab.data.economics import (
    PointInTimeCalendar,
    economic_calendar,
    high_impact_windows,
    is_blocked,
    point_in_time,
)


class FakeSource:
    """Minimal MarketDataSource double: only economic_calendar is exercised
    by these tests, everything else would raise if called by mistake."""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.calls: list[tuple[str, Any]] = []

    def economic_calendar(self, region: str, start: Any) -> list[dict[str, Any]]:
        self.calls.append((region, start))
        return self._records

    def candles(self, *a, **k):  # pragma: no cover - not used here
        raise NotImplementedError

    def catalog(self, *a, **k):  # pragma: no cover - not used here
        raise NotImplementedError


def _raw_records() -> list[dict[str, Any]]:
    # Deliberately varied field spellings/casing, since the vendor schema is
    # unverified -- this is what _normalise_calendar has to survive.
    return [
        {"date": "2024-03-01T13:30:00Z", "name": "Nonfarm Payrolls", "impact": "High",
         "actual": 275000, "forecast": 200000, "prior": 229000},
        {"date": "2024-03-06T15:00:00Z", "name": "ISM Services PMI", "impact": "medium",
         "actual": 52.6, "forecast": 53.0, "prior": 53.4},
        {"date": "2024-03-12T12:30:00Z", "name": "CPI m/m", "impact": "H",
         "actual": 0.4, "forecast": 0.4, "prior": 0.3},
        {"date": "2024-03-20T18:00:00Z", "name": "FOMC Rate Decision", "impact": "3",
         "actual": 5.50, "forecast": 5.50, "prior": 5.50},
        {"date": "2024-03-04T09:00:00Z", "name": "Factory Orders", "impact": "low",
         "actual": 1.4, "forecast": 1.0, "prior": -3.6},
    ]


def test_economic_calendar_normalises_fields_and_importance() -> None:
    source = FakeSource(_raw_records())
    df = economic_calendar("us", "2024-03-01", source=source)

    assert list(df.columns) == ["event", "importance", "actual", "consensus", "previous", "region"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing

    importances = set(df["importance"])
    assert importances == {"high", "medium", "low"}
    row = df[df["event"] == "Nonfarm Payrolls"].iloc[0]
    assert row["importance"] == "high"
    assert row["actual"] == 275000
    assert row["consensus"] == 200000
    assert row["previous"] == 229000
    assert source.calls == [("us", "2024-03-01")]


def test_economic_calendar_filters_by_start_and_end() -> None:
    source = FakeSource(_raw_records())
    df = economic_calendar("us", "2024-03-05", end="2024-03-15", source=source)
    assert set(df["event"]) == {"ISM Services PMI", "CPI m/m"}


def test_high_impact_windows_only_covers_flagged_levels() -> None:
    source = FakeSource(_raw_records())
    df = economic_calendar("us", "2024-01-01", source=source)
    windows = high_impact_windows(df, before=pd.Timedelta(minutes=30), after=pd.Timedelta(hours=1))

    # "High", "H" and "3" all normalise to "high": Nonfarm Payrolls, CPI m/m, FOMC.
    assert len(windows) == 3
    release = pd.Timestamp("2024-03-01T13:30:00Z")
    assert is_blocked(release, windows) is True
    assert is_blocked(release - pd.Timedelta(minutes=45), windows) is False
    assert is_blocked(release + pd.Timedelta(minutes=90), windows) is False
    assert is_blocked(release - pd.Timedelta(minutes=15), windows) is True  # inside the `before` pad


def test_high_impact_windows_empty_when_no_events_match() -> None:
    source = FakeSource(_raw_records())
    df = economic_calendar("us", "2024-01-01", source=source)
    windows = high_impact_windows(df, before=pd.Timedelta(0), after=pd.Timedelta(0), levels=("extreme",))
    assert len(windows) == 0
    assert is_blocked(pd.Timestamp.now(tz="UTC"), windows) is False


def test_point_in_time_guard_rejects_future_release() -> None:
    """The core lookahead trap: querying *before* a release must return the
    prior value, never the release that hasn't happened yet from the
    strategy's point of view."""
    df = pd.DataFrame(
        {
            "event": ["CPI m/m", "CPI m/m", "CPI m/m"],
            "importance": ["high", "high", "high"],
            "actual": [0.3, 0.4, 0.5],
            "consensus": [0.3, 0.4, 0.4],
            "previous": [0.2, 0.3, 0.4],
            "region": ["us", "us", "us"],
        },
        index=pd.DatetimeIndex(
            ["2024-01-11T13:30:00Z", "2024-02-13T13:30:00Z", "2024-03-12T12:30:00Z"], tz="UTC", name="ts"
        ),
    )
    pit = point_in_time(df)

    # Querying the instant *before* the March release must not see it.
    just_before_march = pd.Timestamp("2024-03-12T12:29:59Z")
    assert pit.latest("CPI m/m", just_before_march) == pytest.approx(0.4)  # February's number

    # Exactly at the release timestamp, it becomes visible.
    at_march = pd.Timestamp("2024-03-12T12:30:00Z")
    assert pit.latest("CPI m/m", at_march) == pytest.approx(0.5)

    # Before any release has ever happened, there is nothing to return.
    before_any = pd.Timestamp("2024-01-01T00:00:00Z")
    assert pit.latest("CPI m/m", before_any) is None

    # as_of() must never leak a row whose index is after the query time.
    sub = pit.as_of(just_before_march)
    assert (sub.index <= just_before_march).all()
    assert len(sub) == 2  # January and February releases, but not March's


def test_point_in_time_upcoming_masks_actual() -> None:
    df = pd.DataFrame(
        {
            "event": ["FOMC Rate Decision"],
            "importance": ["high"],
            "actual": [5.50],
            "consensus": [5.50],
            "previous": [5.50],
            "region": ["us"],
        },
        index=pd.DatetimeIndex(["2024-03-20T18:00:00Z"], tz="UTC", name="ts"),
    )
    pit = point_in_time(df)
    upcoming = pit.upcoming(pd.Timestamp("2024-03-01T00:00:00Z"))
    assert len(upcoming) == 1
    assert upcoming.iloc[0]["actual"] is None
    assert upcoming.iloc[0]["event"] == "FOMC Rate Decision"  # schedule itself is fine to look ahead at


def test_point_in_time_blocked_uses_full_schedule() -> None:
    df = pd.DataFrame(
        {
            "event": ["FOMC Rate Decision"],
            "importance": ["high"],
            "actual": [5.50],
            "consensus": [5.50],
            "previous": [5.50],
            "region": ["us"],
        },
        index=pd.DatetimeIndex(["2024-03-20T18:00:00Z"], tz="UTC", name="ts"),
    )
    pit = point_in_time(df)
    before = pd.Timedelta(minutes=30)
    after = pd.Timedelta(hours=1)
    assert pit.blocked(pd.Timestamp("2024-03-20T18:15:00Z"), before, after) is True
    assert pit.blocked(pd.Timestamp("2024-03-20T10:00:00Z"), before, after) is False


def test_as_of_requires_timezone_aware_timestamp() -> None:
    df = pd.DataFrame(
        {"event": ["x"], "importance": ["low"], "actual": [1], "consensus": [1], "previous": [1], "region": ["us"]},
        index=pd.DatetimeIndex(["2024-01-01T00:00:00Z"], tz="UTC", name="ts"),
    )
    pit = point_in_time(df)
    with pytest.raises(ValueError):
        pit.as_of(pd.Timestamp("2024-01-01"))  # naive, must be rejected
