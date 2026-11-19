"""
pineapple_intel - shared framework for all Pineapple OS intelligence/asset modules.

Pure stdlib. No external deps. Bucket-safe: modules find the PINEAPPLE_OS root by
walking up to the `.pineapple_root` marker, so a module works regardless of which
bucket folder it lives in.

Every module is a SIGNAL -> SCORE -> ACTION pipeline that emits ranked Opportunities,
gated by The One Rule.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def find_root(start: Path) -> Path:
    """Walk up from `start` to the directory containing `.pineapple_root`."""
    start = start.resolve()
    for parent in [start, *start.parents]:
        if (parent / ".pineapple_root").exists():
            return parent
    return start.parent


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ONE_RULE_DIMENSIONS = ("makes_money", "saves_money", "saves_time", "reduces_risk", "increases_freedom")


def passes_one_rule(flags: dict) -> bool:
    """A module/opportunity survives only if it scores YES on >=1 dimension."""
    return any(bool(flags.get(d)) for d in ONE_RULE_DIMENSIONS)


@dataclass
class Signal:
    name: str
    value: Any
    weight: float = 1.0
    note: str = ""


@dataclass
class Opportunity:
    title: str
    score: float
    action: str
    signals: list = field(default_factory=list)
    roi_estimate: float | None = None
    risk: str = "UNKNOWN"
    priority: str = "C"
    fields: dict = field(default_factory=dict)
    created: str = field(default_factory=utcnow)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [asdict(s) for s in self.signals]
        return d


def grade(score: float) -> str:
    return "A" if score >= 75 else "B" if score >= 50 else "C"


class IntelModule:
    """Base class for every Pineapple intelligence/asset module.
    Subclass and implement scan() -> list[Opportunity]."""
    module_id: str = "unnamed_module"
    module_name: str = "Unnamed Module"
    layer: str = "04_INTELLIGENCE"
    one_rule: dict = {"makes_money": True}

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            import inspect as _inspect
            base_dir = Path(_inspect.getfile(self.__class__)).parent
        self.base_dir = Path(base_dir).resolve()
        self.root = find_root(self.base_dir)
        self.output_dir = self.base_dir / "output"
        self.input_dir = self.base_dir / "input"

    def scan(self) -> list:
        raise NotImplementedError

    def load_input(self, filename: str, default: Any = None) -> Any:
        p = self.input_dir / filename
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return default

    def _shared_feed_dir(self) -> Path | None:
        for cand in (self.root / "01_CORE" / "shared-feed", self.root / "shared-feed"):
            if cand.exists():
                return cand
        return None

    def publish_feed(self, status: str, events: list) -> bool:
        sf = self._shared_feed_dir()
        if not sf:
            return False
        try:
            if str(sf) not in sys.path:
                sys.path.insert(0, str(sf))
            from feed import write_app_status  # type: ignore
            write_app_status(app_id=self.module_id, app_name=self.module_name,
                             status=status, recent_events=events[:5])
            return True
        except Exception:
            return False

    def run(self, publish: bool = True, quiet: bool = False) -> dict:
        if not passes_one_rule(self.one_rule):
            raise SystemExit("[%s] fails The One Rule - archive it." % self.module_id)
        opps = self.scan()
        for o in opps:
            o.priority = grade(o.score)
        opps.sort(key=lambda o: o.score, reverse=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "layer": self.layer,
            "generated": utcnow(),
            "one_rule": self.one_rule,
            "count": len(opps),
            "opportunities": [o.to_dict() for o in opps],
        }
        (self.output_dir / "opportunities.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8")
        if publish:
            top = opps[0].title if opps else "no opportunities"
            self.publish_feed("ok", ["%d opportunities" % len(opps), "top: " + top])
        if not quiet:
            self._print_summary(opps)
        return result

    def _print_summary(self, opps: list) -> None:
        bar = "=" * 60
        print("")
        print(bar)
        print("  " + self.module_name + "  [" + self.layer + "]")
        print(bar)
        print("  Generated: %s  -  %d opportunities" % (utcnow(), len(opps)))
        print("")
        if not opps:
            print("  (no opportunities this cycle)")
            print("")
            return
        for i, o in enumerate(opps[:10], 1):
            roi = "" if o.roi_estimate is None else ("  ROI~%g" % o.roi_estimate)
            print("  %2d. [%s] %5.1f  %s%s  -  risk=%s" % (i, o.priority, o.score, o.title, roi, o.risk))
            print("      -> " + o.action)
        print("")
        print("  Output: " + str(self.output_dir / "opportunities.json"))
        print("")
