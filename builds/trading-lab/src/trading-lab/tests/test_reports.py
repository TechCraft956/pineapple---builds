"""Tests for lab.reports.render, lab.reports.premarket and lab.reports.session_review.

All inputs are synthetic and in-memory; no network, no other lab module needs
to be importable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab.core.types import LONG, SHORT, ExitReason, Signal, Trade
from lab.journal.journal import JOURNAL_COLUMNS
from lab.reports.premarket import RegimeThresholds, build_premarket_report
from lab.reports.render import markdown_table, section, to_html, verdict_box
from lab.reports.session_review import build_session_review

# ---------------------------------------------------------------------------
# render.py
# ---------------------------------------------------------------------------


def test_markdown_table_basic_alignment_and_formatting():
    df = pd.DataFrame({"symbol": ["ES", "NQ"], "pnl": [123.456, -7.0]})
    table = markdown_table(df, formats={"pnl": ",.2f"})
    lines = table.splitlines()
    assert lines[0].startswith("| symbol")
    assert all(len(line) == len(lines[0]) for line in lines)  # aligned columns
    assert "123.46" in table
    assert "-7.00" in table


def test_markdown_table_empty_frame_still_renders_header():
    df = pd.DataFrame(columns=["a", "b"])
    table = markdown_table(df)
    assert "| a" in table
    assert "(none)" in table


def test_section_and_verdict_box():
    text = section("Title", "body text", level=3)
    assert text.startswith("### Title")
    assert "body text" in text

    pass_line = verdict_box("adherence", True, "90%")
    fail_line = verdict_box("adherence", False, "40%")
    assert "PASS" in pass_line and "90%" in pass_line
    assert "FAIL" in fail_line and "40%" in fail_line


def test_to_html_is_self_contained_and_renders_tables_and_quotes():
    md = "\n".join([
        "# Report",
        "",
        section("A section", "some *text* body").strip(),
        "",
        markdown_table(pd.DataFrame({"x": [1, 2]})),
        "",
        verdict_box("check", True, "ok"),
        "",
        "- item one",
        "- item two",
    ])
    page = to_html(md, title="Test Report")
    assert page.startswith("<!doctype html>")
    assert "<title>Test Report</title>" in page
    assert "<table>" in page and "<th>x</th>" in page
    assert "<blockquote>" in page
    assert "<li>item one</li>" in page
    assert "prefers-color-scheme: dark" in page
    # no external assets
    assert "http://" not in page and "https://" not in page


# ---------------------------------------------------------------------------
# premarket.py
# ---------------------------------------------------------------------------


def _synthetic_bars(day: str, n_days: int = 35, freq: str = "30min", seed: int = 7) -> pd.DataFrame:
    end = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=16)
    start = end - pd.Timedelta(days=n_days)
    idx = pd.date_range(start, end, freq=freq, tz="UTC")
    rng = np.random.default_rng(seed)
    walk = 4500 + np.cumsum(rng.normal(0, 1.2, size=len(idx)))
    close = walk + rng.normal(0, 0.5, size=len(idx))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.random(len(idx)) * 1.0
    low = np.minimum(open_, close) - rng.random(len(idx)) * 1.0
    volume = rng.integers(50, 500, size=len(idx)).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    df.index.name = "ts"
    return df


def test_premarket_report_is_nonempty_and_covers_required_sections():
    day = "2026-08-03"
    bars = _synthetic_bars(day)
    report = build_premarket_report(day=day, bars_by_symbol={"ES": bars}, calendar_events=[])

    assert report.strip()
    assert "Pre-market brief" in report
    assert "Scheduled releases" in report
    assert "Session levels, volatility and regime" in report
    assert "Regime:" in report
    assert "Permitted strategy" in report
    assert "Daily loss lock" in report
    assert "Max attempts" in report
    assert "Pre-session checklist" in report
    assert "- [ ]" in report


def test_premarket_report_classifies_news_dominated_when_high_impact_event_present():
    day = "2026-08-03"
    bars = _synthetic_bars(day)
    rth_start_ct = pd.Timestamp(f"{day} 08:00", tz="America/Chicago").tz_convert("UTC")
    events = [{"time": rth_start_ct.isoformat(), "name": "CPI", "impact": "high"}]

    report = build_premarket_report(day=day, bars_by_symbol={"ES": bars}, calendar_events=events)
    assert "**Regime: news_dominated**" in report
    assert "`no_trade`" in report
    assert "CPI" in report


def test_premarket_report_uses_prior_results_when_supplied():
    day = "2026-08-03"
    bars = _synthetic_bars(day)
    prior_results = {
        "permitted_strategy": "asia_high_sweep",
        "permitted_reason": "risk engine greenlit it",
        "daily_loss_lock_dollars": 2500.0,
        "max_attempts": 2,
    }
    report = build_premarket_report(day=day, bars_by_symbol={"ES": bars}, prior_results=prior_results)
    assert "asia_high_sweep" in report
    assert "$2,500.00" in report
    assert "risk engine greenlit it" in report


# ---------------------------------------------------------------------------
# session_review.py
# ---------------------------------------------------------------------------


def _trade(entry_ts, entry_price, exit_price, direction=LONG, tag="asia_sweep") -> Trade:
    return Trade(
        symbol="ES", strategy="asia_sweep", direction=direction, entry_ts=entry_ts,
        entry_price=entry_price, exit_ts=entry_ts + pd.Timedelta(minutes=20), exit_price=exit_price,
        qty=1.0, pnl=direction * (exit_price - entry_price) * 50.0 - 4.0, commission=4.0,
        slippage_cost=0.0, risk_dollars=100.0, exit_reason=ExitReason.TARGET,
        mfe=60.0, mae=-20.0, tag=tag,
    )


def _signal(ts, entry, stop, direction=LONG, tag="asia_sweep") -> Signal:
    return Signal(ts=ts, direction=direction, entry=entry, stop=stop, symbol="ES",
                  strategy="asia_sweep", tag=tag)


def test_session_review_is_nonempty_and_covers_required_sections():
    day = "2026-08-03"
    t0 = pd.Timestamp("2026-08-03 13:30", tz="UTC")

    matched_signal = _signal(t0, entry=4500.00, stop=4495.00)
    skipped_signal = _signal(t0 + pd.Timedelta(hours=1), entry=4520.00, stop=4515.00, tag="failed_setup")
    matched_trade = _trade(t0 + pd.Timedelta(minutes=1), entry_price=4500.25, exit_price=4506.00)
    unplanned_trade = _trade(t0 + pd.Timedelta(hours=3), entry_price=4530.00, exit_price=4528.00)

    journal_rows = pd.DataFrame(
        [
            {**{c: pd.NA for c in JOURNAL_COLUMNS}, "trading_day": day, "status": "skipped",
             "symbol": "ES", "tag": "failed_setup", "notes": "waited for confirmation, never came"},
        ]
    )

    report = build_session_review(
        day=day, journal_rows=journal_rows,
        executed_trades=[matched_trade, unplanned_trade],
        expected_signals=[matched_signal, skipped_signal],
        account_state={"equity": 152_300.0, "drawdown_headroom": 4_700.0, "qualifying_days": 6},
    )

    assert report.strip()
    assert "Session review" in report
    assert "Planned vs. happened" in report
    assert "Every trade" in report
    assert "PASS" in report or "FAIL" in report
    assert "Skipped setups" in report
    assert "Running account state" in report
    assert "152,300" in report or "152300" in report
    assert "One thing to change" in report
    assert "only **one** rule may change per strategy version" in report
    assert "old results are never retroactively rewritten" in report


def test_session_review_without_account_state_says_so():
    day = "2026-08-03"
    report = build_session_review(
        day=day, journal_rows=pd.DataFrame(columns=list(JOURNAL_COLUMNS)),
        executed_trades=[], expected_signals=[], account_state=None,
    )
    assert "not supplied" in report
    assert "no signals or trades to score" in report
