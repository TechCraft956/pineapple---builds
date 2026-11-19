from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from .planner import TYPE_PRIORITY_BOOST
from .schemas import BriefItem, DailyBrief, ItemStatus, ItemType, SchoolItem
from .storage import get_courses, get_items
from .utils import days_until


def _to_brief_item(item: SchoolItem, course_name: Optional[str]) -> BriefItem:
    return BriefItem(
        item_id=item.item_id,
        title=item.title,
        type=item.type,
        due_date=item.due_date,
        days_until_due=days_until(item.due_date),
        status=item.status,
        confidence_score=item.confidence_score,
        course_name=course_name,
    )


def _exam_weight(item: SchoolItem) -> float:
    """Type weight used to order items at equal proximity.

    RECONCILED (Task 2b, 2026-11-17): this used to be a flat 1.3× for exam
    AND quiz, disagreeing with planner.py (exam 1.4×, quiz 1.2×). It now
    defers to planner.TYPE_PRIORITY_BOOST, the single source of truth, so
    an exam outranks a quiz at the same due date. The planner's grade-weight
    multiplier is intentionally NOT applied here: the brief ranks by
    due-date proximity × type only.
    """
    return TYPE_PRIORITY_BOOST.get(item.type, 1.0)


def _is_active(item: SchoolItem) -> bool:
    return item.status not in (ItemStatus.done, ItemStatus.ignored)


def generate_brief(course_id: Optional[str] = None) -> DailyBrief:
    """Build the daily brief.

    7-DAY WINDOW (documented behaviour, Task 2b): only items due within
    7 days appear in the dated buckets (overdue / within 48h / upcoming
    7d). Items due MORE than 7 days out are OMITTED from the brief entirely
    — they still exist as stored items and are NOT deleted — and no-date
    items appear in the no_due_date bucket. This brief is therefore NOT a
    complete upcoming schedule; anything beyond 7 days must be read from
    the /school/items list.
    """
    items = get_items(course_id=course_id)
    courses = {c.course_id: c.name for c in get_courses()}

    today = date.today()
    active = [i for i in items if _is_active(i)]

    overdue: list[SchoolItem] = []
    within_48h: list[SchoolItem] = []
    upcoming_7d: list[SchoolItem] = []
    no_date: list[SchoolItem] = []

    for item in active:
        d = days_until(item.due_date)
        if d is None:
            no_date.append(item)
        elif d < 0:
            overdue.append(item)
        elif d <= 2:
            within_48h.append(item)
        elif d <= 7:
            upcoming_7d.append(item)

    # Sort each bucket: exams first, then by proximity
    def sort_key(i: SchoolItem):
        d = days_until(i.due_date)
        proximity = d if d is not None else 999
        return (proximity / _exam_weight(i),)

    overdue.sort(key=sort_key)
    within_48h.sort(key=sort_key)
    upcoming_7d.sort(key=sort_key)

    def to_brief(items_list: list[SchoolItem]) -> list[BriefItem]:
        return [_to_brief_item(i, courses.get(i.course_id or "")) for i in items_list]

    # Top 3 plain-language actions
    top_actions = _build_top_actions(overdue, within_48h, upcoming_7d)

    return DailyBrief(
        overdue=to_brief(overdue),
        due_within_48h=to_brief(within_48h),
        upcoming_7d=to_brief(upcoming_7d),
        no_due_date=to_brief(no_date),
        top_actions=top_actions,
    )


def _build_top_actions(
    overdue: list[SchoolItem],
    within_48h: list[SchoolItem],
    upcoming_7d: list[SchoolItem],
) -> list[str]:
    actions: list[str] = []

    for item in overdue[:2]:
        actions.append(f"OVERDUE — submit {item.title} immediately")

    for item in within_48h[:2]:
        d = days_until(item.due_date)
        label = "today" if d == 0 else ("tomorrow" if d == 1 else f"in {d} days")
        actions.append(f"Complete {item.title} — due {label}")

    for item in upcoming_7d[:1]:
        d = days_until(item.due_date)
        if item.type in (ItemType.exam,):
            actions.append(f"Start studying for {item.title} — {d} days away")
        else:
            actions.append(f"Begin {item.title} — due in {d} days")

    return actions[:3]
