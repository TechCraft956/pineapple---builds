"""Core value types shared by every module in the lab.

These are the *contract*. Data, strategy, backtest, risk, ML, journal and report
code all speak in terms of the types defined here. Nothing in this module may
import from any other ``lab.*`` package, so it stays dependency-free and cheap
to import.

Conventions that hold everywhere in the lab
-------------------------------------------
* **Time is UTC internally.** Every timestamp stored, cached or passed between
  modules is a timezone-aware ``pandas.Timestamp`` in UTC. Session logic
  converts to ``America/Chicago`` (CME clock) only at the boundary where a
  human-meaningful session window is defined, and converts straight back.
* **Bar frames** are ``pandas.DataFrame`` objects with a UTC ``DatetimeIndex``
  named ``ts`` and the columns ``open, high, low, close, volume``. The index is
  monotonically increasing and unique, and each timestamp is the bar's *open*
  time. See :mod:`lab.core.frames` for the validator.
* **Prices are raw instrument prices**, never points or ticks. Convert with the
  helpers on :class:`lab.core.instruments.Instrument`.
* **Direction** is ``+1`` for long and ``-1`` for short. Never a string.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Sequence

import pandas as pd

__all__ = [
    "LONG",
    "SHORT",
    "Direction",
    "ExitReason",
    "Signal",
    "Fill",
    "Trade",
    "TradeList",
    "BacktestResult",
]

LONG = 1
SHORT = -1

Direction = int  # +1 long, -1 short. Kept as a plain int on purpose.


class ExitReason(str, Enum):
    """Why a position was closed. Order matters for reporting, not for logic."""

    STOP = "stop"
    TARGET = "target"
    TIME_STOP = "time_stop"
    SESSION_END = "session_end"
    OPPOSING_LEVEL = "opposing_level"
    TRAIL = "trail"
    DAILY_LOCKOUT = "daily_lockout"
    ACCOUNT_BREACH = "account_breach"
    DATA_END = "data_end"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Signal:
    """An intent to enter, emitted by a strategy *before* any fill is known.

    A signal is deliberately not a trade: it carries the levels the strategy
    committed to at decision time. The backtest engine is the only thing allowed
    to turn one into a :class:`Trade`, and it is the only thing that knows about
    slippage, commission and intrabar sequencing.

    Attributes
    ----------
    ts:
        Decision time (UTC). The engine may not use any information after this
        timestamp when filling the signal -- that invariant is asserted in tests.
    direction:
        ``LONG`` (+1) or ``SHORT`` (-1).
    entry:
        Limit/trigger price the strategy wants. ``entry_type`` says how it is
        interpreted.
    stop:
        Protective stop price. Must be below ``entry`` for longs, above for
        shorts; validated on construction.
    targets:
        Ordered take-profit prices. May be empty when the exit policy is purely
        time- or level-based. Multiple targets scale out evenly unless
        ``target_weights`` is given.
    entry_type:
        ``"market"`` (fill at next bar open), ``"limit"`` (fill only if price
        trades through ``entry`` in the strategy's favour) or ``"stop"`` (fill
        only if price trades through ``entry`` against the retracement, i.e. a
        breakout entry).
    valid_until:
        Latest timestamp at which the entry order may still fill. ``None`` means
        "until the session exit rule fires".
    max_hold:
        Time stop measured from *fill*, not from signal.
    tag:
        Short machine-readable label for the setup variant, e.g.
        ``"asia_high_sweep"``. Used to slice results.
    meta:
        Free-form context captured at decision time -- Asia range size, ATR,
        distance to VWAP, news proximity, and so on. The ML layer reads its
        features from here, so anything you might want to condition on later
        must be written here *now*, not recomputed afterwards.
    """

    ts: pd.Timestamp
    direction: Direction
    entry: float
    stop: float
    targets: tuple[float, ...] = ()
    entry_type: str = "market"
    valid_until: pd.Timestamp | None = None
    max_hold: pd.Timedelta | None = None
    tag: str = ""
    strategy: str = ""
    symbol: str = ""
    target_weights: tuple[float, ...] | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in (LONG, SHORT):
            raise ValueError(f"direction must be +1 or -1, got {self.direction!r}")
        if self.entry_type not in ("market", "limit", "stop"):
            raise ValueError(f"unknown entry_type {self.entry_type!r}")
        if not math.isfinite(self.entry) or not math.isfinite(self.stop):
            raise ValueError("entry and stop must be finite")
        if self.direction == LONG and self.stop >= self.entry:
            raise ValueError(f"long stop {self.stop} must sit below entry {self.entry}")
        if self.direction == SHORT and self.stop <= self.entry:
            raise ValueError(f"short stop {self.stop} must sit above entry {self.entry}")
        for t in self.targets:
            if self.direction == LONG and t <= self.entry:
                raise ValueError(f"long target {t} must sit above entry {self.entry}")
            if self.direction == SHORT and t >= self.entry:
                raise ValueError(f"short target {t} must sit below entry {self.entry}")
        if self.target_weights is not None:
            if len(self.target_weights) != len(self.targets):
                raise ValueError("target_weights must match targets in length")
            if not math.isclose(sum(self.target_weights), 1.0, abs_tol=1e-9):
                raise ValueError("target_weights must sum to 1.0")
        if self.ts.tzinfo is None:
            raise ValueError("Signal.ts must be timezone-aware (UTC)")

    @property
    def risk_per_unit(self) -> float:
        """Price distance from entry to stop. Always positive."""
        return abs(self.entry - self.stop)

    def r_multiple_price(self, r: float) -> float:
        """Price that sits ``r`` R away from entry in the trade's favour."""
        return self.entry + self.direction * r * self.risk_per_unit

    def with_targets(self, *targets: float) -> "Signal":
        """Return a copy carrying a different take-profit ladder."""
        return replace(self, targets=tuple(targets), target_weights=None)


