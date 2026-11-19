"""The escalation ladder of candidate models, and the gate that filters signals.

The model in this lab never predicts direction -- a strategy has already
qualified a setup by the time anything here sees it. All it answers is: given
that this setup fired, what is the probability price reaches +1R before -1R
in the horizon the labels were built with? That means its entire output is a
probability, never a raw score, which is why every model built here is wrapped
in :class:`~sklearn.calibration.CalibratedClassifierCV` -- an uncalibrated
"probability" that a threshold gets tuned against is just a score with false
precision.

Escalation is mandatory and enforced by :func:`get_model`, not left to good
intentions: logistic regression first, random forest only once logistic has
been tried, gradient boosting only once both simpler models have been tried,
and anything sequential (an RNN/transformer over the raw bar sequence) only
after all three of the above. A caller cannot build ``"gradient_boosting"``
without passing ``cleared=("logistic", "random_forest")`` -- see
:class:`EscalationError`. "Sequential" has no implementation in this lab (it
would need a dependency this environment does not have); requesting it raises
:class:`NotImplementedError` with the reason spelled out, not a silent no-op.

:class:`ProbabilityGate` is the object that actually turns a probability into
a filtering decision. Its threshold is never eyeballed off a metric table --
:meth:`ProbabilityGate.fit_threshold` chooses it by maximising expectancy net
of cost on exactly the array it is handed, nothing else. It takes no
``Dataset``, no splitter, no bars -- only ``probs``/``outcomes_r``/``costs``
arrays -- specifically so a caller cannot accidentally hand it anything but a
training slice; see :mod:`lab.ml.evaluate` for the walk-forward loop that
relies on that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import numpy.typing as npt
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer, make_column_selector
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

__all__ = [
    "ModelSpec",
    "MODEL_REGISTRY",
    "ESCALATION_ORDER",
    "EscalationError",
    "get_model",
    "ProbabilityGate",
]


# ---------------------------------------------------------------------------
# shared preprocessing
# ---------------------------------------------------------------------------


def _preprocessor(*, scale: bool) -> ColumnTransformer:
    """Impute + (optionally) scale numeric columns; impute + one-hot categoricals.

    One-hot encoding categoricals for every model (rather than relying on
    tree models' native categorical support) keeps the three model builders
    interchangeable and keeps this module independent of any one estimator's
    dtype-detection quirks.
    """
    numeric_steps: list[tuple[str, Any]] = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))
    numeric_pipe = Pipeline(numeric_steps)
    categorical_pipe = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, make_column_selector(dtype_exclude="category")),
            ("cat", categorical_pipe, make_column_selector(dtype_include="category")),
        ],
        remainder="drop",
    )


def _build(
    estimator: Any,
    *,
    scale: bool,
    calibration_cv: int,
    calibration_method: str = "sigmoid",
) -> Pipeline:
    """Wrap ``estimator`` in preprocessing, then in probability calibration.

    The returned object is a single-step ``Pipeline`` named ``"clf"`` --
    every model built by this module shares that step name, which keeps
    downstream code (fit-param forwarding, permutation importance) uniform
    across the three model types.
    """
    inner = Pipeline([("preprocess", _preprocessor(scale=scale)), ("estimator", estimator)])
    calibrated = CalibratedClassifierCV(inner, method=calibration_method, cv=calibration_cv)
    return Pipeline([("clf", calibrated)])


class _AutoBalancedXGB(BaseEstimator, ClassifierMixin):
    """sklearn-compatible wrapper around ``xgboost.XGBClassifier`` that derives
    ``scale_pos_weight`` from the training labels at fit time.

    XGBoost has no ``class_weight="balanced"`` of its own (unlike
    :class:`~sklearn.linear_model.LogisticRegression`,
    :class:`~sklearn.ensemble.RandomForestClassifier` and
    :class:`~sklearn.ensemble.HistGradientBoostingClassifier`, all of which
    do), so this computes the equivalent ``neg/pos`` ratio itself instead of
    asking every caller to remember to. Only ever instantiated when
    ``xgboost`` is importable -- see :func:`_build_gradient_boosting`.
    """

    def __init__(self, seed: int = 0, **xgb_kwargs: Any) -> None:
        self.seed = seed
        self.xgb_kwargs = xgb_kwargs

    def fit(self, X: Any, y: Any, **fit_params: Any) -> "_AutoBalancedXGB":
        from xgboost import XGBClassifier  # local: only reached if importable

        y_arr = np.asarray(y)
        n_pos = float((y_arr == 1).sum())
        n_neg = float((y_arr == 0).sum())
        spw = n_neg / n_pos if n_pos > 0 else 1.0
        self.model_ = XGBClassifier(random_state=self.seed, scale_pos_weight=spw, **self.xgb_kwargs)
        self.model_.fit(X, y, **fit_params)
        self.classes_ = self.model_.classes_
        return self

    def predict(self, X: Any) -> np.ndarray:
        return self.model_.predict(X)

    def predict_proba(self, X: Any) -> np.ndarray:
        return self.model_.predict_proba(X)


# ---------------------------------------------------------------------------
# the three implemented rungs
# ---------------------------------------------------------------------------


def _build_logistic(seed: int, *, calibration_cv: int = 3) -> Pipeline:
    """Logistic regression: the mandatory first rung. Linear, well-calibrated
    by construction (Platt scaling barely has to do any work), and the
    baseline every fancier model must actually beat out-of-sample."""
    est = LogisticRegression(class_weight="balanced", random_state=seed, max_iter=2000, C=1.0)
    return _build(est, scale=True, calibration_cv=calibration_cv)


def _build_random_forest(seed: int, *, calibration_cv: int = 3) -> Pipeline:
    """Random forest: the second rung, tried only once logistic has been.
    Depth and leaf size are kept shallow on purpose -- this is a filter on an
    edge that already exists, not a search for a new one, and a deep forest
    on a modest signal-count dataset is exactly how a lab convinces itself a
    coin flip has structure."""
    est = RandomForestClassifier(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=seed,
        n_jobs=1,
    )
    return _build(est, scale=False, calibration_cv=calibration_cv)


def _build_gradient_boosting(seed: int, *, calibration_cv: int = 3) -> Pipeline:
    """Gradient boosting: the third and last rung with an implementation in
    this lab. Uses ``xgboost`` if it is importable, otherwise
    :class:`~sklearn.ensemble.HistGradientBoostingClassifier` -- which is
    what actually runs in this environment, since xgboost is not installed
    here."""
    try:
        from xgboost import XGBClassifier  # noqa: F401  (import-checked only)
    except ImportError:
        est = HistGradientBoostingClassifier(
            max_iter=200,
            max_depth=4,
            learning_rate=0.08,
            class_weight="balanced",
            random_state=seed,
        )
        return _build(est, scale=False, calibration_cv=calibration_cv)
    est = _AutoBalancedXGB(seed=seed, n_estimators=200, max_depth=3, learning_rate=0.1, eval_metric="logloss")
    return _build(est, scale=False, calibration_cv=calibration_cv)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One rung of the escalation ladder.

    ``build(seed, *, calibration_cv=3)`` returns a fresh, unfitted sklearn
    ``Pipeline`` -- imputation and (for logistic only) scaling, class-weight
    balancing baked into the estimator, and the whole thing wrapped in
    :class:`~sklearn.calibration.CalibratedClassifierCV` so its output is a
    genuine, calibrated probability.
    """

    name: str
    description: str
    build: Callable[..., Pipeline]


ESCALATION_ORDER: tuple[str, ...] = ("logistic", "random_forest", "gradient_boosting", "sequential")

#: Only the first three rungs have an implementation here -- a sequential
#: model over raw bar sequences would need a dependency (e.g. torch) this lab
#: does not carry, and per the escalation rule it should not be reached for
#: real until logistic, random_forest and gradient_boosting have all failed
#: to earn their place anyway.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "logistic": ModelSpec(
        "logistic",
        "Logistic regression, class-balanced, calibrated. The mandatory first rung.",
        _build_logistic,
    ),
    "random_forest": ModelSpec(
        "random_forest",
        "Shallow class-balanced random forest, calibrated. Second rung.",
        _build_random_forest,
    ),
    "gradient_boosting": ModelSpec(
        "gradient_boosting",
        "xgboost if installed, else HistGradientBoostingClassifier, calibrated. Third rung.",
        _build_gradient_boosting,
    ),
}


