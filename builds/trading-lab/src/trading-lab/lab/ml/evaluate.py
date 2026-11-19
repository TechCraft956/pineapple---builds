"""Walk-forward out-of-sample evaluation, and the acceptance rule for keeping a model.

Two things live here, and the second exists specifically to stop the first
from being read charitably.

:func:`walkforward_evaluate` fits a fresh model on every walk-forward fold's
training window, fits :class:`~lab.ml.models.ProbabilityGate`'s threshold on
that *same* training window only, and scores everything -- expectancy with
and without the gate, drawdown, calibration, AUC, permutation importance --
purely on the fold's untouched test window. Nothing here ever fits anything
on a test fold.

:func:`accept_model` is the acceptance test named in the module docstring of
:mod:`lab.ml.models`: a model earns a place in the lab only if it improves
untouched out-of-sample expectancy *and* drawdown, never win rate -- because
win rate is the metric most easily improved by making a system worse (cut
the marginal winners and keep only the sure things, and win rate goes up
while expectancy and trade count both go down). ``accept_model`` computes its
verdict from expectancy and drawdown alone; win rate is carried on
:class:`OOSStats` purely so the verdict's reasons can call it out by name
when it moved the wrong way, not because it is allowed to change the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.inspection import permutation_importance
from sklearn.metrics import brier_score_loss, roc_auc_score

from lab.ml.datasets import Dataset
from lab.ml.models import ModelSpec, ProbabilityGate
from lab.ml.walkforward import Fold, WalkForwardSplitter

__all__ = [
    "OOSStats",
    "FoldResult",
    "WalkForwardResult",
    "Verdict",
    "ModelVerdict",
    "walkforward_evaluate",
    "accept_model",
]


# ---------------------------------------------------------------------------
# stats primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OOSStats:
    """Pooled out-of-sample stats for one signal stream (ungated or gated).

    ``max_drawdown_r`` is <= 0 (0 means no drawdown at all). ``win_rate`` is
    carried for narrative purposes only -- see the module docstring for why
    it never drives the accept/reject decision.
    """

    expectancy_r: float
    max_drawdown_r: float
    win_rate: float
    n_trades: int


def _max_drawdown_r(r_values: np.ndarray) -> float:
    if len(r_values) == 0:
        return 0.0
    curve = np.cumsum(r_values)
    running_max = np.maximum.accumulate(curve)
    return float((curve - running_max).min())


def _oos_stats(r_values: np.ndarray) -> OOSStats:
    n = len(r_values)
    if n == 0:
        return OOSStats(expectancy_r=float("nan"), max_drawdown_r=0.0, win_rate=float("nan"), n_trades=0)
    return OOSStats(
        expectancy_r=float(np.mean(r_values)),
        max_drawdown_r=_max_drawdown_r(r_values),
        win_rate=float(np.mean(r_values > 0)),
        n_trades=n,
    )


def _align_cost(cost_r: pd.Series | float, idx: pd.DatetimeIndex) -> np.ndarray:
    if isinstance(cost_r, pd.Series):
        return cost_r.reindex(idx).fillna(0.0).to_numpy(dtype=float)
    return np.full(len(idx), float(cost_r))


# ---------------------------------------------------------------------------
# walk-forward evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FoldResult:
    """Everything one walk-forward fold produced, scored purely on its test window."""

    fold: Fold
    n_train: int
    n_test: int
    threshold: float
    baseline: OOSStats
    gated: OOSStats
    auc: float
    brier_score: float
    calibration_curve: tuple[np.ndarray, np.ndarray]  # (fraction_of_positives, mean_predicted)
    permutation_importance: pd.Series


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Per-fold results plus the pooled (concatenated-OOS) summary."""

    model_name: str
    folds: list[FoldResult]
    pooled_baseline: OOSStats
    pooled_gated: OOSStats
    pooled_auc: float
    pooled_brier_score: float
    pooled_calibration_curve: tuple[np.ndarray, np.ndarray]
    pooled_permutation_importance: pd.Series

    def accept(self, **kwargs: float) -> "ModelVerdict":
        """Shortcut for ``accept_model(self.pooled_baseline, self.pooled_gated, **kwargs)``."""
        return accept_model(self.pooled_baseline, self.pooled_gated, **kwargs)

    def summary(self) -> str:
        lines = [f"walk-forward: {self.model_name}, {len(self.folds)} usable fold(s)"]
        for i, f in enumerate(self.folds):
            lines.append(
                f"  fold {i}: train={f.n_train} test={f.n_test} thr={f.threshold:.3f} "
                f"baseline={f.baseline.expectancy_r:+.3f}R gated={f.gated.expectancy_r:+.3f}R "
                f"(retained {f.gated.n_trades}/{f.n_test}) dd={f.baseline.max_drawdown_r:.2f}R"
                f"->{f.gated.max_drawdown_r:.2f}R auc={f.auc:.3f} brier={f.brier_score:.3f}"
            )
        lines.append(
            f"pooled: baseline={self.pooled_baseline.expectancy_r:+.3f}R "
            f"(dd {self.pooled_baseline.max_drawdown_r:.2f}R, n={self.pooled_baseline.n_trades}) -> "
            f"gated={self.pooled_gated.expectancy_r:+.3f}R "
            f"(dd {self.pooled_gated.max_drawdown_r:.2f}R, n={self.pooled_gated.n_trades}) | "
            f"auc={self.pooled_auc:.3f} (reported only, not an acceptance criterion) "
            f"brier={self.pooled_brier_score:.3f}"
        )
        return "\n".join(lines)


