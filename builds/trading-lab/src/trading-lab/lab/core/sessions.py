"""Session clocks: CME trading days, Asia/London/RTH windows, prior-day levels.

Session boundaries are defined in the *exchange* timezone (``America/Chicago``
for CME products) and converted to UTC on demand. Doing it this way means DST
transitions in Chicago, London and Tokyo are handled by the tz database instead
of by arithmetic, and a session window keeps its economic meaning across the
March and November shifts -- which is exactly when a hand-rolled UTC offset
silently starts labelling the wrong hour as "the London open".

The CME trading day runs 17:00 CT to 16:00 CT the following calendar day, with
a 60-minute maintenance break. A bar stamped 22:30 UTC on a Sunday therefore
belongs to *Monday's* trading day. Every daily aggregation in the lab -- daily
PnL, Topstep end-of-day drawdown trailing, prior-day high/low -- uses
:func:`trading_day` so those all agree with each other and with the broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta

import pandas as pd

__all__ = [
    "SessionWindow",
    "ASIA",
    "LONDON",
    "NY_RTH",
    "CL_RTH",
    "OVERNIGHT",
    "SESSIONS",
    "CME_TZ",
    "trading_day",
    "add_trading_day",
    "window_bounds",
    "slice_window",
    "iter_sessions",
    "session_levels",
    "prior_day_levels",
]

CME_TZ = "America/Chicago"
#: The CME trading day rolls at 17:00 CT. Bars at or after this time belong to
#: the next calendar trading day.
DAY_ROLL = time(17, 0)


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """A named intraday window, expressed in exchange-local wall-clock time.

    ``start`` and ``end`` are ``HH:MM`` strings. When ``end <= start`` the
    window wraps past midnight (e.g. Asia 18:00 -> 02:00), and it is anchored so
    that it *ends* inside its trading day: the Asia session for Tuesday's
    trading day starts at 18:00 CT on Monday.
    """

    name: str
    start: str
    end: str
    tz: str = CME_TZ

    @property
    def start_time(self) -> time:
        h, m = (int(x) for x in self.start.split(":"))
        return time(h, m)

    @property
    def end_time(self) -> time:
        h, m = (int(x) for x in self.end.split(":"))
        return time(h, m)

    @property
    def wraps_midnight(self) -> bool:
        return self.end_time <= self.start_time

    def bounds(self, day: date | str | pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
        """UTC ``[start, end)`` for this window on the given *trading day*."""
        return window_bounds(self, day)


#: Tokyo cash hours mapped onto the Chicago clock. The "Asia range" the sweep
#: strategy uses is the high/low of this window.
ASIA = SessionWindow("asia", "18:00", "02:00")
#: London cash open through the pre-NY window.
LONDON = SessionWindow("london", "02:00", "07:00")
#: Equity-index regular trading hours.
NY_RTH = SessionWindow("ny_rth", "08:30", "15:00")
#: NYMEX energy pit hours -- CL's opening range is anchored here.
CL_RTH = SessionWindow("cl_rth", "08:00", "13:30")
#: Everything from the CME reopen to the equity cash open.
OVERNIGHT = SessionWindow("overnight", "17:00", "08:30")

SESSIONS: dict[str, SessionWindow] = {
    s.name: s for s in (ASIA, LONDON, NY_RTH, CL_RTH, OVERNIGHT)
}


def trading_day(ts: pd.Timestamp | pd.DatetimeIndex, tz: str = CME_TZ):
    """Map timestamps to the CME trading day (a naive ``date``) they belong to.

    Works on a single timestamp or a whole index. Returns a ``date`` for scalar
    input and a ``pandas.Index`` of dates for index input.
    """
    if isinstance(ts, pd.DatetimeIndex):
        local = ts.tz_convert(tz) if ts.tz is not None else ts.tz_localize("UTC").tz_convert(tz)
        rolled = local + pd.to_timedelta(
            [(1 if t >= DAY_ROLL else 0) for t in local.time], unit="D"
        )
        return pd.Index(rolled.date, name="trading_day")
    t = ts if ts.tzinfo is not None else ts.tz_localize("UTC")
    local = t.tz_convert(tz)
    return (local + timedelta(days=1)).date() if local.time() >= DAY_ROLL else local.date()


def add_trading_day(df: pd.DataFrame, tz: str = CME_TZ) -> pd.DataFrame:
    """Return a copy of ``df`` with a ``trading_day`` column attached."""
    out = df.copy()
    out["trading_day"] = trading_day(out.index, tz=tz)
    return out


def window_bounds(window: SessionWindow, day: date | str | pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """UTC half-open ``[start, end)`` for ``window`` on trading day ``day``."""
    d = pd.Timestamp(day).date() if not isinstance(day, date) else day
    end_local = pd.Timestamp.combine(d, window.end_time).tz_localize(
        window.tz, nonexistent="shift_forward", ambiguous=True
    )
    if window.wraps_midnight:
        start_local = pd.Timestamp.combine(d - timedelta(days=1), window.start_time).tz_localize(
            window.tz, nonexistent="shift_forward", ambiguous=True
        )
    else:
        start_local = pd.Timestamp.combine(d, window.start_time).tz_localize(
            window.tz, nonexistent="shift_forward", ambiguous=True
        )
    return start_local.tz_convert("UTC"), end_local.tz_convert("UTC")


def slice_window(
    df: pd.DataFrame,
    window: SessionWindow,
    day: date | str | pd.Timestamp,
) -> pd.DataFrame:
    """Bars whose *open* timestamp falls in ``window`` on trading day ``day``.

    Half-open on the right, so consecutive windows never double-count a bar.
    """
    start, end = window_bounds(window, day)
    return df.loc[(df.index >= start) & (df.index < end)]


def iter_sessions(df: pd.DataFrame, tz: str = CME_TZ):
    """Yield ``(trading_day, frame)`` for each CME trading day present in ``df``.

    Days are yielded in chronological order, which is what every walk-forward
    and account-simulation loop needs.
    """
    days = trading_day(df.index, tz=tz)
    for day, idx in pd.Series(range(len(df)), index=days).groupby(level=0):
        yield day, df.iloc[idx.to_numpy()]


def session_levels(
    df: pd.DataFrame,
    window: SessionWindow,
    day: date | str | pd.Timestamp,
) -> dict[str, float] | None:
    """High/low/open/close/range/volume of one session window.

    Returns ``None`` when the window has no bars, which is the correct signal to
    skip the day rather than to substitute a level from somewhere else.
    """
    bars = slice_window(df, window, day)
    if len(bars) == 0:
        return None
    high = float(bars["high"].max())
    low = float(bars["low"].min())
    return {
        "high": high,
        "low": low,
        "open": float(bars["open"].iloc[0]),
        "close": float(bars["close"].iloc[-1]),
        "range": high - low,
        "volume": float(bars["volume"].fillna(0).sum()),
        "n_bars": int(len(bars)),
        "start": bars.index[0],
        "end": bars.index[-1],
    }


def prior_day_levels(df: pd.DataFrame, day: date | str | pd.Timestamp, tz: str = CME_TZ) -> dict[str, float] | None:
    """High/low/close of the most recent *completed* trading day before ``day``.

    Uses the previous day that actually has bars rather than ``day - 1``, so
    holidays and weekends resolve to the real prior session.
    """
    d = pd.Timestamp(day).date() if not isinstance(day, date) else day
    days = trading_day(df.index, tz=tz)
    prior = [x for x in pd.unique(days) if x < d]
    if not prior:
        return None
    target = max(prior)
    bars = df.loc[days == target]
    if len(bars) == 0:
        return None
    return {
        "day": target,
        "high": float(bars["high"].max()),
        "low": float(bars["low"].min()),
        "close": float(bars["close"].iloc[-1]),
        "open": float(bars["open"].iloc[0]),
        "range": float(bars["high"].max() - bars["low"].min()),
    }