class EscalationError(RuntimeError):
    """Raised when a caller tries to build a model out of the mandated escalation order."""


def get_model(name: str, seed: int, *, cleared: Sequence[str] = (), calibration_cv: int = 3) -> Pipeline:
    """Build model ``name``, refusing to skip ahead in the escalation ladder.

    ``cleared`` is the set of rung names that have already been tried and
    have earned their place (typically via
    :func:`lab.ml.evaluate.accept_model` returning ``KEEP``, or at minimum
    having been walk-forward evaluated). Building ``"random_forest"``
    requires ``"logistic"`` in ``cleared``; building ``"gradient_boosting"``
    requires both. This is the actual enforcement mechanism the escalation
    rule relies on -- not a comment asking a future caller to please try
    logistic first.
    """
    if name not in ESCALATION_ORDER:
        raise KeyError(f"unknown model {name!r}; escalation order is {ESCALATION_ORDER}")
    idx = ESCALATION_ORDER.index(name)
    required = ESCALATION_ORDER[:idx]
    missing = [m for m in required if m not in cleared]
    if missing:
        raise EscalationError(
            f"cannot build {name!r} before clearing {missing} -- the lab escalates "
            f"{' -> '.join(ESCALATION_ORDER)}, in order, and each rung must earn its "
            "place (walk-forward evaluated, ideally KEEP-verdicted) before the next "
            "is tried. Pass cleared=(...) with the rungs already attempted."
        )
    if name not in MODEL_REGISTRY:
        raise NotImplementedError(
            f"{name!r} is in the escalation order but has no implementation in this "
            "lab (a sequential model needs a dependency this environment does not "
            "carry). Implement it in lab/ml/models.py before requesting it."
        )
    return MODEL_REGISTRY[name].build(seed, calibration_cv=calibration_cv)


