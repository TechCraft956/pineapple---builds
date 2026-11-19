"""Monte Carlo resampling of a trade sequence, replayed through AccountSimulator.

A single historical trade sequence tells you what happened. It does not tell
you how *likely* that outcome was, or how bad the unlucky draw could have
been -- for that you need many plausible alternate orderings/samplings of the
same edge, each run through :class:`~lab.risk.account.AccountSimulator`.

**Why not plain i.i.d. resampling for everything**: losing streaks are
exactly the thing that blows prop-firm accounts (the trailing MLL cares about
peak-to-trough, not average return), and losing streaks are, in real trading
data, autocorrelated -- a bad regime clusters losses together rather than
scattering them uniformly through history. Independent, identically
distributed (i.i.d.) resampling destroys that clustering by construction (each
slot is drawn independently), which systematically *understates* both the
probability and the depth of a real drawdown. ``method="block"`` and
``method="stationary"`` resample contiguous chunks instead, so a real
five-loss cluster in the source data survives, intact, into a meaningful
fraction of resampled paths. Reach for i.i.d. only when you specifically want
to ask "how much of my drawdown risk is explained by ordering effects at
all" -- comparing an i.i.d. run against a block run *is* that question.

Determinism: everything here is seeded via NumPy's ``Generator`` API
(:func:`numpy.random.default_rng`). The same seed, method and inputs always
produce the same index arrays and therefore the same
:class:`~lab.risk.account.AccountRun` objects -- see
``tests/test_montecarlo.py`` for the direct assertion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from lab.core.types import Trade
from lab.risk.account import AccountRun, AccountSimulator
from lab.risk.rules import AccountRules

__all__ = [
    "BootstrapMethod",
    "bootstrap_trades",
    "permute_order",
    "MonteCarloResult",
    "simulate_paths",
]

BootstrapMethod = Literal["iid", "block", "stationary"]

_DEFAULT_PERCENTILES = (5, 25, 50, 75, 95)


def bootstrap_trades(
    trades: Sequence[Trade],
    n_paths: int,
    method: BootstrapMethod = "iid",
    *,
    seed: int = 0,
    block_size: int | None = None,
    path_length: int | None = None,
) -> np.ndarray:
    """Generate ``n_paths`` resampled index arrays into ``trades``.

    Returns an ``(n_paths, path_length)`` ``int64`` array of 0-based indices
    into ``trades`` (as sorted by ``(exit_ts, entry_ts)`` -- the same order
    :class:`~lab.risk.account.AccountSimulator` processes them in).
    ``path_length`` defaults to ``len(trades)``.

    ``method``:

    * ``"iid"`` -- every slot drawn independently and uniformly, with
      replacement. Fast, fully vectorised, and destroys any autocorrelation
      (losing streaks) present in the source sequence.
    * ``"block"`` -- fixed-length contiguous blocks of ``block_size`` trades
      (default ``round(sqrt(n))``), each block's start position drawn
      uniformly with circular wraparound, concatenated until ``path_length``
      is reached. Preserves local autocorrelation within a block.
    * ``"stationary"`` -- the Politis & Romano (1994) stationary bootstrap:
      like ``"block"``, but block length is itself random (geometrically
      distributed with mean ``block_size``), which avoids the artificial
      periodicity fixed-length blocks introduce at block boundaries while
      still preserving short-range autocorrelation.
    """
    n = len(trades)
    if n == 0:
        raise ValueError("cannot bootstrap an empty trade sequence")
    if n_paths <= 0:
        raise ValueError("n_paths must be > 0")
    length = n if path_length is None else path_length
    if length <= 0:
        raise ValueError("path_length must be > 0")
    rng = np.random.default_rng(seed)

    if method == "iid":
        return rng.integers(0, n, size=(n_paths, length))

    bs = block_size if block_size is not None else max(1, round(math.sqrt(n)))
    if bs <= 0:
        raise ValueError("block_size must be > 0")
    if method == "block":
        return _block_bootstrap(rng, n, n_paths, length, bs)
    if method == "stationary":
        return _stationary_bootstrap(rng, n, n_paths, length, bs)
    raise ValueError(f"unknown bootstrap method {method!r}; expected iid/block/stationary")


def _block_bootstrap(rng: np.random.Generator, n: int, n_paths: int, length: int, block_size: int) -> np.ndarray:
    out = np.empty((n_paths, length), dtype=np.int64)
    for p in range(n_paths):
        row = np.empty(length, dtype=np.int64)
        pos = 0
        while pos < length:
            start = int(rng.integers(0, n))
            take = min(block_size, length - pos)
            row[pos : pos + take] = (start + np.arange(take)) % n
            pos += take
        out[p] = row
    return out


def _stationary_bootstrap(
    rng: np.random.Generator, n: int, n_paths: int, length: int, mean_block_size: int,
) -> np.ndarray:
    """Politis & Romano (1994): at each step, continue the current block with
    probability ``1 - p`` or start a fresh block at a uniform random index
    with probability ``p = 1 / mean_block_size``."""
    p = 1.0 / mean_block_size
    out = np.empty((n_paths, length), dtype=np.int64)
    for path in range(n_paths):
        row = np.empty(length, dtype=np.int64)
        cur = int(rng.integers(0, n))
        for pos in range(length):
            row[pos] = cur
            if rng.random() < p:
                cur = int(rng.integers(0, n))
            else:
                cur = (cur + 1) % n
        out[path] = row
    return out


def permute_order(trades: Sequence[Trade], n_paths: int, *, seed: int = 0) -> np.ndarray:
    """``n_paths`` random permutations (no replacement) of ``trades``' order.

    Unlike :func:`bootstrap_trades`, this never repeats or drops a trade --
    each path is a reordering of the *exact same multiset* of outcomes. Use it
    to isolate the effect of sequencing/luck-of-the-draw ordering on drawdown
    and payout timing, holding the win/loss distribution itself fixed.
    """
    n = len(trades)
    if n == 0:
        raise ValueError("cannot permute an empty trade sequence")
    if n_paths <= 0:
        raise ValueError("n_paths must be > 0")
    rng = np.random.default_rng(seed)
    return np.array([rng.permutation(n) for _ in range(n_paths)], dtype=np.int64)


def _materialize_path(trades: Sequence[Trade], idx: np.ndarray) -> list[Trade]:
    """Build a synthetic sequence: resampled trade *economics*, original time slots.

    Slot ``i`` takes pnl/mae/mfe/commission/etc. from ``ordered[idx[i]]`` but
    keeps the entry/exit timestamps of ``ordered[i]`` (the original,
    chronologically-sorted sequence). This gives every resampled path a valid
    trading-day calendar for :class:`~lab.risk.account.AccountSimulator`'s
    daily grouping and end-of-day trailing, instead of colliding many
    resampled trades onto whichever days they originally happened to fall on.
    When ``len(idx) > len(trades)`` (a ``path_length`` longer than the source
    history), time slots repeat cyclically -- documented as a known
    simplification, since it reuses -- not extends -- the original calendar.
    """
    ordered = sorted(trades, key=lambda t: (t.exit_ts, t.entry_ts))
    n = len(ordered)
    out: list[Trade] = []
    for slot, source_i in enumerate(idx):
        src = ordered[int(source_i)]
        slot_ts = ordered[slot % n]
        out.append(replace(src, entry_ts=slot_ts.entry_ts, exit_ts=slot_ts.exit_ts, signal_ts=None))
    return out


@dataclass(slots=True)
class MonteCarloResult:
    """Distributional output of running many resampled paths through the account.

    Arrays are all length ``n_paths``, one entry per path, in path order.
    ``runs`` is empty unless ``simulate_paths(..., keep_runs=True)`` -- full
    :class:`~lab.risk.account.AccountRun` objects are not cheap to retain at
    large ``n_paths``.
    """

    n_paths: int
    method: BootstrapMethod
    seed: int
    block_size: int | None
    max_drawdown: np.ndarray
    breached: np.ndarray
    breach_probability: float
    days_survived: np.ndarray
    terminal_equity: np.ndarray
    terminal_equity_percentiles: dict[int, float]
    survival_curve: pd.DataFrame
    expectancy_per_trade: np.ndarray
    expectancy_ci_90: tuple[float, float]
    runs: list[AccountRun] = field(default_factory=list, repr=False)


def simulate_paths(
    trades: Sequence[Trade],
    rules: AccountRules,
    n_paths: int,
    *,
    method: BootstrapMethod = "block",
    seed: int = 0,
    block_size: int | None = None,
    path_length: int | None = None,
    horizons: Sequence[int] = (20, 40, 60),
    keep_runs: bool = False,
) -> MonteCarloResult:
    """Resample ``trades`` ``n_paths`` times and replay each through :class:`AccountRules`.

    ``horizons`` (in trading sessions) drives ``survival_curve``. A path
    counts as *survived* through horizon ``h`` if it reached at least ``h``
    days without breaching, *breached* if it breached at or before day ``h``,
    and is **censored** (excluded from that horizon's probability) if it ran
    out of trades before reaching day ``h`` without ever breaching -- a path
    with only 15 trading days of history simply cannot speak to session 60,
    and silently counting it as "survived" would inflate the answer. See the
    ``censored`` column on the returned ``survival_curve`` before trusting a
    probability computed from a small ``denom``.
    """
    if n_paths <= 0:
        raise ValueError("n_paths must be > 0")
    idx = bootstrap_trades(trades, n_paths, method, seed=seed, block_size=block_size, path_length=path_length)
    sim = AccountSimulator(rules)

    max_dd = np.empty(n_paths)
    breached = np.empty(n_paths, dtype=bool)
    days = np.empty(n_paths, dtype=np.int64)
    terminal = np.empty(n_paths)
    expectancy = np.empty(n_paths)
    runs: list[AccountRun] = []

    survived_count = {h: 0 for h in horizons}
    failed_count = {h: 0 for h in horizons}
    censored_count = {h: 0 for h in horizons}

    for p in range(n_paths):
        run = sim.run(_materialize_path(trades, idx[p]))
        max_dd[p] = run.max_intraday_drawdown
        breached[p] = run.breached
        days[p] = run.days_survived
        terminal[p] = run.final_equity
        expectancy[p] = run.net_pnl / run.trades_taken if run.trades_taken else 0.0
        if keep_runs:
            runs.append(run)

        for h in horizons:
            if run.breached and run.days_survived <= h:
                failed_count[h] += 1
            elif run.days_survived >= h:
                survived_count[h] += 1
            else:
                censored_count[h] += 1

    rows = []
    for h in horizons:
        s, f, c = survived_count[h], failed_count[h], censored_count[h]
        denom = s + f
        rows.append({
            "sessions": h,
            "survival_probability": (s / denom) if denom else float("nan"),
            "survived": s,
            "breached": f,
            "censored": c,
            "n_paths": n_paths,
        })
    survival_curve_df = pd.DataFrame(rows)

    pct = {q: float(np.percentile(terminal, q)) for q in _DEFAULT_PERCENTILES}
    expectancy_ci = (float(np.percentile(expectancy, 5)), float(np.percentile(expectancy, 95)))

    return MonteCarloResult(
        n_paths=n_paths,
        method=method,
        seed=seed,
        block_size=block_size,
        max_drawdown=max_dd,
        breached=breached,
        breach_probability=float(breached.mean()),
        days_survived=days,
        terminal_equity=terminal,
        terminal_equity_percentiles=pct,
        survival_curve=survival_curve_df,
        expectancy_per_trade=expectancy,
        expectancy_ci_90=expectancy_ci,
        runs=runs,
    )
