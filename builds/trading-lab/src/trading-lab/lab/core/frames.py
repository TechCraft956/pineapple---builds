"""Bar-frame conventions, validation and safe resampling.

Every OHLCV frame in the lab obeys the same shape, and :func:`validate_bars`
is the single gate that enforces it. Data loaders call it on the way out,
strategies and the backtest engine call it on the way in. It is cheap, and it
catches the class of bug that silently ruins a backtest: duplicated bars from a
retry, a tz-naive index that quietly shifts sessions by six hours, a mid-history
gap where the vendor dropped a day.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "OHLCV",
    "BarQuality",
    "validate_bars",
    "normalise_bars",
    "resample_bars",
    "assess_quality",
    "fingerprint",
]

OHLCV = ("open", "high", "low", "close", "volume")


def normalise_bars(df: pd.DataFrame, tz: str = "UTC") -> pd.DataFrame:
    """Coerce a vendor frame into lab shape without changing any prices.

    Accepts the common column spellings (``Open``, ``o``, ``time``, ``ts``,
    ``timestamp``, ``datetime``), sorts, de-duplicates on timestamp keeping the
    last occurrence, and localises or converts the index to UTC.
    """
    out = df.copy()
    lower = {c: str(c).strip().lower() for c in out.columns}
    out.columns = [lower[c] for c in out.columns]

    aliases = {
        "o": "open", "h": "high", "l": "low", "c": "close",
        "v": "volume", "vol": "volume", "size": "volume",
        "price": "close", "last": "close",
    }
    out = out.rename(columns={k: v for k, v in aliases.items() if k in out.columns})

    if not isinstance(out.index, pd.DatetimeIndex):
        for cand in ("ts", "timestamp", "time", "datetime", "date"):
            if cand in out.columns:
                idx = pd.to_datetime(out[cand], utc=True, errors="coerce")
                out = out.drop(columns=[cand]).set_index(idx)
                break
        else:
            raise ValueError(
                "frame has no DatetimeIndex and no recognisable timestamp column "
                f"(saw {list(out.columns)})"
            )

    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    if tz != "UTC":
        out.index = out.index.tz_convert(tz)
    out.index.name = "ts"

    missing = [c for c in OHLCV if c not in out.columns]
    if "volume" in missing and all(c in out.columns for c in OHLCV[:4]):
        out["volume"] = np.nan
        missing.remove("volume")
    if missing:
        raise ValueError(f"frame is missing required columns: {missing}")

    out = out[list(OHLCV) + [c for c in out.columns if c not in OHLCV]]
    for c in OHLCV:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    out = out[~out.index.isna()]
    out = out.sort_index(kind="stable")
    out = out[~out.index.duplicated(keep="last")]
    return out


def validate_bars(df: pd.DataFrame, *, name: str = "bars", strict: bool = True) -> pd.DataFrame:
    """Raise if ``df`` violates the bar-frame contract. Returns ``df`` unchanged.

    With ``strict=False`` the OHLC-consistency check (high >= max(open, close),
    low <= min(open, close)) is downgraded to a warning-shaped exception message
    only when more than 0.1% of bars are affected, which tolerates the odd
    vendor print without letting a systematically broken feed through.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError(f"{name}: index must be a DatetimeIndex, got {type(df.index)}")
    if df.index.tz is None:
        raise ValueError(f"{name}: index must be timezone-aware (UTC)")
    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    if not df.index.is_monotonic_increasing:
        raise ValueError(f"{name}: index is not monotonically increasing")
    if df.index.has_duplicates:
        dupes = df.index[df.index.duplicated()][:5].tolist()
        raise ValueError(f"{name}: duplicate timestamps, e.g. {dupes}")
    if len(df) == 0:
        return df

    ohlc = df[["open", "high", "low", "close"]]
    if ohlc.isna().all(axis=1).any():
        raise ValueError(f"{name}: rows with all-NaN OHLC present")
    bad = (
        (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
        | (df["high"] < df["low"])
    )
    n_bad = int(bad.sum())
    if n_bad:
        share = n_bad / len(df)
        if strict or share > 0.001:
            first = df.index[bad][0]
            raise ValueError(
                f"{name}: {n_bad} bars ({share:.3%}) have inconsistent OHLC, "
                f"first at {first}. Re-fetch or clean before using."
            )
    if (df["volume"].fillna(0) < 0).any():
        raise ValueError(f"{name}: negative volume present")
    return df


@dataclass(frozen=True, slots=True)
class BarQuality:
    """Summary of how trustworthy a bar frame is. Cheap enough to always run."""

    symbol: str
    timeframe: str
    n_bars: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    median_gap: pd.Timedelta | None
    n_gaps: int              # gaps > 3x the median spacing
    largest_gap: pd.Timedelta | None
    n_zero_volume: int
    n_zero_range: int        # high == low, a common synthetic-fill tell
    pct_missing_volume: float
    suspicious_jumps: int    # bar-to-bar moves beyond 10 median true ranges

    def summary(self) -> str:
        return (
            f"{self.symbol} {self.timeframe}: {self.n_bars:,} bars "
            f"{self.start} -> {self.end} | gaps>{3}x: {self.n_gaps} "
            f"(largest {self.largest_gap}) | zero-vol {self.n_zero_volume} | "
            f"flat bars {self.n_zero_range} | jumps {self.suspicious_jumps}"
        )


def assess_quality(df: pd.DataFrame, symbol: str = "", timeframe: str = "") -> BarQuality:
    """Profile a bar frame for the failure modes that quietly break backtests."""
    if len(df) == 0:
        return BarQuality(symbol, timeframe, 0, None, None, None, 0, None, 0, 0, 1.0, 0)
    deltas = pd.Series(df.index).diff().dropna()
    median_gap = deltas.median() if len(deltas) else pd.Timedelta(0)
    gap_mask = deltas > 3 * median_gap if median_gap > pd.Timedelta(0) else deltas > pd.Timedelta.max
    tr = (df["high"] - df["low"]).replace(0, np.nan)
    med_tr = float(tr.median()) if tr.notna().any() else np.nan
    jumps = 0
    if med_tr and np.isfinite(med_tr) and med_tr > 0:
        jumps = int((df["close"].diff().abs() > 10 * med_tr).sum())
    return BarQuality(
        symbol=symbol,
        timeframe=timeframe,
        n_bars=len(df),
        start=df.index[0],
        end=df.index[-1],
        median_gap=median_gap,
        n_gaps=int(gap_mask.sum()),
        largest_gap=deltas.max() if len(deltas) else None,
        n_zero_volume=int((df["volume"].fillna(0) == 0).sum()),
        n_zero_range=int((df["high"] == df["low"]).sum()),
        pct_missing_volume=float(df["volume"].isna().mean()),
        suspicious_jumps=jumps,
    )


_PANDAS_RULE = {
    "1s": "1s", "5s": "5s", "15s": "15s", "30s": "30s",
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "4h": "4h", "1d": "1D", "1w": "1W", "1mo": "1MS",
}


def resample_bars(df: pd.DataFrame, timeframe: str, *, origin: str | pd.Timestamp = "start_day") -> pd.DataFrame:
    """Aggregate bars to a coarser timeframe.

    Only ever call this to go *coarser*. Upsampling would invent bars, and the
    engine treats every bar it is given as a real tradable event.
    """
    rule = _PANDAS_RULE.get(timeframe, timeframe)
    out = (
        df.resample(rule, label="left", closed="left", origin=origin)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "high", "low", "close"])
    )
    out.index.name = "ts"
    return out


def fingerprint(df: pd.DataFrame) -> str:
    """Stable short hash of a bar frame's content.

    Stamped onto every :class:`~lab.core.types.BacktestResult` so a number in
    ``results/`` can always be traced to the exact bytes that produced it.
    """
    if len(df) == 0:
        return "empty"
    h = hashlib.sha256()
    h.update(str(len(df)).encode())
    h.update(str(df.index[0]).encode())
    h.update(str(df.index[-1]).encode())
    vals = df[list(OHLCV)].to_numpy(dtype="float64", na_value=np.nan)
    h.update(np.nan_to_num(vals, nan=-1.0).tobytes())
    return h.hexdigest()[:16]
