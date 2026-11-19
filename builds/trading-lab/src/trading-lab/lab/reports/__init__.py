"""Hand-rolled report builders: pre-market briefs and post-session reviews.

See :mod:`lab.reports.render` for the shared markdown/HTML primitives,
:mod:`lab.reports.premarket` for the pre-session brief and
:mod:`lab.reports.session_review` for the post-session review.
"""

from __future__ import annotations

from lab.reports.premarket import RegimeThresholds, build_premarket_report
from lab.reports.render import markdown_table, section, to_html, verdict_box
from lab.reports.session_review import build_session_review

__all__ = [
    "RegimeThresholds",
    "build_premarket_report",
    "build_session_review",
    "markdown_table",
    "section",
    "to_html",
    "verdict_box",
]
