"""Weekly availability, expressed in the tutor's own wall-clock time.

A rule says "Tuesdays 17:00-19:00" and means it literally: after a daylight
saving change the lesson is still at 17:00 on the tutor's clock. Rules are
therefore stored as naive local times plus an IANA zone, never as UTC offsets.
See docs/adr/0002-time-model.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import IntEnum
from itertools import pairwise
from zoneinfo import ZoneInfo


class Weekday(IntEnum):
    """Matches ``date.weekday()``."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True, slots=True)
class WeeklyRule:
    """A recurring block of availability on one weekday, within a single local day."""

    weekday: Weekday
    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("rule times are wall-clock times and must be naive")
        if self.start >= self.end:
            raise ValueError("a rule must start before it ends on the same day")


@dataclass(frozen=True, slots=True)
class Schedule:
    timezone: ZoneInfo
    lesson_duration: timedelta
    rules: tuple[WeeklyRule, ...]
    days_off: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        if self.lesson_duration <= timedelta(0):
            raise ValueError("lesson duration must be positive")
        if self.lesson_duration % timedelta(minutes=1):
            raise ValueError("lesson duration must be a whole number of minutes")
        ordered = tuple(sorted(self.rules, key=lambda rule: (rule.weekday, rule.start)))
        for earlier, later in pairwise(ordered):
            if earlier.weekday == later.weekday and later.start < earlier.end:
                raise ValueError(f"rules overlap on {earlier.weekday.name.title()}")
        object.__setattr__(self, "rules", ordered)

    def rules_on(self, day: date) -> Iterator[WeeklyRule]:
        """Rules that apply on a local calendar day, earliest first."""
        if day in self.days_off:
            return
        weekday = day.weekday()
        yield from (rule for rule in self.rules if rule.weekday == weekday)
