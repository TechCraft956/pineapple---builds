"""Turn measured fills back into research cost assumptions.

``lab/core/instruments.py`` ships conservative, made-up commission/slippage
defaults on purpose -- see its module docstring. This module closes the loop:
once the journal has enough *matched* trades (a signal reconciled against the
execution that filled it, see :mod:`lab.journal.adherence`), it measures what
commission and slippage actually cost and emits a ``cost_overrides:`` block
ready to paste into ``config/config.yaml``.

The one rule this module enforces harder than anything else: refuse to emit
from too few samples. An estimate built on 6 fills is *worse* than the
conservative default it would replace, because it replaces an honest "we
don't know, so assume the worst" with a false "we measured this" that could
easily be a lucky (or unlucky) run of thin, quiet-market fills.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from lab.core.instruments import get_instrument
from lab.journal.adherence import MatchedPair

__all__ = ["CostEstimate", "measure_costs", "build_cost_overrides_yaml"]

DEFAULT_MIN_SAMPLES = 50


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Realised commission and slippage stats for one symbol.

    Slippage is reported in ticks, both signed (median, to see systematic
    bias -- consistently worse fills on one side means the base assumption is
    too tight, not just noisy) and as an unsigned magnitude at the 80th
    percentile (what a conservative override should actually use).
    """

    symbol: str
    n: int
    commission_median: float
    commission_p80: float
    slippage_ticks_median_signed: float
    slippage_ticks_p80_abs: float
    by_order_type: dict[str, dict[str, float]]
    by_hour: dict[int, dict[str, float]]


def _stats(commissions: Sequence[float], slip_ticks: Sequence[float]) -> dict[str, float]:
    c = np.asarray(commissions, dtype=float)
    s = np.asarray(slip_ticks, dtype=float)
    return {
        "n": int(len(c)),
        "commission_median": float(np.median(c)) if len(c) else float("nan"),
        "commission_p80": float(np.percentile(c, 80)) if len(c) else float("nan"),
        "slippage_ticks_median_signed": float(np.median(s)) if len(s) else float("nan"),
        "slippage_ticks_p80_abs": float(np.percentile(np.abs(s), 80)) if len(s) else float("nan"),
    }


def measure_costs(matched: Sequence[MatchedPair]) -> dict[str, CostEstimate]:
    """Per-symbol commission/slippage stats from matched (signal, execution) pairs.

    Every symbol present is measured regardless of sample size -- seeing *how
    few* fills you have is itself useful information, even when it is not
    enough to trust for a config override. The minimum-sample gate lives in
    :func:`build_cost_overrides_yaml`.

    Commission is read from the matched trade (per-contract, i.e.
    ``trade.commission / trade.qty``), slippage from the reconciled
    theoretical-vs-actual entry (see :mod:`lab.journal.adherence`). Both are
    additionally split by order type (``Signal.entry_type``) and by hour of
    day in the instrument's own session timezone, so a systematic difference
    between market and stop fills, or between the open and mid-session, is
    visible rather than averaged away.
    """
    by_symbol: dict[str, list[MatchedPair]] = defaultdict(list)
    for mp in matched:
        by_symbol[mp.signal.symbol].append(mp)

    out: dict[str, CostEstimate] = {}
    for symbol, pairs in by_symbol.items():
        inst = get_instrument(symbol)
        commissions = [mp.trade.commission / mp.trade.qty if mp.trade.qty else 0.0 for mp in pairs]
        slips = [mp.slippage_ticks for mp in pairs]
        overall = _stats(commissions, slips)

        by_order_type: dict[str, dict[str, float]] = {}
        order_types = sorted({mp.signal.entry_type for mp in pairs})
        for ot in order_types:
            sub = [mp for mp in pairs if mp.signal.entry_type == ot]
            by_order_type[ot] = _stats(
                [mp.trade.commission / mp.trade.qty if mp.trade.qty else 0.0 for mp in sub],
                [mp.slippage_ticks for mp in sub],
            )

        by_hour: dict[int, dict[str, float]] = {}
        hours = sorted({mp.trade.entry_ts.tz_convert(inst.session_tz).hour for mp in pairs})
        for h in hours:
            sub = [mp for mp in pairs if mp.trade.entry_ts.tz_convert(inst.session_tz).hour == h]
            by_hour[h] = _stats(
                [mp.trade.commission / mp.trade.qty if mp.trade.qty else 0.0 for mp in sub],
                [mp.slippage_ticks for mp in sub],
            )

        out[symbol] = CostEstimate(
            symbol=symbol,
            n=overall["n"],
            commission_median=overall["commission_median"],
            commission_p80=overall["commission_p80"],
            slippage_ticks_median_signed=overall["slippage_ticks_median_signed"],
            slippage_ticks_p80_abs=overall["slippage_ticks_p80_abs"],
            by_order_type=by_order_type,
            by_hour=by_hour,
        )
    return out


def build_cost_overrides_yaml(
    estimates: Mapping[str, CostEstimate], min_samples: int = DEFAULT_MIN_SAMPLES
) -> str:
    """A ready-to-paste ``cost_overrides:`` block for ``config/config.yaml``.

    Raises :class:`ValueError` -- refuses to emit anything -- if no symbol has
    at least ``min_samples`` matched trades. Symbols that individually fall
    short are left out of the emitted block (and listed in a trailing
    comment) rather than blocking symbols that do have enough data.

    Uses the median for commission (a fixed cost with no meaningful tail) and
    the 80th-percentile *magnitude* for slippage (the number
    ``Instrument.default_slippage_ticks`` is meant to hold: a conservative
    per-side assumption, not the average case).
    """
    usable = {s: e for s, e in estimates.items() if e.n >= min_samples}
    refused = {s: e.n for s, e in estimates.items() if e.n < min_samples}
    if not usable:
        have = ", ".join(f"{s}={e.n}" for s, e in sorted(estimates.items())) or "no symbols at all"
        raise ValueError(
            f"no symbol has {min_samples}+ matched trades to measure costs from "
            f"(have: {have}); keep trading and journaling before overriding the "
            "conservative defaults in lab/core/instruments.py."
        )

    lines = [
        "# Generated by lab.journal.costs_measure.build_cost_overrides_yaml from "
        f"{sum(e.n for e in usable.values())} matched, journaled fills.",
        "# Paste into config/config.yaml, replacing (or merging with) the existing block.",
        "cost_overrides:",
    ]
    for sym, est in sorted(usable.items()):
        lines.append(f"  {sym}:")
        lines.append(f"    commission_round_turn: {round(est.commission_median, 2)}")
        lines.append(f"    default_slippage_ticks: {round(est.slippage_ticks_p80_abs, 2)}")
    if refused:
        lines.append(
            "# not enough samples yet, kept on the conservative defaults: "
            + ", ".join(f"{s}={n}" for s, n in sorted(refused.items()))
        )
    return "\n".join(lines) + "\n"
