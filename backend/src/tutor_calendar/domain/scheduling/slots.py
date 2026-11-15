"""Turns a weekly schedule into concrete, bookable slots.

The interesting part is daylight saving time. Slots are laid out on the tutor's
wall clock and then converted to instants, and three things can go wrong:

* the wall-clock start does not exist (spring forward) - the slot is skipped;
* the wall-clock start happens twice (fall back) - the first occurrence wins;
* a slot that straddles the spring gap ends an hour "later" on the wall clock
  than its position on the grid suggests, so it may run past the end of the
  rule or into the next grid position - both are rejected.

Lesson length is always real elapsed time: a 60-minute lesson lasts 60 minutes
even on the night the clocks change.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from tutor_calendar.domain.scheduling.availability import Schedule
from tutor_calendar.domain.scheduling.time_range import TimeRange

_ONE_DAY = timedelta(days=1)


def generate_slots(
    schedule: Schedule,
    window: TimeRange,
    busy: Iterable[TimeRange] = (),
) -> list[TimeRange]:
    """Free slots that lie entirely inside ``window``, ordered by start.

    The grid of slots depends only on the schedule. ``window`` and ``busy``
    filter that grid and never shift it, so asking for a narrower window always
    returns a subset of what a wider one returns.
    """
    taken = tuple(busy)
    tz = schedule.timezone
    # A slot never ends after its own rule, so each local day's grid is
    # self-contained and the window's first local day is early enough to start.
    day = window.start.astimezone(tz).date()
    last_day = window.end.astimezone(tz).date()

    slots: list[TimeRange] = []
    previous_end: datetime | None = None
    while day <= last_day:
        for slot in _grid_for_day(schedule, day):
            if previous_end is not None and slot.start < previous_end:
                continue
            previous_end = slot.end
            if window.contains(slot) and not any(slot.overlaps(other) for other in taken):
                slots.append(slot)
        day += _ONE_DAY
    return slots


def slot_starting_at(schedule: Schedule, start: datetime) -> TimeRange | None:
    """The slot on the schedule's grid that starts at ``start``, if there is one.

    This is how a requested booking is checked against the schedule: a client
    names a start instant, and only an instant the grid really contains is
    accepted. Whether that slot is still free is a separate question.
    """
    candidate = TimeRange(start, start + schedule.lesson_duration)
    return candidate if generate_slots(schedule, candidate) == [candidate] else None


def _grid_for_day(schedule: Schedule, day: date) -> Iterator[TimeRange]:
    tz = schedule.timezone
    duration = schedule.lesson_duration
    for rule in schedule.rules_on(day):
        wall_end = datetime.combine(day, rule.end)
        cursor = datetime.combine(day, rule.start)
        while cursor + duration <= wall_end:
            start = _instant_at(cursor, tz)
            cursor += duration
            if start is None:
                continue
            end = start + duration
            if _wall_clock(end, tz) > wall_end:
                continue
            yield TimeRange(start, end)


def _instant_at(wall: datetime, tz: ZoneInfo) -> datetime | None:
    """The instant a naive wall-clock time refers to, or ``None`` if it never happens.

    An ambiguous time resolves to its first occurrence (``fold=0``).
    """
    instant = wall.replace(tzinfo=tz).astimezone(UTC)
    if _wall_clock(instant, tz) != wall:
        return None
    return instant


def _wall_clock(instant: datetime, tz: ZoneInfo) -> datetime:
    return instant.astimezone(tz).replace(tzinfo=None)
