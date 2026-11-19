"""Parameter and cost sensitivity: does the edge survive being slightly wrong?

A backtest is run at one exact set of parameters. A real edge tends to be
insensitive to that exact choice -- move a lookback window 10%, and the
result gets a bit worse, not a lot worse. An overfit rule, by contrast, was
tuned to the one setting that happened to work on the historical sample, and
degrades sharply (or outright collapses) as soon as you step away from it.
:func:`parameter_sweep` builds the perturbation grid that lets you see the
difference; :func:`fragility_score` turns that grid into a single number that
specifically measures *how* it degrades, not just *whether* it does.

Nothing here imports :mod:`lab.backtest` or :mod:`lab.strategies` -- every
function takes ``run_fn``, an injected callable of ``params -> result``,
where ``result`` is whatever the caller's backtest returns (a
:class:`~lab.core.types.BacktestResult`, a plain stats mapping, ...). A
``metric_fn`` extracts the one number being tracked; it defaults to reading
``result["expectancy_r"]`` or ``result.stats["expectancy_r"]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np
import pandas as pd

__all__ = ["parameter_sweep", "stress_costs", "FragilityScore", "fragility_score"]

RunFn = Callable[[Mapping[str, Any]], Any]
MetricFn = Callable[[Any], float]


def _default_metric(result: Any) -> float:
    if isinstance(result, Mapping):
        if "expectancy_r" in result:
            return float(result["expectancy_r"])
        raise KeyError(
            "run_fn returned a mapping with no 'expectancy_r' key; pass metric_fn explicitly"
        )
    stats = getattr(result, "stats", None)
    if isinstance(stats, Mapping) and "expectancy_r" in stats:
        return float(stats["expectancy_r"])
    raise TypeError(
        f"cannot infer a metric from a {type(result)!r} result; pass "
        "metric_fn=lambda result: ... explicitly"
    )


def _safe_pct_change(new: float, base: float) -> float:
    if base == 0 or not np.isfinite(base):
        return float("nan")
    return (new - base) / abs(base)


def _numeric_candidates(base_value: float, pct_steps: Sequence[float], is_int: bool) -> Iterator[tuple[float, Any]]:
    seen: set[Any] = set()
    for pct in pct_steps:
        for sign in (-1, 1):
            if is_int:
                step = max(1, round(abs(base_value) * pct))
                value: Any = int(base_value + sign * step)
            else:
                value = base_value * (1 + sign * pct)
            marker = value if is_int else round(value, 12)
            if marker in seen:
                continue
            seen.add(marker)
            yield (round(sign * pct, 6), value)


def _candidates(
    key: str, base_value: Any, pct_steps: Sequence[float], explicit: Sequence[Any] | None
) -> Iterator[tuple[float, Any]]:
    if explicit is not None:
        for value in explicit:
            if value == base_value:
                continue
            yield (float("nan"), value)
        return
    if isinstance(base_value, bool):
        yield (float("nan"), not base_value)
        return
    if isinstance(base_value, (int, float)):
        yield from _numeric_candidates(float(base_value), pct_steps, is_int=isinstance(base_value, int))
        return
    raise TypeError(
        f"don't know how to perturb {key!r} of type {type(base_value).__name__}; pass explicit "
        f"candidate values via perturbations={{{key!r}: [...]}}"
    )


def parameter_sweep(
    run_fn: RunFn,
    base_params: Mapping[str, Any],
    perturbations: Mapping[str, Sequence[Any] | None] | Sequence[str] | None = None,
    *,
    pct_steps: Sequence[float] = (0.10, 0.20),
    metric_fn: MetricFn | None = None,
) -> pd.DataFrame:
    """Vary each of ``perturbations`` around ``base_params`` and tabulate the metric.

    ``perturbations`` selects which keys of ``base_params`` to sweep and how:

    * ``None`` (default): sweep every key in ``base_params`` using the
      automatic rule below.
    * a sequence of names: sweep exactly those keys, automatic rule.
    * a mapping ``{name: [explicit, values, ...]}``: sweep exactly those
      keys, trying exactly the listed values for each (required for
      categoricals, which have no notion of "+10%"). A ``None`` value for a
      key falls back to the automatic rule for that key.

    Automatic rule, by the base value's type:

    * ``bool`` -- flip it (one candidate).
    * ``int`` -- step by ``max(1, round(|base| * pct))`` for each ``pct`` in
      ``pct_steps``, both directions (integers "step sensibly" rather than
      landing on a fraction).
    * ``float`` -- ``base * (1 +/- pct)`` for each ``pct`` in ``pct_steps``,
      both directions.
    * anything else -- raises ``TypeError``; supply explicit candidates.

    The returned frame always includes one ``param="<base>"`` row (the
    unperturbed run, ``pct_step=0.0``) plus one row per perturbation, with
    columns ``param, value, base_value, pct_step, metric, base_metric, delta,
    pct_change``. ``pct_step`` is ``NaN`` for boolean/categorical/explicit
    candidates, which have no perturbation magnitude. See
    :func:`fragility_score` for what to do with the result.
    """
    metric_fn = metric_fn or _default_metric

    if perturbations is None:
        keys: list[str] = list(base_params)
        explicit_map: dict[str, Sequence[Any] | None] = {}
    elif isinstance(perturbations, Mapping):
        keys = list(perturbations)
        explicit_map = dict(perturbations)
    else:
        keys = list(perturbations)
        explicit_map = {}

    base_metric = metric_fn(run_fn(dict(base_params)))
    rows: list[dict[str, Any]] = [
        {
            "param": "<base>", "value": None, "base_value": None, "pct_step": 0.0,
            "metric": base_metric, "base_metric": base_metric, "delta": 0.0, "pct_change": 0.0,
        }
    ]

    for key in keys:
        if key not in base_params:
            raise KeyError(f"perturbation key {key!r} is not in base_params")
        base_value = base_params[key]
        explicit = explicit_map.get(key)
        for step, value in _candidates(key, base_value, pct_steps, explicit):
            params = dict(base_params)
            params[key] = value
            metric = metric_fn(run_fn(params))
            rows.append(
                {
                    "param": key, "value": value, "base_value": base_value, "pct_step": step,
                    "metric": metric, "base_metric": base_metric,
                    "delta": metric - base_metric, "pct_change": _safe_pct_change(metric, base_metric),
                }
            )
    return pd.DataFrame(rows)


def stress_costs(
    run_fn: RunFn,
    base_params: Mapping[str, Any] | None = None,
    extra_slip_ticks: Sequence[float] = (1, 2),
    commission_mult: Sequence[float] = (1.0, 1.25),
    *,
    metric_fn: MetricFn | None = None,
) -> pd.DataFrame:
    """Cartesian cost-stress grid: extra adverse slippage (ticks) x commission multiplier.

    ``run_fn`` is called once per combination with
    ``{**base_params, "extra_slip_ticks": t, "commission_mult": m}``. How
    those two keys actually load onto an ``Instrument`` or cost model is
    entirely up to the caller's ``run_fn`` -- this function only drives the
    grid and records the resulting metric, columns ``extra_slip_ticks,
    commission_mult, metric``.
    """
    metric_fn = metric_fn or _default_metric
    base = dict(base_params or {})
    rows: list[dict[str, Any]] = []
    for t in extra_slip_ticks:
        for m in commission_mult:
            params = dict(base)
            params["extra_slip_ticks"] = t
            params["commission_mult"] = m
            metric = metric_fn(run_fn(params))
            rows.append({"extra_slip_ticks": t, "commission_mult": m, "metric": metric})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# fragility score
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FragilityScore:
    """How gracefully a :func:`parameter_sweep` surface degrades away from its base point.

    ``score`` is the headline number (see :func:`fragility_score` for the
    exact formula and how to read it); ``worst_relative_drop`` and
    ``cliffness`` are its two components, aggregated (by taking the max)
    across every swept parameter; ``by_param`` breaks all three down per
    parameter, sorted worst-first.
    """

    score: float
    worst_relative_drop: float
    cliffness: float
    by_param: pd.DataFrame


def fragility_score(
    surface: pd.DataFrame,
    metric: str = "metric",
    *,
    param_col: str = "param",
    step_col: str = "pct_step",
    base_col: str = "base_metric",
) -> FragilityScore:
    """Score the *shape* of ``surface`` (a :func:`parameter_sweep` output), not just its values.

    For each swept parameter, build the degradation profile
    ``d(step) = (base_metric - metric(step)) / |base_metric|`` over whatever
    perturbation points that parameter has (``d(0) = 0`` at the base point,
    by definition). Positive ``d`` means the metric got worse there; negative
    means it improved.

    Two components, per parameter:

    * ``worst_relative_drop = max(0, max(d))`` across that parameter's
      points -- the single worst normalised degradation observed. This alone
      cannot tell a parameter that is "a little worse everywhere" from one
      that is fine right up until it suddenly is not, which is exactly the
      distinction that matters here (a real edge does the former; an
      overfit one often does the latter).
    * ``cliffness`` -- only computed for parameters with the full symmetric
      grid at +/-10% and +/-20% -- is the largest absolute discrete second
      derivative of ``d`` across that five-point grid,
      ``|d[i-1] - 2*d[i] + d[i+1]|`` evaluated at each interior point
      (-10%, 0, +10%). A profile that degrades roughly linearly as the
      perturbation grows keeps this small; a profile with a sudden bend --
      flat, then a cliff, or a cliff on one side only -- produces a large
      value here even when its ``worst_relative_drop`` looks unremarkable.
      Boolean/categorical/explicit-candidate perturbations have no
      perturbation magnitude and so contribute ``cliffness=0``.

    A parameter's own score is ``0.5 * worst_relative_drop + 0.5 * cliffness``.
    The surface's aggregate ``score``, ``worst_relative_drop`` and
    ``cliffness`` are each the **max** over parameters, not the mean: a
    strategy is only as robust as its single most fragile input, and
    averaging would let one badly fragile parameter hide behind several
    boring ones.

    How to read the aggregate ``score``
    ------------------------------------
    * ``0`` -- flat or improving under every perturbation tried.
    * roughly ``0`` to ``0.3`` -- normal, gradual sensitivity; expected of a
      real edge nudged off its exact backtested parameters.
    * above ``0.5`` -- either a large worst-case drop, a sharp cliff, or
      both. Treat the underlying rule as likely fit to its exact base
      parameters rather than to something the market actually does, and
      corroborate with :func:`~lab.robustness.dropn.drop_best` and
      :func:`stress_costs` before trusting it out of sample.
    """
    work = surface[surface[param_col] != "<base>"]
    if len(work) == 0:
        empty = pd.DataFrame(columns=["param", "worst_relative_drop", "cliffness", "score"])
        return FragilityScore(0.0, 0.0, 0.0, empty)

    required_steps = (-0.2, -0.1, 0.0, 0.1, 0.2)
    rows: list[dict[str, Any]] = []
    for name, g in work.groupby(param_col, sort=True):
        base_metric = float(g[base_col].iloc[0])
        denom = abs(base_metric) if base_metric != 0 else 1.0

        grid: dict[float, float] = {0.0: 0.0}
        no_magnitude_worst = 0.0
        for _, r in g.iterrows():
            step = r[step_col]
            d = (base_metric - r[metric]) / denom
            if pd.isna(step):
                no_magnitude_worst = max(no_magnitude_worst, d)
            else:
                grid[round(float(step), 6)] = d

        worst = max([0.0, no_magnitude_worst] + [v for k, v in grid.items() if k != 0.0])

        cliff = 0.0
        if all(s in grid for s in required_steps):
            ordered = [grid[s] for s in required_steps]
            second_diffs = [abs(ordered[i - 1] - 2 * ordered[i] + ordered[i + 1]) for i in (1, 2, 3)]
            cliff = max(second_diffs)

        rows.append(
            {"param": name, "worst_relative_drop": worst, "cliffness": cliff, "score": 0.5 * worst + 0.5 * cliff}
        )

    by_param = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    return FragilityScore(
        score=float(by_param["score"].max()),
        worst_relative_drop=float(by_param["worst_relative_drop"].max()),
        cliffness=float(by_param["cliffness"].max()),
        by_param=by_param,
    )
