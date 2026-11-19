"""Tests for lab.robustness: drop-the-best, sensitivity/fragility, and regime
stability. None of these import lab.backtest or lab.strategies -- trades are
built directly from lab.core.types.Trade, and run_fn callables are plain
Python functions."""

from __future__ import annotations

import pandas as pd
import pytest

from lab.core.types import LONG, ExitReason, Trade
from lab.robustness.dropn import drop_best
from lab.robustness.regimes import compare_regimes, stability_verdict
from lab.robustness.sensitivity import fragility_score, parameter_sweep, stress_costs


def _trade(entry_ts: pd.Timestamp, pnl: float, symbol: str = "ES", r_multiple: float | None = None) -> Trade:
    risk = 100.0
    exit_price_offset = (r_multiple if r_multiple is not None else pnl / risk)
    return Trade(
        symbol=symbol, strategy="s", direction=LONG, entry_ts=entry_ts, entry_price=100.0,
        exit_ts=entry_ts + pd.Timedelta(minutes=10), exit_price=100.0 + exit_price_offset,
        qty=1.0, pnl=pnl, commission=1.0, slippage_cost=0.0, risk_dollars=risk,
        exit_reason=ExitReason.TARGET, tag="t",
    )


# ---------------------------------------------------------------------------
# drop_best
# ---------------------------------------------------------------------------


def test_drop_best_by_trade_monotonically_reduces_headline_stats():
    """All distinct, positive pnls -- dropping the current-best trade always
    strictly lowers both the remaining net_pnl and expectancy_r."""
    base = pd.Timestamp("2024-02-01 14:30", tz="UTC")
    pnls = [500, 420, 340, 260, 180, 100, 60, 20]
    trades = [_trade(base + pd.Timedelta(days=i), pnl) for i, pnl in enumerate(pnls)]

    net_pnls = []
    expectancies = []
    for n in range(len(trades)):
        result = drop_best(trades, n, by="trade")
        net_pnls.append(result.after["net_pnl"])
        expectancies.append(result.after["expectancy_r"])

    assert all(a > b for a, b in zip(net_pnls, net_pnls[1:])), net_pnls
    assert all(a > b for a, b in zip(expectancies, expectancies[1:])), expectancies


def test_drop_best_by_day_removes_more_trades_than_by_trade_when_a_day_stacks_winners():
    """One trading day holds two strong winners; by='day' must remove both,
    while by='trade' with the same n only removes the single best trade."""
    day1 = pd.Timestamp("2024-02-05 14:00", tz="UTC")
    day2 = pd.Timestamp("2024-02-06 14:00", tz="UTC")
    trades = [
        _trade(day1, 500),
        _trade(day1 + pd.Timedelta(hours=1), 300),  # same day as the best trade
        _trade(day2, 50),
        _trade(day2 + pd.Timedelta(hours=1), -20),
    ]

    by_trade = drop_best(trades, 1, by="trade")
    by_day = drop_best(trades, 1, by="day")

    assert by_trade.n_dropped_trades == 1
    assert by_day.n_dropped_trades == 2
    assert by_day.after["net_pnl"] < by_trade.after["net_pnl"]


def test_drop_best_n_zero_is_a_no_op():
    trades = [_trade(pd.Timestamp("2024-01-01", tz="UTC"), 100)]
    result = drop_best(trades, 0, by="trade")
    assert result.n_dropped_trades == 0
    assert result.before["net_pnl"] == result.after["net_pnl"]


def test_drop_best_rejects_bad_by_value():
    trades = [_trade(pd.Timestamp("2024-01-01", tz="UTC"), 100)]
    with pytest.raises(ValueError):
        drop_best(trades, 1, by="week")


def test_drop_best_accepts_a_backtest_result_like_object():
    class _FakeResult:
        def __init__(self, trades):
            self.trades = trades

    trades = [_trade(pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=i), 50 * (i + 1)) for i in range(4)]
    result = drop_best(_FakeResult(trades), 1, by="trade")
    assert result.n_dropped_trades == 1


