"""Town Vitals hooks — interfaces only, NOT WIRED in v1.

The town-hall / town-site layer (meetings, agendas, minutes) is
heterogeneous municipal web content: that is future BROWSER-AGENT work,
deliberately not scraped in v1. The economy-signals layer is future
wiring to Pineapple's local_econ / economic_checker modules. Each hook
returns an explicit NOT WIRED marker so the renderer prints the gap
instead of silently omitting the layer.
"""
from __future__ import annotations

NOT_WIRED = "NOT WIRED"


def town_hall_items(place=None) -> dict:
    """Future: town-hall meetings / agendas / minutes for this place.

    Phase 2, BROWSER-AGENT over the town's own municipal site.
    """
    return {
        "hook": "town_hall_items",
        "status": NOT_WIRED,
        "items": [],
        "note": "Town-hall meetings/agendas hook is NOT WIRED in v1 — "
                "future browser-agent phase over municipal sites; no scraping in v1.",
    }


def economy_signals(place=None) -> dict:
    """Future: economy signals for this place from local_econ /
    economic_checker. Not connected in v1."""
    return {
        "hook": "economy_signals",
        "status": NOT_WIRED,
        "items": [],
        "note": "Economy-signals hook is NOT WIRED in v1 — future wiring to "
                "local_econ / economic_checker; no data borrowed in v1.",
    }


def all_hooks(place=None) -> list:
    return [town_hall_items(place), economy_signals(place)]