@dataclass(frozen=True, slots=True)
class Fill:
    """A single execution. Price is *after* slippage."""

    ts: pd.Timestamp
    price: float
    qty: float
    direction: Direction
    slippage_ticks: float = 0.0
    commission: float = 0.0


@dataclass(frozen=True, slots=True)
class Trade:
    """A round-turn position, from first entry fill to final exit fill.

    ``pnl`` is net of commission and slippage and is denominated in account
    currency (USD). ``r_multiple`` divides *net* PnL by the *intended* risk in
    dollars, so a stop that slips beyond its price produces an R worse than
    ``-1`` -- which is the honest accounting and the one the risk engine needs.
    """

    symbol: str
    strategy: str
    direction: Direction
    entry_ts: pd.Timestamp
    entry_price: float
    exit_ts: pd.Timestamp
    exit_price: float
    qty: float
    pnl: float
    commission: float
    slippage_cost: float
    risk_dollars: float
    exit_reason: ExitReason
    mfe: float = 0.0  # best unrealised excursion in dollars, >= 0
    mae: float = 0.0  # worst unrealised excursion in dollars, <= 0
    bars_held: int = 0
    tag: str = ""
    signal_ts: pd.Timestamp | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def r_multiple(self) -> float:
        if self.risk_dollars <= 0:
            return 0.0
        return self.pnl / self.risk_dollars

    @property
    def duration(self) -> pd.Timedelta:
        return self.exit_ts - self.entry_ts

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> dict[str, Any]:
        d = {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "direction": self.direction,
            "entry_ts": self.entry_ts,
            "entry_price": self.entry_price,
            "exit_ts": self.exit_ts,
            "exit_price": self.exit_price,
            "qty": self.qty,
            "pnl": self.pnl,
            "commission": self.commission,
            "slippage_cost": self.slippage_cost,
            "risk_dollars": self.risk_dollars,
            "r_multiple": self.r_multiple,
            "exit_reason": self.exit_reason.value,
            "mfe": self.mfe,
            "mae": self.mae,
            "bars_held": self.bars_held,
            "tag": self.tag,
            "signal_ts": self.signal_ts,
        }
        for k, v in self.meta.items():
            d.setdefault(f"meta_{k}", v)
        return d


TradeList = Sequence[Trade]


def trades_to_frame(trades: TradeList) -> pd.DataFrame:
    """Flatten trades into a DataFrame indexed by ``exit_ts``.

    Empty input yields an empty frame with the right columns, so downstream
    metric code never has to special-case "no trades".
    """
    columns = [
        "symbol", "strategy", "direction", "entry_ts", "entry_price", "exit_ts",
        "exit_price", "qty", "pnl", "commission", "slippage_cost", "risk_dollars",
        "r_multiple", "exit_reason", "mfe", "mae", "bars_held", "tag", "signal_ts",
    ]
    if not trades:
        empty = pd.DataFrame(columns=columns)
        empty.index = pd.DatetimeIndex([], tz="UTC", name="exit_ts")
        return empty
    df = pd.DataFrame([t.to_dict() for t in trades])
    df = df.sort_values("exit_ts").set_index("exit_ts", drop=False)
    df.index.name = "exit_ts"
    return df


@dataclass(slots=True)
class BacktestResult:
    """Everything a single backtest run produced.

    ``params`` and ``data_fingerprint`` exist so a result can be traced back to
    the exact code path and bytes that made it. Never publish a result without
    them -- silently rewriting old numbers after a rule change is the single
    fastest way to fool yourself.
    """

    trades: list[Trade]
    equity: pd.Series  # cumulative net PnL in USD, indexed by exit_ts
    strategy: str
    version: str
    symbol: str
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    stats: Mapping[str, Any] = field(default_factory=dict)
    data_fingerprint: str = ""
    skipped: list[Mapping[str, Any]] = field(default_factory=list)

    @property
    def frame(self) -> pd.DataFrame:
        return trades_to_frame(self.trades)

    def __len__(self) -> int:
        return len(self.trades)
