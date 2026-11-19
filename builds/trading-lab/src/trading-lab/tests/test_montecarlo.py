"""Bootstrap resampling: determinism, shape, and preservation of streaks.

The reason block/stationary bootstraps exist here at all is that losing streaks
are autocorrelated and iid resampling destroys exactly that structure — which
would flatter every drawdown estimate the risk engine produces. The
autocorrelation test below is the one that keeps that claim honest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.risk.montecarlo import bootstrap_trades, permute_order, simulate_paths
from lab.risk.rules import TOPSTEP_FUNDED_50K, TOPSTEP_FUNDED_150K
from tests.helpers import mk_trade


def streaky_trades(n_blocks: int = 8, block: int = 5) -> list:
    """Deliberately autocorrelated: alternating runs of wins and losses.

    One trade per business day so the chronological order the simulator sorts
    into is the order the blocks were built in — a fixture that collides trades
    onto repeated dates would have its streaks scrambled by that sort, and the
    autocorrelation test below would be measuring nothing.
    """
    days = pd.bdate_range("2026-01-05", periods=n_blocks * block).strftime("%Y-%m-%d")
    trades = []
    for i, day in enumerate(days):
        pnl = 200.0 if (i // block) % 2 == 0 else -180.0
        trades.append(mk_trade(day, pnl, mae=min(pnl, 0.0) * 1.2))
    return trades


def lag1_autocorr(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    denom = float((x * x).sum())
    return float((x[:-1] * x[1:]).sum() / denom) if denom > 0 else 0.0


@pytest.mark.parametrize("method", ["iid", "block", "stationary"])
def test_bootstrap_is_deterministic_under_a_fixed_seed(method):
    trades = streaky_trades()
    a = bootstrap_trades(trades, 25, method, seed=7)
    b = bootstrap_trades(trades, 25, method, seed=7)
    c = bootstrap_trades(trades, 25, method, seed=8)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


@pytest.mark.parametrize("method", ["iid", "block", "stationary"])
def test_bootstrap_shape_and_index_range(method):
    trades = streaky_trades()
    idx = bootstrap_trades(trades, 12, method, seed=1)
    assert idx.shape == (12, len(trades))
    assert idx.min() >= 0 and idx.max() < len(trades)


def test_block_bootstrap_preserves_streaks_that_iid_destroys():
    # The claim the module makes in its docstring, tested rather than asserted
    # in prose. The source sequence has strongly positive lag-1 autocorrelation;
    # iid resampling should wash it out to roughly zero, while block resampling
    # should retain most of it.
    trades = streaky_trades()
    pnls = np.array([t.pnl for t in sorted(trades, key=lambda t: (t.exit_ts, t.entry_ts))])
    source_acf = lag1_autocorr(pnls)
    assert source_acf > 0.4, "test fixture is not actually streaky"

    iid_idx = bootstrap_trades(trades, 200, "iid", seed=3)
    block_idx = bootstrap_trades(trades, 200, "block", seed=3, block_size=10)

    iid_acf = np.mean([lag1_autocorr(pnls[row]) for row in iid_idx])
    block_acf = np.mean([lag1_autocorr(pnls[row]) for row in block_idx])

    assert abs(iid_acf) < 0.15
    assert block_acf > 0.4
    assert block_acf > iid_acf


def test_permute_order_reuses_every_trade_exactly_once():
    trades = streaky_trades(n_blocks=4)
    perms = permute_order(trades, 10, seed=2)
    assert perms.shape == (10, len(trades))
    for row in perms:
        assert sorted(row.tolist()) == list(range(len(trades)))


def test_empty_input_is_rejected_rather_than_silently_returning_nothing():
    with pytest.raises(ValueError):
        bootstrap_trades([], 5)
    with pytest.raises(ValueError):
        permute_order([], 5)
    with pytest.raises(ValueError):
        bootstrap_trades(streaky_trades(), 0)


def test_unknown_method_is_rejected():
    with pytest.raises(ValueError):
        bootstrap_trades(streaky_trades(), 5, "gaussian")  # type: ignore[arg-type]


def test_simulate_paths_is_deterministic_and_well_formed():
    trades = streaky_trades()
    a = simulate_paths(trades, TOPSTEP_FUNDED_150K, 50, seed=11)
    b = simulate_paths(trades, TOPSTEP_FUNDED_150K, 50, seed=11)

    assert np.array_equal(a.max_drawdown, b.max_drawdown)
    assert np.array_equal(a.terminal_equity, b.terminal_equity)
    assert a.breach_probability == b.breach_probability
    assert 0.0 <= a.breach_probability <= 1.0
    assert len(a.max_drawdown) == 50
    lo, hi = a.expectancy_ci_90
    assert lo <= hi


def test_survival_curve_reports_censoring_not_just_a_probability():
    # A 40-trade history cannot speak to session 60. The curve must say so
    # rather than quietly counting short paths as survivors.
    trades = streaky_trades()
    mc = simulate_paths(trades, TOPSTEP_FUNDED_150K, 40, seed=5, horizons=(5, 60))
    curve = mc.survival_curve
    assert "censored" in curve.columns
    long_horizon = curve[curve["sessions"] == 60].iloc[0]
    assert long_horizon["censored"] > 0


def test_a_tighter_account_breaches_more_often_on_the_same_trades():
    # Same edge, smaller drawdown allowance -> strictly more breaches. If this
    # ever fails, the account rules are not reaching the simulation.
    trades = streaky_trades()
    tight = simulate_paths(trades, TOPSTEP_FUNDED_50K, 100, seed=4)
    loose = simulate_paths(trades, TOPSTEP_FUNDED_150K, 100, seed=4)
    assert tight.breach_probability >= loose.breach_probability
