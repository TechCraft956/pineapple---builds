#!/usr/bin/env python3
"""
Political Tracker  -  04_INTELLIGENCE
Parse city council / county meeting agenda items. Surface items that move money
or land near you: rezoning, road projects, grants, tax changes, permits, eminent domain.

Run:  python political_tracker.py
Input: input/agenda_items.json (sample created on first run)

OFFLINE by design: feed it agenda text (scraped/pasted) and it scores.
Wire a scraper later to populate input/agenda_items.json automatically.
"""
from __future__ import annotations
import sys
from pathlib import Path


def _boot():
    p = Path(__file__).resolve()
    for a in [p, *p.parents]:
        if (a / ".pineapple_root").exists():
            sys.path.insert(0, str(a / "_lib"))
            return
        # BUILD HARDENING (2026-11-17, build copy only): a workspace-relative
        # _lib holding pineapple_intel.py also satisfies the import, so the
        # module runs in an isolated workspace with no .pineapple_root marker
        # anywhere in the parent tree. Marker still wins when present.
        if (a / "_lib" / "pineapple_intel.py").exists():
            sys.path.insert(0, str(a / "_lib"))
            return
_boot()
import pineapple_intel as pi  # noqa: E402


# keyword -> (points, why-it-matters, recommended angle)
KEYWORDS = {
    "rezoning":        (30, "land use change -> property value swings", "Map affected parcels; check upzoning equity"),
    "rezone":          (30, "land use change -> property value swings", "Map affected parcels"),
    "road project":    (25, "access changes drive nearby value", "Identify parcels gaining/losing access"),
    "road widening":   (25, "access + frontage changes", "Check frontage takings / value lift"),
    "grant":           (22, "free capital / matching funds", "Check eligibility for your projects"),
    "tax abatement":   (20, "subsidized development zones", "Target abatement-eligible parcels"),
    "tax increase":    (18, "cost change for owners", "Model carrying-cost impact"),
    "eminent domain":  (28, "forced sales / payouts incoming", "Find affected owners (motivated sellers)"),
    "tif":             (24, "tax-increment financing district", "TIF = public money flowing to an area"),
    "permit":          (12, "construction/business activity", "Track who is building / expanding"),
    "variance":        (14, "exception to zoning -> development", "Signals intent to develop"),
    "annexation":      (20, "boundary change -> new services/value", "Watch newly-serviced land"),
    "moratorium":      (16, "freeze -> scarcity downstream", "Anticipate post-freeze demand"),
    "auction":         (22, "public asset / surplus sale", "Surplus property/equipment cheap"),
    "surplus":         (18, "government selling assets", "Surplus equipment/vehicle flips"),
}

SAMPLE = [
    {"body": "City Council", "date": "2026-06-30",
     "text": "Public hearing on REZONING of parcels along Highway 9 from agricultural to commercial."},
    {"body": "County Commission", "date": "2026-07-02",
     "text": "Approval of ROAD WIDENING project on Maple Dr; discussion of frontage acquisition."},
    {"body": "City Council", "date": "2026-07-07",
     "text": "Resolution accepting state GRANT for downtown facade improvements; TIF district extension."},
    {"body": "Town Board", "date": "2026-07-09",
     "text": "Routine approval of minutes and a parks SURPLUS equipment AUCTION next month."},
    {"body": "Planning Dept", "date": "2026-07-10",
     "text": "Note on park bench replacement schedule."},
]


class PoliticalTracker(pi.IntelModule):
    module_id = "political_tracker"
    module_name = "Political Tracker"
    layer = "04_INTELLIGENCE"
    one_rule = {"makes_money": True, "increases_freedom": True}

    def scan(self):
        items = self.load_input("agenda_items.json")
        if items is None:
            self.input_dir.mkdir(parents=True, exist_ok=True)
            (self.input_dir / "agenda_items.json").write_text(
                pi.json.dumps(SAMPLE, indent=2), encoding="utf-8")
            items = SAMPLE

        opps = []
        for it in items:
            text = (it.get("text") or "").lower()
            signals, score, angles = [], 0.0, []
            for kw, (pts, why, angle) in KEYWORDS.items():
                if kw in text:
                    signals.append(pi.Signal(kw, True, pts, why))
                    score += pts
                    angles.append(angle)
            if not signals:
                continue
            score = min(round(score, 1), 100)
            body = it.get("body", "meeting")
            date = it.get("date", "")
            uniq = list(dict.fromkeys(angles))[:2]
            action = "%s (%s): %s" % (body, date, "; ".join(uniq))
            opps.append(pi.Opportunity(
                title="%s - %s" % (body, ", ".join(s.name for s in signals)),
                score=score, action=action, signals=signals,
                risk="LOW", fields={"date": date, "body": body, "excerpt": it.get("text", "")[:160]},
            ))
        return opps


if __name__ == "__main__":
    PoliticalTracker().run()
