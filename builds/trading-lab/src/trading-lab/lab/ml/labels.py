"""Triple-barrier labelling, built to agree with the backtest engine's fills.

The whole point of the probability gate is "P(+1R before -1R)". If this
module's idea of how a bar fills a stop-vs-target race disagrees with
``lab.backtest``'s idea, the model learns to predict a fiction that the live
engine (and live trading) will never produce. So the tie-break rule here is
the same one documented on :attr:`lab.core.config.LabConfig.pessimistic_intrabar`:
when a single bar's range spans both the target and the stop, the stop is
assumed to have printed first. This module does not import ``lab.backtest``
(scope boundary), it just implements the same documented convention
independently -- see the module docstring on ``lab.core.config`` for the
source of truth on that convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from lab.core.types import LONG, SHORT, Direction, Signal, TradeList

__all__ = [
    "BarrierOutcome",
    "triple_barrier",
    "label_from_trades",
    "r_label",
]


@dataclass(frozen=True, slots=True)
class BarrierOutcome:
    """Result of racing a signal's +1R and -1R (stop) barriers forward in time.

    Attributes
    ----------
    label:
        1 if the favourable (+1R) barrier was reached before the adverse
        (stop) barrier, within ``horizon`` of the fill. 0 otherwise -- which
        covers both "stop hit" and "neither hit before the time barrier".
    r:
        Realised R multiple. Exactly +1.0 / -1.0 on a barrier touch (this
        module does not model slippage beyond the stop itself -- that is the
        backtest engine's job); the actual mark-to-market R at the horizon
        cutoff when neither barrier was touched.
    outcome:
        ``"target"``, ``"stop"``, ``"time"`` (horizon elapsed, no barrier
        touched) or ``"no_fill"`` (the entry order itself never filled within
        ``signal.valid_until`` / the available bars).
    """

    signal_ts: pd.Timestamp
    label: int
    r: float
    outcome: str
    entry_ts: pd.Timestamp | None
    entry_price: float | None
    exit_ts: pd.Timestamp | None
    exit_price: float | None
    bars_held: int


def _find_entry(
    bars: pd.DataFrame, signal: Signal
) -> tuple[pd.Timestamp, float] | None:
    """Locate the first bar (strictly after ``signal.ts``) that fills the order.

    Mirrors the entry semantics documented on :class:`lab.core.types.Signal`:
    market fills at the next bar's open, limit fills only if price trades
    through the entry in the strategy's favour, stop (breakout) fills only if
    price trades through against the retracement.
    """
    future = bars.loc[bars.index > signal.ts]
    if signal.valid_until is not None:
        future = future.loc[future.index <= signal.valid_until]
    if len(future) == 0:
        return None

    if signal.entry_type == "market":
        row = future.iloc[0]
        return future.index[0], float(row["open"])

    for ts, row in future.iterrows():
        if signal.entry_type == "limit":
            touched = (
                row["low"] <= signal.entry
                if signal.direction == LONG
                else row["high"] >= signal.entry
            )
        else:  # "stop" (breakout)
            touched = (
                row["high"] >= signal.entry
                if signal.direction == LONG
                else row["low"] <= signal.entry
            )
        if touched:
            return ts, float(signal.entry)
    return None


def triple_barrier(
    bars: pd.DataFrame,
    signal: Signal,
    horizon: pd.Timedelta,
    *,
    pessimistic: bool = True,
) -> BarrierOutcome:
    """Race +1R against -1R (the signal's own stop) for ``horizon`` after fill.

    ``pessimistic=True`` (the default, and the only setting that agrees with
    the backtest engine) resolves a bar that touches both barriers in favour
    of the stop -- see the module docstring. Setting it False is provided only
    so the pessimism itself can be measured, exactly as
    ``LabConfig.pessimistic_intrabar`` is never meant to be switched off for a
    result anyone trusts.
    """
    entry = _find_entry(bars, signal)
    if entry is None:
        return BarrierOutcome(
            signal_ts=signal.ts, label=0, r=0.0, outcome="no_fill",
            entry_ts=None, entry_price=None, exit_ts=None, exit_price=None,
            bars_held=0,
        )
    entry_ts, entry_price = entry
    favourable = signal.r_multiple_price(1.0)
    adverse = signal.stop
    deadline = entry_ts + horizon

    window = bars.loc[(bars.index > entry_ts) & (bars.index <= deadline)]
    for i, (ts, row) in enumerate(window.iterrows(), start=1):
        if signal.direction == LONG:
            hit_favourable = row["high"] >= favourable
            hit_adverse = row["low"] <= adverse
        else:
            hit_favourable = row["low"] <= favourable
            hit_adverse = row["high"] >= adverse

        if hit_favourable and hit_adverse:
            # Both barriers sit inside this single bar's range: we cannot know
            # which printed first from OHLC alone, so assume the worse outcome.
            if pessimistic:
                return BarrierOutcome(
                    signal.ts, 0, -1.0, "stop", entry_ts, entry_price, ts, adverse, i
                )
            return BarrierOutcome(
                signal.ts, 1, 1.0, "target", entry_ts, entry_price, ts, favourable, i
            )
        if hit_adverse:
            return BarrierOutcome(
                signal.ts, 0, -1.0, "stop", entry_ts, entry_price, ts, adverse, i
            )
        if hit_favourable:
            return BarrierOutcome(
                signal.ts, 1, 1.0, "target", entry_ts, entry_price, ts, favourable, i
            )

    # Neither barrier touched before the horizon elapsed: mark to the last
    # available close (which may be before `deadline` if bars run out).
    if len(window) == 0:
        return BarrierOutcome(
            signal.ts, 0, 0.0, "time", entry_ts, entry_price, entry_ts, entry_price, 0
        )
    last_ts = window.index[-1]
    last_close = float(window["close"].iloc[-1])
    r = signal.direction * (last_close - entry_price) / signal.risk_per_unit
    label = 1 if r > 0 else 0
    return BarrierOutcome(
        signal.ts, label, float(r), "time", entry_ts, entry_price, last_ts, last_close, len(window)
    )


def label_from_trades(trades: TradeList, *, win_threshold_r: float = 0.0) -> pd.DataFrame:
    """Label straight off realised backtest trades rather than replaying bars.

    Preferred over :func:`triple_barrier` whenever a full backtest has already
    been run, since it inherits the engine's actual fills (slippage,
    commission, partial scale-outs) instead of the simplified independent
    replica above. Indexed by ``signal_ts`` where the trade recorded one,
    falling back to ``entry_ts``.

    ``win_threshold_r`` lets a caller require more than "> 0" to count as a
    label-1 win (e.g. 1.0 to require a full +1R before it counts), but the
    continuous ``r_label`` column is always the raw realised R so downstream
    code is never forced to accept the threshold's framing.
    """
    rows = []
    for t in trades:
        idx_ts = t.signal_ts if t.signal_ts is not None else t.entry_ts
        rows.append(
            {
                "ts": idx_ts,
                "label": int(t.r_multiple > win_threshold_r),
                "r_label": float(t.r_multiple),
                "exit_reason": t.exit_reason.value,
                "entry_ts": t.entry_ts,
                "exit_ts": t.exit_ts,
            }
        )
    if not rows:
        out = pd.DataFrame(columns=["label", "r_label", "exit_reason", "entry_ts", "exit_ts"])
        out.index = pd.DatetimeIndex([], tz="UTC", name="ts")
        return out
    df = pd.DataFrame(rows).sort_values("ts").set_index("ts")
    df.index.name = "ts"
    return df


def r_label(trades: TradeList) -> pd.Series:
    """Continuous realised-R series for ``trades``, indexed the same way as :func:`label_from_trades`."""
    return label_from_trades(trades)["r_label"]