# ---------------------------------------------------------------------------
# the probability gate
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProbabilityGate:
    """Filters signals by predicted probability of reaching +1R before -1R.

    A gate with no threshold set passes nothing usefully -- call
    :meth:`fit_threshold` (or set ``threshold`` directly, e.g. to reproduce a
    previously-fit value) before :meth:`transform`.
    """

    threshold: float | None = None
    fit_info: Mapping[str, Any] | None = field(default=None, repr=False)

    def fit_threshold(
        self,
        probs: npt.ArrayLike,
        outcomes_r: npt.ArrayLike,
        costs: npt.ArrayLike | float = 0.0,
        *,
        candidates: Sequence[float] | None = None,
        min_trades: int = 10,
    ) -> "ProbabilityGate":
        """Choose the cutoff that maximises expectancy net of cost.

        ``probs``, ``outcomes_r`` (realised R multiple per signal) and
        ``costs`` (R-denominated friction subtracted from every retained
        trade) must already be exactly the slice the caller wants this fit
        to see -- this method has no notion of folds, splits or holdouts and
        never will; it trusts its arguments completely, which is exactly why
        it must never be handed anything but a training slice. See
        :func:`lab.ml.evaluate.walkforward_evaluate` for the loop that
        enforces that boundary.

        Candidates default to every distinct probability observed (so the
        search is exhaustive over the data given, not a coarse grid), and
        the threshold that clears ``min_trades`` retained signals while
        maximising mean net R wins ties by being the first found while
        scanning candidates in ascending order -- i.e. the lowest
        (least-restrictive) threshold among equally good ones. Both of these
        make the result deterministic for a fixed input.

        Raises
        ------
        ValueError:
            If ``probs``/``outcomes_r`` are empty, mismatched in shape, or
            no candidate threshold retains at least ``min_trades``
            signals -- in the last case the gate falls back to
            ``threshold=0.0`` (gate nothing) rather than raising, since "the
            model isn't confident enough to filter anything" is a valid,
            informative outcome, not a bug.
        """
        probs_arr = np.asarray(probs, dtype=float)
        r_arr = np.asarray(outcomes_r, dtype=float)
        if probs_arr.shape != r_arr.shape:
            raise ValueError(
                f"probs and outcomes_r must share a shape, got {probs_arr.shape} vs {r_arr.shape}"
            )
        if probs_arr.ndim != 1 or len(probs_arr) == 0:
            raise ValueError("fit_threshold requires a non-empty 1-D array of probabilities")

        costs_arr = np.broadcast_to(np.asarray(costs, dtype=float), probs_arr.shape)
        net_r = r_arr - costs_arr

        cand = np.asarray(candidates, dtype=float) if candidates is not None else np.unique(probs_arr)
        cand = np.sort(cand)

        best_thr = 0.0
        best_exp = float("-inf")
        best_n = 0
        for thr in cand:
            mask = probs_arr >= thr
            n = int(mask.sum())
            if n < min_trades:
                continue
            exp = float(net_r[mask].mean())
            if exp > best_exp:
                best_thr, best_exp, best_n = float(thr), exp, n

        if best_exp == float("-inf"):
            # Nothing cleared min_trades: gate nothing rather than fail --
            # an honest "not enough signal to filter on" outcome.
            best_thr = 0.0
            best_exp = float(net_r.mean())
            best_n = len(net_r)

        self.threshold = best_thr
        self.fit_info = {
            "expectancy_r": best_exp,
            "n_trades_retained": best_n,
            "n_candidates": int(len(cand)),
            "n_total": int(len(probs_arr)),
        }
        return self

    def transform(self, probs: npt.ArrayLike) -> np.ndarray:
        """Boolean mask: which signals pass the gate."""
        if self.threshold is None:
            raise RuntimeError("ProbabilityGate has no threshold; call fit_threshold() first")
        return np.asarray(probs, dtype=float) >= self.threshold

    def __call__(self, probs: npt.ArrayLike) -> np.ndarray:
        return self.transform(probs)