# ---------------------------------------------------------------------------
# sensitivity: parameter_sweep / stress_costs
# ---------------------------------------------------------------------------


def test_parameter_sweep_auto_rules_for_int_float_bool():
    def run_fn(params):
        penalty = abs(params["lookback"] - 20) * 0.001 + abs(params["threshold"] - 1.0) * 0.05
        penalty += 0.0 if params["use_filter"] else 0.02
        return {"expectancy_r": 0.30 - penalty}

    surface = parameter_sweep(run_fn, {"lookback": 20, "threshold": 1.0, "use_filter": True})

    base_row = surface[surface["param"] == "<base>"]
    assert len(base_row) == 1
    assert base_row["metric"].iloc[0] == pytest.approx(0.30)

    lookback_rows = surface[surface["param"] == "lookback"]
    assert set(lookback_rows["pct_step"]) == {-0.2, -0.1, 0.1, 0.2}
    assert all(isinstance(v, int) for v in lookback_rows["value"])

    bool_rows = surface[surface["param"] == "use_filter"]
    assert list(bool_rows["value"]) == [False]


def test_parameter_sweep_requires_explicit_values_for_categoricals():
    def run_fn(params):
        return {"expectancy_r": 0.1}

    with pytest.raises(TypeError):
        parameter_sweep(run_fn, {"mode": "breakout"})

    # works once explicit candidates are supplied
    surface = parameter_sweep(run_fn, {"mode": "breakout"}, perturbations={"mode": ["reversal", "breakout"]})
    modes = set(surface[surface["param"] == "mode"]["value"])
    assert modes == {"reversal"}  # base value excluded from its own candidate list


def test_stress_costs_builds_the_cartesian_grid():
    calls = []

    def run_fn(params):
        calls.append((params["extra_slip_ticks"], params["commission_mult"]))
        return {"expectancy_r": 0.2 - 0.01 * params["extra_slip_ticks"] - 0.05 * (params["commission_mult"] - 1)}

    surface = stress_costs(run_fn, {}, extra_slip_ticks=(1, 2), commission_mult=(1.0, 1.25))
    assert len(surface) == 4
    assert set(zip(surface["extra_slip_ticks"], surface["commission_mult"])) == {
        (1, 1.0), (1, 1.25), (2, 1.0), (2, 1.25),
    }
    assert len(calls) == 4


# ---------------------------------------------------------------------------
# fragility_score: shape, not just values
# ---------------------------------------------------------------------------


def _surface(base_metric: float, degradations: dict[float, float]) -> pd.DataFrame:
    """Build a minimal parameter_sweep-shaped surface for one parameter 'p'
    from a {pct_step: degradation_fraction} map, where degradation_fraction
    is (base - metric) / |base|."""
    rows = [{"param": "<base>", "pct_step": 0.0, "metric": base_metric, "base_metric": base_metric}]
    for step, d in degradations.items():
        rows.append(
            {"param": "p", "pct_step": step, "metric": base_metric * (1 - d), "base_metric": base_metric}
        )
    return pd.DataFrame(rows)


def test_fragility_score_ranks_a_cliff_shaped_surface_above_a_smooth_one():
    """Both surfaces share the same worst-case degradation (0.20 at the
    +-20% points) -- the only difference is how they get there: the smooth
    one degrades gradually, the cliff one is essentially flat near the base
    and then collapses. fragility_score must rank the cliff higher."""
    # Same worst-case (0.20 at +-20%) reached two different ways: "smooth" is
    # a quadratic-in-perturbation degradation (constant, modest curvature,
    # the shape of a real edge nudged off its exact parameters); "cliff" is
    # flat near the base and then jumps (large curvature right where the
    # jump happens), the shape of a rule fit to its exact backtested values.
    smooth = _surface(0.30, {-0.2: 0.20, -0.1: 0.05, 0.1: 0.05, 0.2: 0.20})
    cliff = _surface(0.30, {-0.2: 0.20, -0.1: 0.02, 0.1: 0.02, 0.2: 0.20})

    smooth_score = fragility_score(smooth)
    cliff_score = fragility_score(cliff)

    # same worst-case drop by construction
    assert smooth_score.worst_relative_drop == pytest.approx(cliff_score.worst_relative_drop, abs=1e-9)
    # but the cliff's curvature -- and therefore its overall score -- is higher
    assert cliff_score.cliffness > smooth_score.cliffness, (smooth_score, cliff_score)
    assert cliff_score.score > smooth_score.score


