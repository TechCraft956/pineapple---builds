from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .schemas import InferredTask, ItemStatus, ItemType, SchoolItem
from .storage import get_items, save_task
from .utils import days_until


# ── Single source of truth for type weighting (Task 2b reconciliation) ─────────
# BEFORE: planner.py used exam 1.4× / quiz 1.2× (+ grade-weight multiplier)
# while brief.py used a flat 1.3× for both exam and quiz. The two disagreed,
# so ranking depended on which code path produced it.
# RESOLVED 2026-11-17: planner.py's per-type multipliers govern EVERYWHERE.
# brief.py imports this dict instead of carrying its own 1.3×. The grade-weight
# multiplier (1 + weight/100) remains planner-only: the brief ranks by
# due-date proximity × type, not by grade weight — see brief.py.
TYPE_PRIORITY_BOOST = {
    ItemType.exam:       1.4,
    ItemType.quiz:       1.2,
    ItemType.lab:        1.1,
    ItemType.project:    1.15,
    ItemType.assignment: 1.0,
    ItemType.discussion: 0.9,
    ItemType.other:      0.8,
}


def _priority_score(item: SchoolItem) -> float:
    """
    Simple priority heuristic for v1.
    Score range: 0.0 – 1.0 (higher = more urgent).
    """
    d = days_until(item.due_date)

    # No due date: medium-low priority
    if d is None:
        return 0.3

    # Overdue: highest
    if d < 0:
        return 1.0

    # Proximity decay: closer = higher score
    proximity = max(0.0, 1.0 - (d / 30))

    # Type multiplier — from the single source of truth above.
    type_boost = TYPE_PRIORITY_BOOST.get(item.type, 1.0)

    # Weight multiplier (if we know grade %)
    weight_factor = 1.0
    if item.weight:
        weight_factor = 1.0 + (item.weight / 100)

    return min(1.0, proximity * type_boost * weight_factor)


def _suggested_start(item: SchoolItem) -> Optional[date]:
    if item.due_date is None:
        return None
    d = days_until(item.due_date)
    if d is None:
        return None

    lead = {
        ItemType.exam:       7,
        ItemType.project:    5,
        ItemType.lab:        3,
        ItemType.quiz:       2,
        ItemType.assignment: 2,
        ItemType.discussion: 1,
    }.get(item.type, 2)

    start = item.due_date - timedelta(days=lead)
    return max(start, date.today())


def _action_label(item: SchoolItem) -> str:
    verbs = {
        ItemType.exam:       "Study for",
        ItemType.quiz:       "Review for",
        ItemType.lab:        "Complete",
        ItemType.discussion: "Write and post",
        ItemType.project:    "Work on",
    }
    verb = verbs.get(item.type, "Complete")
    return f"{verb} {item.title}"


def infer_tasks(course_id: Optional[str] = None) -> list[InferredTask]:
    """Generate InferredTasks for all active items without existing tasks."""
    items = get_items(course_id=course_id)
    tasks: list[InferredTask] = []

    for item in items:
        if item.status in (ItemStatus.done, ItemStatus.ignored):
            continue

        task = InferredTask(
            linked_item_id=item.item_id,
            action=_action_label(item),
            suggested_start_date=_suggested_start(item),
            priority_score=_priority_score(item),
        )
        tasks.append(task)

    tasks.sort(key=lambda t: t.priority_score, reverse=True)
    return tasks


def save_inferred_tasks(tasks: list[InferredTask]) -> None:
    for task in tasks:
        save_task(task)
