"""Point-in-time features, labels, leakage-audited datasets, walk-forward
evaluation and the probability-gate models -- the ML layer of the lab.

The model here never predicts direction. It answers, after a strategy has
already qualified a setup: what is the probability price reaches +1R before
-1R within the labelled horizon? That probability is used only to filter
signals an existing edge already generates -- see :mod:`lab.ml.models` and
:mod:`lab.ml.evaluate` for the escalation ladder and the acceptance rule that
keeps this from becoming a second, hidden source of "edge".
"""

from __future__ import annotations

from lab.ml.datasets import Dataset, LeakageError, build_dataset
from lab.ml.evaluate import (
    FoldResult,
    ModelVerdict,
    OOSStats,
    Verdict,
    WalkForwardResult,
    accept_model,
    walkforward_evaluate,
)
from lab.ml.features import FEATURE_REGISTRY, build_feature_frame
from lab.ml.labels import BarrierOutcome, label_from_trades, r_label, triple_barrier
from lab.ml.models import (
    ESCALATION_ORDER,
    MODEL_REGISTRY,
    EscalationError,
    ModelSpec,
    ProbabilityGate,
    get_model,
)
from lab.ml.walkforward import Fold, HoldoutSplit, WalkForwardSplitter, final_holdout

__all__ = [
    # features
    "FEATURE_REGISTRY",
    "build_feature_frame",
    # labels
    "BarrierOutcome",
    "triple_barrier",
    "label_from_trades",
    "r_label",
    # datasets
    "Dataset",
    "build_dataset",
    "LeakageError",
    # walkforward
    "Fold",
    "WalkForwardSplitter",
    "HoldoutSplit",
    "final_holdout",
    # models
    "ModelSpec",
    "MODEL_REGISTRY",
    "ESCALATION_ORDER",
    "EscalationError",
    "get_model",
    "ProbabilityGate",
    # evaluate
    "OOSStats",
    "FoldResult",
    "WalkForwardResult",
    "Verdict",
    "ModelVerdict",
    "walkforward_evaluate",
    "accept_model",
]
