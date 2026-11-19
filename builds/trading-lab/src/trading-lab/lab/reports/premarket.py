"""The pre-session brief: what today looks like, and what is allowed on it.

Built entirely from bars and a calendar feed -- no dependency on the
backtest, strategy or risk modules being importable, per the lab's parallel
build constraint. Where a judgement call genuinely belongs to another module
(the daily loss lock, the max-attempts count, which strategy the risk layer
has actually greenlit), this report *accepts* that as ``prior_results`` and
uses it verbatim; it only falls back to a conservative, clearly-labelled
built-in default when nothing is supplied, exactly the way
``lab.core.instruments`` falls back to conservative cost defaults until
you've measured your own.

Every session window used here comes from :mod:`lab.core.sessions` -- never
hand-rolled -- so this report and the backtest agree on what "the Asia
session" or "overnight" means down to the DST transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from lab.core.instruments import get_instrument
from lab.core.sessions import (
    ASIA,
    NY_RTH,
    OVERNIGHT,
    prior_day_levels,
    session_levels,
    trading_day,
    window_bounds,
)
from lab.reports.render import markdown_table, section, verdict_box

__all__ = ["RegimeThresholds", "build_premarket_report"]

CHICAGO_TZ = "America/Chicago"

#: Conservative fallbacks, used only when `prior_results` doesn't supply the
#: real numbers from lab.risk. Modelled loosely on typical prop-firm rules;
#: override with real account-simulation output whenever you have it.
_DEFAULT_DAILY_LOSS_LOCK_PCT = {"combine": 0.02, "funded": 0.015, "express_funded": 0.015}
_DEFAULT_MAX_ATTEMPTS = {"combine": 3, "funded": 2, "express_funded": 2}

#: Which single strategy tag a regime permits, and the one-line reason -- used
#: only as a fallback when `prior_results["permitted_strategy"]` is absent.
_REGIME_STRATEGY: dict[str, tuple[str, str]] = {
    "trend": ("breakout_trend", "range expansion in both Asia and ATR favours following a break"),
    "range": ("mean_reversion_fade", "contained, non-expanding range favours fading extremes back to value"),
    "compressed": ("no_trade", "range and ATR both sit in the bottom quartile -- no edge to lean on yet"),
    "news_dominated": ("no_trade", "a high-impact release sits inside or just before today's session"),
}


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    """The numeric cutoffs the regime classifier uses, stated once, used everywhere.

    Percentiles are computed against the trailing ``lookback_days`` trading
    days for the same symbol -- there is no universal "compressed" ATR, only
    "compressed relative to this instrument's own recent history".
    """

    lookback_days: int = 20
    compressed_pctile: float = 25.0
    expansion_pctile: float = 60.0


def _trailing_percentile(values: Sequence[float], current: float) -> float:
    """Percentile rank of ``current`` within ``values`` (0-100), NaN if too few points."""
    arr = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if len(arr) < 3 or not np.isfinite(current):
        return float("nan")
    return float((arr <= current).mean() * 100.0)


def _daily_atr_series(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-style ATR on daily bars derived by resampling, indexed by trading day."""
    from lab.core.frames import resample_bars  # local: keep this module's import surface narrow

    daily = resample_bars(bars, "1d")
    if len(daily) < 2:
        return pd.Series(dtype=float)
    prior_close = daily["close"].shift(1)
    tr = pd.concat(
        [
            daily["high"] - daily["low"],
            (daily["high"] - prior_close).abs(),
            (daily["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def _vwap_distance(bars: pd.DataFrame, window_start: pd.Timestamp, window_end: pd.Timestamp) -> dict[str, float]:
    win = bars.loc[(bars.index >= window_start) & (bars.index < window_end)]
    if win.empty:
        return {"vwap": float("nan"), "last": float("nan"), "distance": float("nan")}
    typical = (win["high"] + win["low"] + win["close"]) / 3.0
    vol = win["volume"].fillna(0.0)
    vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() > 0 else float(typical.mean())
    last = float(win["close"].iloc[-1])
    return {"vwap": vwap, "last": last, "distance": last - vwap}


def _high_impact_events_today(
    calendar_events: Sequence[Mapping[str, Any]], session_start: pd.Timestamp, session_end: pd.Timestamp
) -> list[Mapping[str, Any]]:
    hits = []
    for ev in calendar_events:
        ts = pd.Timestamp(ev["time"])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        if session_start <= ts <= session_end and str(ev.get("impact", "")).lower() == "high":
            hits.append(ev)
    return hits


def _classify_regime(
    asia_range_pctile: float,
    atr_pctile: float,
    n_high_impact_today: int,
    thresholds: RegimeThresholds,
) -> str:
    if n_high_impact_today > 0:
        return "news_dominated"
    if np.isfinite(asia_range_pctile) and np.isfinite(atr_pctile):
        if asia_range_pctile < thresholds.compressed_pctile and atr_pctile < thresholds.compressed_pctile:
            return "compressed"
        if asia_range_pctile >= thresholds.expansion_pctile and atr_pctile >= thresholds.expansion_pctile:
            return "trend"
    return "range"


def _symbol_section(
    symbol: str,
    bars: pd.DataFrame,
    day: date,
    calendar_events: Sequence[Mapping[str, Any]],
    thresholds: RegimeThresholds,
) -> tuple[str, dict[str, Any]]:
    inst = get_instrument(symbol)

    prior = prior_day_levels(bars, day)
    asia = session_levels(bars, ASIA, day)
    overnight = session_levels(bars, OVERNIGHT, day)

    # Trailing Asia-range percentile: same window on each of the prior N trading days.
    trailing_ranges = []
    days = pd.unique(trading_day(bars.index))
    prior_days = sorted(d for d in days if d < day)[-thresholds.lookback_days:]
    for d in prior_days:
        lv = session_levels(bars, ASIA, d)
        if lv:
            trailing_ranges.append(lv["range"])
    asia_range_pctile = _trailing_percentile(trailing_ranges, asia["range"] if asia else float("nan"))

    atr_series = _daily_atr_series(bars)
    atr_today = float(atr_series.iloc[-1]) if len(atr_series) and pd.notna(atr_series.iloc[-1]) else float("nan")
    atr_pctile = _trailing_percentile(atr_series.iloc[:-1].tail(thresholds.lookback_days).tolist(), atr_today) if len(atr_series) > 1 else float("nan")

    rth_start, rth_end = window_bounds(NY_RTH, day)
    high_impact_today = _high_impact_events_today(calendar_events, rth_start - pd.Timedelta(hours=2), rth_end)

    regime = _classify_regime(asia_range_pctile, atr_pctile, len(high_impact_today), thresholds)
    strategy, why = _REGIME_STRATEGY[regime]

    on_start, on_end = window_bounds(OVERNIGHT, day)
    vwap_info = _vwap_distance(bars, on_start, on_end)
    vwap_ticks = inst.ticks(vwap_info["distance"]) if np.isfinite(vwap_info["distance"]) else float("nan")

    rows = pd.DataFrame(
        [
            {"metric": "prior day high/low/close", "value": (
                f"{prior['high']:.2f} / {prior['low']:.2f} / {prior['close']:.2f}" if prior else "n/a"
            )},
            {"metric": "Asia range (pctile)", "value": (
                f"{asia['high']:.2f}-{asia['low']:.2f} = {asia['range']:.2f} "
                f"({asia_range_pctile:.0f}th pct, n={len(trailing_ranges)})" if asia else "no Asia bars"
            )},
            {"metric": "Overnight range / realised vol", "value": (
                f"{overnight['range']:.2f} pts / {float(bars.loc[(bars.index>=on_start)&(bars.index<on_end), 'close'].pct_change().std() or 0):.4f}"
                if overnight else "no overnight bars"
            )},
            {"metric": f"ATR({14}) (pctile)", "value": (
                f"{atr_today:.2f} ({atr_pctile:.0f}th pct)" if np.isfinite(atr_today) else "insufficient daily history"
            )},
            {"metric": "distance from overnight VWAP", "value": (
                f"{vwap_info['distance']:+.2f} pts ({vwap_ticks:+.1f} ticks)" if np.isfinite(vwap_ticks) else "n/a"
            )},
            {"metric": "high-impact releases today", "value": str(len(high_impact_today))},
        ]
    )

    body = markdown_table(rows)
    body += (
        f"\n\n**Regime: {regime}** "
        f"(thresholds: compressed < {thresholds.compressed_pctile:.0f}th pct, "
        f"expansion >= {thresholds.expansion_pctile:.0f}th pct on both Asia range and "
        f"ATR({14}) over the trailing {thresholds.lookback_days} days; news_dominated overrides "
        "both whenever a high-impact release sits in or just before the session)\n\n"
        f"**Permitted strategy: `{strategy}`** -- {why}"
    )
    return section(f"{symbol}", body, level=3), {
        "regime": regime, "strategy": strategy, "reason": why,
        "asia_range_pctile": asia_range_pctile, "atr_pctile": atr_pctile,
    }


def build_premarket_report(
    day: "date | str | pd.Timestamp",
    bars_by_symbol: Mapping[str, pd.DataFrame],
    calendar_events: Sequence[Mapping[str, Any]] | None = None,
    prior_results: Mapping[str, Any] | None = None,
    cfg: Any = None,
    thresholds: RegimeThresholds = RegimeThresholds(),
) -> str:
    """Build the pre-session brief as markdown.

    Parameters
    ----------
    day:
        The CME trading day this brief is for.
    bars_by_symbol:
        ``{symbol: bar_frame}`` covering at least ``thresholds.lookback_days``
        trading days before ``day``, per :mod:`lab.core.frames`. The first
        key is treated as the primary/traded symbol unless
        ``prior_results["primary_symbol"]`` says otherwise.
    calendar_events:
        Sequence of ``{"time": <tz-aware timestamp>, "name": str, "impact":
        "high"|"medium"|"low"}``. Optional -- an empty calendar just means no
        release-driven regime override fires.
    prior_results:
        Optional precomputed risk/account figures from ``lab.risk`` --
        ``daily_loss_lock_dollars``, ``max_attempts``, ``permitted_strategy``,
        ``permitted_reason``, ``primary_symbol``. Anything not supplied falls
        back to a conservative built-in default, clearly labelled as such.
    cfg:
        A :class:`~lab.core.config.LabConfig`-like object (``account_size``,
        ``account_type``); only used to compute the fallback loss lock/max
        attempts when ``prior_results`` doesn't supply them.
    """
    d = pd.Timestamp(day).date() if not isinstance(day, date) else day
    calendar_events = calendar_events or []
    prior_results = prior_results or {}

    symbols = list(bars_by_symbol)
    primary = prior_results.get("primary_symbol", symbols[0] if symbols else None)

    parts: list[str] = [f"# Pre-market brief -- {d.isoformat()}\n"]

    # ---- scheduled releases ------------------------------------------
    if calendar_events:
        ev_rows = pd.DataFrame(
            [
                {
                    "time_ct": pd.Timestamp(ev["time"]).tz_convert(CHICAGO_TZ).strftime("%H:%M %Z")
                    if pd.Timestamp(ev["time"]).tzinfo
                    else pd.Timestamp(ev["time"]).tz_localize("UTC").tz_convert(CHICAGO_TZ).strftime("%H:%M %Z"),
                    "name": ev.get("name", ""),
                    "impact": ev.get("impact", ""),
                }
                for ev in sorted(calendar_events, key=lambda e: pd.Timestamp(e["time"]))
            ]
        )
        parts.append(section("Scheduled releases (America/Chicago)", markdown_table(ev_rows)))
    else:
        parts.append(section("Scheduled releases (America/Chicago)", "_none on file for today_"))

    # ---- per-symbol session/regime detail ------------------------------
    decisions: dict[str, dict[str, Any]] = {}
    symbol_bodies = []
    for sym in symbols:
        body, info = _symbol_section(sym, bars_by_symbol[sym], d, calendar_events, thresholds)
        symbol_bodies.append(body)
        decisions[sym] = info
    parts.append(section("Session levels, volatility and regime", "\n".join(symbol_bodies), level=2))

    # ---- the decision: what's permitted today --------------------------
    if "permitted_strategy" in prior_results:
        permitted_strategy = prior_results["permitted_strategy"]
        permitted_reason = prior_results.get("permitted_reason", "set by lab.risk / prior_results")
    elif primary and primary in decisions:
        permitted_strategy = decisions[primary]["strategy"]
        permitted_reason = decisions[primary]["reason"]
    else:
        permitted_strategy, permitted_reason = "no_trade", "no primary symbol / bars supplied"

    account_type = getattr(cfg, "account_type", "funded") if cfg is not None else "funded"
    account_size = getattr(cfg, "account_size", 150_000) if cfg is not None else 150_000
    if "daily_loss_lock_dollars" in prior_results:
        loss_lock = prior_results["daily_loss_lock_dollars"]
        loss_lock_note = "from prior_results (lab.risk)"
    else:
        loss_lock = round(account_size * _DEFAULT_DAILY_LOSS_LOCK_PCT.get(account_type, 0.015), 2)
        loss_lock_note = (
            f"conservative fallback: {_DEFAULT_DAILY_LOSS_LOCK_PCT.get(account_type, 0.015):.1%} "
            f"of ${account_size:,} ({account_type}) -- override via prior_results"
        )
    if "max_attempts" in prior_results:
        max_attempts = prior_results["max_attempts"]
        attempts_note = "from prior_results (lab.risk)"
    else:
        max_attempts = _DEFAULT_MAX_ATTEMPTS.get(account_type, 2)
        attempts_note = "conservative fallback -- override via prior_results"

    decision_rows = pd.DataFrame(
        [
            {"item": "Permitted strategy today", "value": permitted_strategy, "why": permitted_reason},
            {"item": "Daily loss lock", "value": f"${loss_lock:,.2f}", "why": loss_lock_note},
            {"item": "Max attempts", "value": str(max_attempts), "why": attempts_note},
        ]
    )
    parts.append(section("Today's rules", markdown_table(decision_rows)))
    parts.append(
        verdict_box(
            "one strategy, one plan",
            passed=permitted_strategy != "no_trade",
            detail=(f"trade only `{permitted_strategy}`" if permitted_strategy != "no_trade" else "sit on hands today"),
        )
        + "\n"
    )

    # ---- checklist -------------------------------------------------
    checklist = [
        "Reviewed every scheduled release above and its time in CT",
        f"Confirmed today's permitted strategy is `{permitted_strategy}` and no other setup will be taken",
        f"Confirmed the daily loss lock (${loss_lock:,.2f}) and will stop *before* it, not at it",
        f"Confirmed the max-attempts limit ({max_attempts}) for today",
        "Sized the first entry per the plan before the session opens, not during it",
        "Journal open and ready to log every taken trade and every skipped setup",
    ]
    parts.append(section("Pre-session checklist", "\n".join(f"- [ ] {c}" for c in checklist)))

    return "\n".join(parts)
