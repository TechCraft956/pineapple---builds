"""Does the edge hold up across regime, session, volatility and instrument -- or is it one lucky slice?

A backtest's headline stats are pooled across everything: every session,
every volatility state, every instrument traded. That pooling can hide a
strategy that only actually works in London, or only in low-volatility
chop, or only on MES and quietly loses on ES. :func:`compare_regimes` splits
a trade list along the dimensions that matter to this lab -- trend/range/news
regime (caller-supplied classifier, since this lab has no canonical one),
session (via :mod:`lab.core.sessions`), volatility tercile (caller-supplied
volatility-at-entry), and instrument (including micro/full-size families,
e.g. ES+MES) -- and returns both a tidy comparison frame and a
:class:`StabilityVerdict` that states, in prose, exactly what pattern in that
frame would make the split unstable, rather than leaving a reader to eyeball
a table of numbers and guess.

Like the rest of this package, ``lab.backtest.metrics.compute_stats`` is
never imported at module scope -- see :mod:`lab.robustness._common`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from lab.core.sessions import LONDON, NY_RTH, OVERNIGHT, SessionWindow, trading_day, window_bounds
from lab.core.types import Trade, TradeList
from lab.robustness._common import compute_stats

__all__ = [
    "RegimeComparison",
    "StabilityVerdict",
    "compare_regimes",
    "stability_verdict",
]

#: LONDON and NY_RTH before OVERNIGHT deliberately: OVERNIGHT (17:00-08:30 CT)
#: fully contains LONDON's 02:00-07:00 CT window, so a timestamp inside
#: London hours matches both -- checking OVERNIGHT first would silently
#: swallow every London trade into the "overnight" bucket. The narrower,
#: more specific window has to win; OVERNIGHT is the catch-all for whatever
#: is left (chiefly the Asia hours neither other window covers).
DEFAULT_SESSIONS: tuple[SessionWindow, ...] = (LONDON, NY_RTH, OVERNIGHT)


# ---------------------------------------------------------------------------
# the four splits
# ---------------------------------------------------------------------------


def _by_instrument(trades: TradeList) -> dict[str, list[Trade]]:
    from lab.core.instruments import get_instrument  # local: lab.core, not a scope violation, but keep it near its one use

    buckets: dict[str, list[Trade]] = {}
    for t in trades:
        buckets.setdefault(t.symbol, []).append(t)

    families: dict[str, list[Trade]] = {}
    for sym, ts in buckets.items():
        try:
            inst = get_instrument(sym)
        except KeyError:
            continue
        family = inst.micro_of or inst.symbol
        families.setdefault(family, []).extend(ts)

    for family, ts in families.items():
        symbols_present = {t.symbol for t in ts}
        if len(symbols_present) > 1:
            buckets[f"family:{family}"] = ts
    return buckets


def _by_session(trades: TradeList, sessions: Sequence[SessionWindow]) -> dict[str, list[Trade]]:
    buckets: dict[str, list[Trade]] = {s.name: [] for s in sessions}
    buckets["other"] = []
    for t in trades:
        ts = t.entry_ts
        day = trading_day(ts)
        label = "other"
        for s in sessions:
            start, end = window_bounds(s, day)
            if start <= ts < end:
                label = s.name
                break
        buckets[label].append(t)
    return {k: v for k, v in buckets.items() if v}


def _by_volatility_tercile(
    trades: TradeList, vol_of: Callable[[Trade], float], n_buckets: int
) -> dict[str, list[Trade]]:
    scored = [(t, vol_of(t)) for t in trades]
    scored = [(t, v) for t, v in scored if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(scored) < n_buckets:
        return {}
    values = np.array([v for _, v in scored], dtype=float)
    edges = np.quantile(values, np.linspace(0.0, 1.0, n_buckets + 1))
    labels = ["low", "mid", "high"] if n_buckets == 3 else [f"q{i + 1}" for i in range(n_buckets)]
    buckets: dict[str, list[Trade]] = {lab: [] for lab in labels}
    for t, v in scored:
        idx = int(np.searchsorted(edges, v, side="right")) - 1
        idx = min(max(idx, 0), n_buckets - 1)
        buckets[labels[idx]].append(t)
    return buckets


def _by_regime(trades: TradeList, regime_of: Callable[[Trade], str]) -> dict[str, list[Trade]]:
    buckets: dict[str, list[Trade]] = {}
    for t in trades:
        buckets.setdefault(str(regime_of(t)), []).append(t)
    return buckets


def _split_frame(dimension: str, buckets: Mapping[str, list[Trade]]) -> pd.DataFrame:
    rows = []
    for bucket, ts in buckets.items():
        stats = compute_stats(ts)
        rows.append(
            {
                "dimension": dimension, "bucket": bucket, "n_trades": stats["n_trades"],
                "win_rate": stats["win_rate"], "expectancy_r": stats["expectancy_r"],
                "net_pnl": stats["net_pnl"], "max_drawdown_dollars": stats["max_drawdown_dollars"],
            }
        )
    return pd.DataFrame(
        rows, columns=["dimension", "bucket", "n_trades", "win_rate", "expectancy_r", "net_pnl", "max_drawdown_dollars"]
    )


# ---------------------------------------------------------------------------
# stability verdict
# ---------------------------------------------------------------------------


_CRITERIA_TEXT = (
    "A split is judged UNSTABLE when, among buckets that clear min_trades: (1) "
    "expectancy_r changes sign across buckets -- the edge depends on the "
    "regime/session/instrument rather than holding generally, or (2) the spread "
    "between the best and worst bucket's expectancy_r, relative to the mean "
    "expectancy_r across those buckets, exceeds max_relative_spread. Buckets "
    "below min_trades are reported but excluded from both checks: too few trades "
    "to say anything is a data problem, not evidence of instability, and is "
    "called out separately rather than silently dropped."
)


@dataclass(frozen=True, slots=True)
class StabilityVerdict:
    """Whether a regime/session/volatility/instrument split looks stable, and why."""

    stable: bool
    reasons: list[str]
    criteria: str = _CRITERIA_TEXT

    def summary(self) -> str:
        head = "STABLE" if self.stable else "UNSTABLE"
        return f"{head}: " + " | ".join(self.reasons)


def stability_verdict(
    frame: pd.DataFrame,
    *,
    metric: str = "expectancy_r",
    min_trades: int = 20,
    max_relative_spread: float = 1.5,
) -> StabilityVerdict:
    """Judge ``frame`` (a :func:`compare_regimes` frame, or any frame shaped
    like one) stable or not. See :data:`_CRITERIA_TEXT` (``.criteria`` on the
    result) for the exact rule."""
    reasons: list[str] = []
    usable = frame[frame["n_trades"] >= min_trades]
    thin = frame[frame["n_trades"] < min_trades]
    if len(thin):
        reasons.append(
            f"{len(thin)} bucket(s) below min_trades={min_trades}, excluded from the check: "
            f"{list(thin['bucket'])}"
        )
    if len(usable) < 2:
        reasons.append("fewer than two buckets clear min_trades -- not enough to judge stability.")
        return StabilityVerdict(True, reasons)

    vals = usable[metric]
    sign_flip = bool((vals > 0).any() and (vals < 0).any())
    mean_val = float(vals.mean())
    spread = float(vals.max() - vals.min())
    rel_spread = spread / abs(mean_val) if mean_val != 0 else float("inf")

    if sign_flip:
        reasons.append(
            f"{metric} flips sign across buckets (min {vals.min():+.3f}, max {vals.max():+.3f}) -- "
            "the edge is regime/session/instrument-dependent, not general."
        )
    if rel_spread > max_relative_spread:
        reasons.append(
            f"{metric} spread {spread:.3f} is {rel_spread:.1f}x the mean {mean_val:+.3f} "
            f"(tolerance {max_relative_spread:.1f}x)."
        )

    stable = not sign_flip and rel_spread <= max_relative_spread
    if stable:
        reasons.append(
            f"{metric} consistent across buckets: no sign flip, spread {rel_spread:.2f}x mean "
            f"(tolerance {max_relative_spread:.2f}x)."
        )
    return StabilityVerdict(stable, reasons)


# ---------------------------------------------------------------------------
# top-level entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegimeComparison:
    """A tidy multi-dimension comparison frame plus its stability verdict."""

    frame: pd.DataFrame
    verdict: StabilityVerdict

    def summary(self) -> str:
        return self.verdict.summary()


def compare_regimes(
    trades: TradeList,
    *,
    regime_of: Callable[[Trade], str] | None = None,
    regime_name: str = "regime",
    vol_of: Callable[[Trade], float] | None = None,
    n_vol_buckets: int = 3,
    sessions: Sequence[SessionWindow] = DEFAULT_SESSIONS,
    min_trades: int = 20,
    max_relative_spread: float = 1.5,
) -> RegimeComparison:
    """Split ``trades`` by instrument, session, volatility tercile and (if
    supplied) trend/range/news regime, and judge the result for stability.

    ``regime_of`` and ``vol_of`` are caller-supplied classifiers -- this
    module has no opinion on how "trending" or "current volatility" are
    defined, only on how to compare the resulting buckets. Pass
    ``regime_of=lambda t: t.meta.get("regime", "unknown")`` (or similar) and
    ``vol_of=lambda t: t.meta.get("atr_percentile")`` if a strategy already
    records that context on its trades/signals; both are optional and are
    simply omitted from the comparison (and the frame) when not given.

    Instrument splitting is by exact symbol, plus a synthetic
    ``family:<root>`` bucket for any root instrument (e.g. ``ES``, ``CL``)
    that has more than one of its own contracts present (e.g. both ``ES``
    and ``MES``) -- so a micro/full-size discrepancy shows up as its own row
    rather than only being visible by eyeballing the two symbol rows
    separately.
    """
    frames = [_split_frame("instrument", _by_instrument(trades))]
    frames.append(_split_frame("session", _by_session(trades, sessions)))
    if vol_of is not None:
        frames.append(_split_frame("volatility_tercile", _by_volatility_tercile(trades, vol_of, n_vol_buckets)))
    if regime_of is not None:
        frames.append(_split_frame(regime_name, _by_regime(trades, regime_of)))

    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["dimension", "bucket", "n_trades", "win_rate", "expectancy_r", "net_pnl", "max_drawdown_dollars"]
    )
    verdict = stability_verdict(frame, min_trades=min_trades, max_relative_spread=max_relative_spread)
    return RegimeComparison(frame, verdict)
