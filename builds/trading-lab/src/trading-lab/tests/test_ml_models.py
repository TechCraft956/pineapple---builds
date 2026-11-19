"""Tests for lab.ml.models (escalation ladder, ProbabilityGate) and the
accept_model acceptance rule in lab.ml.evaluate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.ml.evaluate import OOSStats, Verdict, accept_model
from lab.ml.models import (
    ESCALATION_ORDER,
    MODEL_REGISTRY,
    EscalationError,
    ProbabilityGate,
    get_model,
)


def _classification_frame(n: int = 240, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.normal(size=n),
            "c": rng.normal(size=n),
            "day_of_week": pd.Categorical(rng.integers(0, 5, size=n)),
        }
    )
    logits = 1.4 * X["a"] - 0.6 * X["b"]
    p = 1.0 / (1.0 + np.exp(-logits))
    y = (rng.uniform(size=n) < p).astype(int)
    return X, y


# ---------------------------------------------------------------------------
# escalation order
# ---------------------------------------------------------------------------


def test_escalation_order_constant_matches_the_mandated_ladder():
    assert ESCALATION_ORDER[:3] == ("logistic", "random_forest", "gradient_boosting")


def test_get_model_refuses_random_forest_before_logistic_is_cleared():
    with pytest.raises(EscalationError):
        get_model("random_forest", seed=0)


def test_get_model_refuses_gradient_boosting_before_both_priors_are_cleared():
    with pytest.raises(EscalationError):
        get_model("gradient_boosting", seed=0, cleared=("logistic",))
    # succeeds once both priors are cleared
    pipeline = get_model("gradient_boosting", seed=0, cleared=("logistic", "random_forest"))
    assert pipeline is not None


def test_get_model_logistic_needs_nothing_cleared():
    pipeline = get_model("logistic", seed=0)
    assert pipeline is not None


def test_get_model_sequential_raises_not_implemented_once_cleared():
    with pytest.raises(NotImplementedError):
        get_model("sequential", seed=0, cleared=("logistic", "random_forest", "gradient_boosting"))


def test_get_model_unknown_name_raises_key_error():
    with pytest.raises(KeyError):
        get_model("neural_prophecy", seed=0)


@pytest.mark.parametrize("name", ["logistic", "random_forest", "gradient_boosting"])
def test_every_registered_model_fits_and_predicts_calibrated_probabilities(name):
    X, y = _classification_frame()
    pipeline = MODEL_REGISTRY[name].build(0, calibration_cv=3)
    pipeline.fit(X, y)
    probs = pipeline.predict_proba(X)[:, 1]
    assert probs.shape == (len(X),)
    assert np.all((probs >= 0.0) & (probs <= 1.0))


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_same_seed_gives_identical_predictions():
    X, y = _classification_frame()
    p1 = MODEL_REGISTRY["logistic"].build(20260805, calibration_cv=3)
    p1.fit(X, y)
    probs1 = p1.predict_proba(X)[:, 1]

    p2 = MODEL_REGISTRY["logistic"].build(20260805, calibration_cv=3)
    p2.fit(X, y)
    probs2 = p2.predict_proba(X)[:, 1]

    np.testing.assert_array_equal(probs1, probs2)


def test_same_seed_gives_identical_chosen_threshold():
    X, y = _classification_frame()
    r = np.where(y == 1, 1.0, -1.0)

    def fit_and_gate(seed: int) -> float:
        pipeline = MODEL_REGISTRY["logistic"].build(seed, calibration_cv=3)
        pipeline.fit(X, y)
        probs = pipeline.predict_proba(X)[:, 1]
        gate = ProbabilityGate().fit_threshold(probs, r, costs=0.05, min_trades=10)
        return gate.threshold

    thr1 = fit_and_gate(20260805)
    thr2 = fit_and_gate(20260805)
    assert thr1 == thr2


# ---------------------------------------------------------------------------
# ProbabilityGate.fit_threshold: never sees anything but what it's handed
# ---------------------------------------------------------------------------


def test_fit_threshold_result_depends_only_on_its_own_arguments():
    """By construction, fit_threshold takes no Dataset/splitter/bars -- only
    plain arrays. This proves that a 'test slice' existing elsewhere in the
    caller's scope cannot influence the fit no matter how it's mutated,
    because the function never receives it in the first place."""
    rng = np.random.default_rng(1)
    train_probs = rng.uniform(size=80)
    train_r = rng.normal(loc=0.1, scale=1.0, size=80)

    gate_a = ProbabilityGate().fit_threshold(train_probs, train_r, costs=0.02, min_trades=5)
    threshold_a = gate_a.threshold

    # Define a "test slice" only after the fit above, then mutate it wildly.
    test_probs = rng.uniform(size=40)
    test_r = rng.normal(loc=-5.0, scale=1.0, size=40)  # deliberately terrible
    test_probs[:] = 1.0
    test_r[:] = -100.0

    # Refit on the exact same train arrays: nothing about the "test" data
    # above is reachable from fit_threshold, so the result must be identical.
    gate_b = ProbabilityGate().fit_threshold(train_probs, train_r, costs=0.02, min_trades=5)
    assert gate_b.threshold == threshold_a


def test_fit_threshold_maximises_net_expectancy_not_accuracy():
    """A cutoff that keeps only the highest-probability signals should
    retain a subset with clearly higher net expectancy than the full
    population when the probabilities are actually informative."""
    rng = np.random.default_rng(2)
    n = 300
    probs = rng.uniform(size=n)
    # r is genuinely correlated with prob: higher prob -> better outcomes.
    r = (probs - 0.5) * 4 + rng.normal(scale=0.5, size=n)

    gate = ProbabilityGate().fit_threshold(probs, r, costs=0.0, min_trades=20)
    mask = gate.transform(probs)
    assert mask.sum() >= 20
    assert r[mask].mean() > r.mean()


def test_fit_threshold_rejects_empty_input():
    with pytest.raises(ValueError):
        ProbabilityGate().fit_threshold(np.array([]), np.array([]))


def test_fit_threshold_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        ProbabilityGate().fit_threshold(np.array([0.1, 0.2]), np.array([0.1]))


def test_transform_before_fit_raises():
    with pytest.raises(RuntimeError):
        ProbabilityGate().transform(np.array([0.5]))


def test_fit_threshold_falls_back_to_gate_nothing_when_min_trades_unreachable():
    probs = np.array([0.1, 0.2, 0.3])
    r = np.array([1.0, -1.0, 1.0])
    gate = ProbabilityGate().fit_threshold(probs, r, min_trades=100)
    assert gate.threshold == 0.0
    assert gate.transform(probs).all()


# ---------------------------------------------------------------------------
# accept_model: the acceptance rule this whole module exists to enforce
# ---------------------------------------------------------------------------


def test_accept_model_keeps_a_model_that_improves_both_expectancy_and_drawdown():
    baseline = OOSStats(expectancy_r=0.10, max_drawdown_r=-8.0, win_rate=0.42, n_trades=200)
    gated = OOSStats(expectancy_r=0.25, max_drawdown_r=-4.0, win_rate=0.45, n_trades=140)
    verdict = accept_model(baseline, gated, min_expectancy_gain=0.05, max_dd_tolerance=0.5)
    assert verdict.verdict is Verdict.KEEP


def test_accept_model_rejects_win_rate_improvement_that_worsens_expectancy():
    """The exact failure mode the acceptance rule exists to prevent: a gate
    that cuts marginal-but-still-profitable trades, raising win rate while
    expectancy gets worse, must be REJECTed -- not KEPT because a metric
    table shows a bigger win-rate number."""
    baseline = OOSStats(expectancy_r=0.30, max_drawdown_r=-5.0, win_rate=0.40, n_trades=300)
    gated = OOSStats(expectancy_r=0.10, max_drawdown_r=-5.0, win_rate=0.65, n_trades=60)

    verdict = accept_model(baseline, gated, min_expectancy_gain=0.0, max_dd_tolerance=0.0)

    assert verdict.verdict is Verdict.REJECT
    assert gated.win_rate > baseline.win_rate  # sanity: the trap is real
    assert any("win rate" in r.lower() for r in verdict.reasons)
    assert any("expectancy" in r.lower() and "FAIL" in r for r in verdict.reasons)


def test_accept_model_rejects_on_drawdown_alone_even_with_expectancy_gain():
    baseline = OOSStats(expectancy_r=0.10, max_drawdown_r=-3.0, win_rate=0.40, n_trades=200)
    gated = OOSStats(expectancy_r=0.20, max_drawdown_r=-9.0, win_rate=0.40, n_trades=180)
    verdict = accept_model(baseline, gated, min_expectancy_gain=0.0, max_dd_tolerance=1.0)
    assert verdict.verdict is Verdict.REJECT
    assert any("drawdown" in r.lower() and "FAIL" in r for r in verdict.reasons)


def test_accept_model_summary_reads_as_a_decision():
    baseline = OOSStats(expectancy_r=0.10, max_drawdown_r=-3.0, win_rate=0.40, n_trades=200)
    gated = OOSStats(expectancy_r=0.05, max_drawdown_r=-3.0, win_rate=0.40, n_trades=200)
    verdict = accept_model(baseline, gated)
    summary = verdict.summary()
    assert summary.startswith("REJECT:") or summary.startswith("KEEP:")