def test_fragility_score_is_zero_for_a_flat_surface():
    flat = _surface(0.30, {-0.2: 0.0, -0.1: 0.0, 0.1: 0.0, 0.2: 0.0})
    result = fragility_score(flat)
    assert result.score == pytest.approx(0.0)


def test_fragility_score_ignores_improvements():
    improving = _surface(0.30, {-0.2: -0.5, -0.1: -0.2, 0.1: -0.2, 0.2: -0.5})  # metric improves everywhere
    result = fragility_score(improving)
    assert result.worst_relative_drop == pytest.approx(0.0)


def test_fragility_score_handles_empty_surface():
    surface = pd.DataFrame([{"param": "<base>", "pct_step": 0.0, "metric": 0.3, "base_metric": 0.3}])
    result = fragility_score(surface)
    assert result.score == 0.0


# ---------------------------------------------------------------------------
# regimes
# ---------------------------------------------------------------------------


def test_compare_regimes_flags_a_sign_flip_as_unstable():
    # UTC times chosen so they land in LONDON/NY_RTH (both windows are defined
    # in America/Chicago wall-clock time); January so the whole 25-day span
    # stays on one side of the US DST transition.
    london = pd.Timestamp("2024-01-08 09:00", tz="UTC")  # CT 03:00 -> inside LONDON (02:00-07:00 CT)
    us = pd.Timestamp("2024-01-08 16:00", tz="UTC")  # CT 10:00 -> inside NY_RTH (08:30-15:00 CT)

    trades = []
    for i in range(25):
        trades.append(_trade(london + pd.Timedelta(days=i), 60.0))  # consistently profitable
    for i in range(25):
        trades.append(_trade(us + pd.Timedelta(days=i), -40.0))  # consistently losing

    result = compare_regimes(trades, min_trades=10)
    session_rows = result.frame[result.frame["dimension"] == "session"]
    assert set(session_rows["bucket"]) >= {"london", "ny_rth"}
    assert not result.verdict.stable
    assert any("sign" in r.lower() for r in result.verdict.reasons)


def test_stability_verdict_stable_when_buckets_agree():
    frame = pd.DataFrame(
        [
            {"dimension": "d", "bucket": "a", "n_trades": 50, "expectancy_r": 0.20},
            {"dimension": "d", "bucket": "b", "n_trades": 50, "expectancy_r": 0.22},
            {"dimension": "d", "bucket": "c", "n_trades": 50, "expectancy_r": 0.18},
        ]
    )
    verdict = stability_verdict(frame, min_trades=20, max_relative_spread=1.5)
    assert verdict.stable


def test_stability_verdict_excludes_thin_buckets_from_the_check():
    frame = pd.DataFrame(
        [
            {"dimension": "d", "bucket": "thin", "n_trades": 3, "expectancy_r": -5.0},
            {"dimension": "d", "bucket": "a", "n_trades": 50, "expectancy_r": 0.20},
            {"dimension": "d", "bucket": "b", "n_trades": 50, "expectancy_r": 0.21},
        ]
    )
    verdict = stability_verdict(frame, min_trades=20, max_relative_spread=1.5)
    assert verdict.stable  # the wild thin bucket is excluded, not counted
    assert any("thin" in r for r in verdict.reasons)