def walkforward_evaluate(
    dataset: Dataset,
    spec: ModelSpec,
    splitter: WalkForwardSplitter,
    r_outcomes: pd.Series | None = None,
    *,
    seed: int = 0,
    cost_r: pd.Series | float = 0.0,
    calibration_cv: int = 3,
    threshold_candidates: Sequence[float] | None = None,
    min_trades_per_fold: int = 10,
    n_permutation_repeats: int = 5,
) -> WalkForwardResult:
    """Fit-and-score ``spec`` on every fold ``splitter`` produces from ``dataset``.

    ``r_outcomes`` is the realised R multiple per signal, indexed like
    ``dataset.X`` -- defaults to ``dataset.meta["r"]`` (the triple-barrier /
    trade-derived realised R already attached by :func:`lab.ml.build_dataset`).
    Pass your own if you want the gate optimised and scored against a
    different realised-outcome series (e.g. actual booked trade R rather than
    the label module's simplified replay).

    ``cost_r`` is R-denominated friction (commission + slippage expressed as
    a fraction of planned risk) subtracted from every trade, gated or not,
    before any stat is computed -- either a constant or a ``Series`` aligned
    to ``dataset.X.index``.

    For each fold: fit a fresh model (from ``spec.build``, using ``seed``) on
    the fold's train rows; fit :class:`~lab.ml.models.ProbabilityGate` on the
    model's *train*-row probabilities and the *train*-row realised R (never
    test); score both the ungated ("baseline") and gated streams purely on
    the fold's test rows. A fold where either the train or test split has
    fewer than two label classes is skipped outright (nothing meaningful can
    be fit or scored) rather than silently producing a degenerate result.

    Permutation importance is computed with ``scoring="neg_brier_score"`` on
    each fold's *test* rows against the fitted pipeline -- never the fitted
    tree models' impurity-based ``feature_importances_``, which is biased
    toward high-cardinality features and, worse, is computed on training
    data the model already memorised.

    Raises
    ------
    ValueError:
        If no fold produced a usable train/test split at all.
    """
    r_series = (r_outcomes if r_outcomes is not None else dataset.meta["r"]).astype(float)
    r_series = r_series.reindex(dataset.X.index)

    fold_results: list[FoldResult] = []
    pooled_baseline_r: list[float] = []
    pooled_gated_r: list[float] = []
    pooled_y: list[int] = []
    pooled_probs: list[float] = []
    pooled_importance_sum: pd.Series | None = None
    pooled_weight = 0

    for fold in splitter.split(dataset):
        if len(fold.train_idx) == 0 or len(fold.test_idx) == 0:
            continue
        X_train, y_train = dataset.X.loc[fold.train_idx], dataset.y.loc[fold.train_idx]
        X_test, y_test = dataset.X.loc[fold.test_idx], dataset.y.loc[fold.test_idx]
        if y_train.nunique(dropna=True) < 2 or y_test.nunique(dropna=True) < 2:
            continue  # cannot fit/calibrate, or cannot honestly score AUC -- skip, don't fake it

        y_train_arr = y_train.astype("int64").to_numpy()
        y_test_arr = y_test.astype("int64").to_numpy()

        pipeline = spec.build(seed, calibration_cv=calibration_cv)
        pipeline.fit(X_train, y_train_arr)

        train_probs = pipeline.predict_proba(X_train)[:, 1]
        test_probs = pipeline.predict_proba(X_test)[:, 1]

        r_train = r_series.loc[fold.train_idx].to_numpy()
        r_test = r_series.loc[fold.test_idx].to_numpy()
        cost_train = _align_cost(cost_r, fold.train_idx)
        cost_test = _align_cost(cost_r, fold.test_idx)

        gate = ProbabilityGate().fit_threshold(
            train_probs,
            r_train,
            costs=cost_train,
            candidates=threshold_candidates,
            min_trades=min_trades_per_fold,
        )
        mask_test = gate.transform(test_probs)

        net_baseline = r_test - cost_test
        net_gated = net_baseline[mask_test]
        baseline_stats = _oos_stats(net_baseline)
        gated_stats = _oos_stats(net_gated)

        try:
            auc = float(roc_auc_score(y_test_arr, test_probs))
        except ValueError:
            auc = float("nan")
        brier = float(brier_score_loss(y_test_arr, test_probs))
        try:
            n_bins = min(10, max(2, len(y_test_arr) // 5))
            cal_true, cal_pred = calibration_curve(y_test_arr, test_probs, n_bins=n_bins, strategy="quantile")
        except ValueError:
            cal_true, cal_pred = np.array([]), np.array([])
        try:
            pi = permutation_importance(
                pipeline, X_test, y_test_arr,
                scoring="neg_brier_score", n_repeats=n_permutation_repeats, random_state=seed,
            )
            importance = pd.Series(pi.importances_mean, index=X_test.columns, name="importance")
        except Exception:
            importance = pd.Series(0.0, index=X_test.columns, name="importance")

        fold_results.append(
            FoldResult(
                fold=fold, n_train=len(fold.train_idx), n_test=len(fold.test_idx),
                threshold=gate.threshold, baseline=baseline_stats, gated=gated_stats,
                auc=auc, brier_score=brier, calibration_curve=(cal_true, cal_pred),
                permutation_importance=importance,
            )
        )

        pooled_baseline_r.extend(net_baseline.tolist())
        pooled_gated_r.extend(net_gated.tolist())
        pooled_y.extend(y_test_arr.tolist())
        pooled_probs.extend(test_probs.tolist())
        weighted = importance * len(fold.test_idx)
        pooled_importance_sum = weighted if pooled_importance_sum is None else pooled_importance_sum.add(weighted, fill_value=0.0)
        pooled_weight += len(fold.test_idx)

    if not fold_results:
        raise ValueError(
            "no walk-forward fold produced a usable train/test split -- check the "
            "splitter's train/test/step windows against the dataset's time span, and "
            "confirm both label classes appear within every fold's train and test rows"
        )

    pooled_baseline = _oos_stats(np.array(pooled_baseline_r))
    pooled_gated = _oos_stats(np.array(pooled_gated_r))
    pooled_y_arr = np.array(pooled_y)
    pooled_probs_arr = np.array(pooled_probs)
    try:
        pooled_auc = float(roc_auc_score(pooled_y_arr, pooled_probs_arr))
    except ValueError:
        pooled_auc = float("nan")
    pooled_brier = float(brier_score_loss(pooled_y_arr, pooled_probs_arr))
    try:
        pooled_curve = calibration_curve(pooled_y_arr, pooled_probs_arr, n_bins=10, strategy="quantile")
    except ValueError:
        pooled_curve = (np.array([]), np.array([]))
    pooled_importance = (
        (pooled_importance_sum / pooled_weight) if pooled_weight else pd.Series(dtype=float)
    )

    return WalkForwardResult(
        model_name=spec.name,
        folds=fold_results,
        pooled_baseline=pooled_baseline,
        pooled_gated=pooled_gated,
        pooled_auc=pooled_auc,
        pooled_brier_score=pooled_brier,
        pooled_calibration_curve=pooled_curve,
        pooled_permutation_importance=pooled_importance,
    )


# ---------------------------------------------------------------------------
# the acceptance rule
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    KEEP = "KEEP"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class ModelVerdict:
    """A hard keep/reject decision with the reasons spelled out.

    Use :meth:`summary` for a one-paragraph readout; the individual fields
    are there for anything that wants to assert on the decision directly
    rather than parse prose.
    """

    verdict: Verdict
    reasons: list[str]
    baseline: OOSStats
    gated: OOSStats
    min_expectancy_gain: float
    max_dd_tolerance: float

    def summary(self) -> str:
        return f"{self.verdict.value}: " + " | ".join(self.reasons)


def accept_model(
    baseline: OOSStats,
    gated: OOSStats,
    *,
    min_expectancy_gain: float = 0.0,
    max_dd_tolerance: float = 0.0,
) -> ModelVerdict:
    """KEEP the gate only if it improves *both* untouched OOS expectancy and drawdown.

    ``min_expectancy_gain`` is the minimum required increase in expectancy_r
    (gated - baseline); ``max_dd_tolerance`` is how much *more* negative
    ``max_drawdown_r`` is allowed to get (gated vs baseline) and still pass.
    Both default to 0.0 -- "no worse, ideally better" -- pass positive
    numbers to require a real margin (recommended: a model that only just
    clears 0.0 on noisy OOS folds is not a model anyone should trust).

    Win rate never appears in the KEEP/REJECT logic. It is read from
    ``baseline``/``gated`` purely so the verdict can flag the specific
    failure mode this function exists to catch: a gate that raises win rate
    while expectancy gets worse (or does not improve enough) is REJECTed
    exactly the same as one that raises nothing at all, and the reason text
    says so explicitly rather than leaving a reader to notice the win-rate
    number looked good and assume that means anything.
    """
    reasons: list[str] = []

    expectancy_gain = gated.expectancy_r - baseline.expectancy_r
    expectancy_ok = expectancy_gain >= min_expectancy_gain
    reasons.append(
        f"expectancy {baseline.expectancy_r:+.4f}R -> {gated.expectancy_r:+.4f}R "
        f"({expectancy_gain:+.4f}R, requires >= {min_expectancy_gain:+.4f}R): "
        f"{'PASS' if expectancy_ok else 'FAIL'}"
    )

    dd_change = gated.max_drawdown_r - baseline.max_drawdown_r  # negative = worse (more drawdown)
    dd_ok = dd_change >= -max_dd_tolerance
    reasons.append(
        f"max drawdown {baseline.max_drawdown_r:.4f}R -> {gated.max_drawdown_r:.4f}R "
        f"({dd_change:+.4f}R, tolerance {max_dd_tolerance:.4f}R worse allowed): "
        f"{'PASS' if dd_ok else 'FAIL'}"
    )

    if not np.isnan(gated.win_rate) and not np.isnan(baseline.win_rate) and gated.win_rate > baseline.win_rate:
        note = "expectancy also improved enough" if expectancy_ok else "expectancy did NOT improve enough"
        reasons.append(
            f"win rate improved {baseline.win_rate:.1%} -> {gated.win_rate:.1%}, but win rate is "
            f"never a keep criterion here ({note}) -- it is the metric most easily improved by "
            "making the system worse (cut marginal winners, keep only sure things, watch win "
            "rate rise while expectancy and trade count both fall)."
        )

    verdict = Verdict.KEEP if (expectancy_ok and dd_ok) else Verdict.REJECT
    return ModelVerdict(verdict, reasons, baseline, gated, min_expectancy_gain, max_dd_tolerance)
