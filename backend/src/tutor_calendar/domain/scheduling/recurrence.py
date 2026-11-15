"""Weekly lessons: the same student at the same time on the tutor's clock.

Like availability rules, a series is a wall-clock fact ("Tuesdays at 17:00"),
so its lessons stay at 17:00 when the clocks change. See ADR 0002.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from tutor_calendar.domain.scheduling.availability import Schedule
from tutor_calendar.domain.scheduling.booking import Student
from tutor_calendar.domain.scheduling.time_range import TimeRange

MAX_OCCURRENCES = 52
_ONE_WEEK = timedelta(weeks=1)


@dataclass(frozen=True, slots=True)
class Occurrence:
    day: date
    slot: TimeRange


@dataclass(frozen=True, slots=True)
class WeeklySeries:
    """A request for lessons once a week, starting on a given day."""

    first_day: date
    start: time
    weeks: int
    student: Student

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None:
            raise ValueError("a series starts at a wall-clock time and must be naive")
        if self.start.second or self.start.microsecond:
            raise ValueError("a series must start on a whole minute")
        if not 1 <= self.weeks <= MAX_OCCURRENCES:
            raise ValueError(f"a series has between 1 and {MAX_OCCURRENCES} lessons")

    def days(self) -> list[date]:
        return [self.first_day + n * _ONE_WEEK for n in range(self.weeks)]

    def lay_out(self, schedule: Schedule) -> tuple[list[Occurrence], list[date]]:
        """The lessons of the series as instants, and the days that get none.

        A day gets no lesson when the tutor has it off, or when the wall-clock
        start does not exist that day because the clocks jump over it. A start
        that happens twice (clocks going back) means the first time.
        """
        tz = schedule.timezone
        occurrences: list[Occurrence] = []
        skipped: list[date] = []
        for day in self.days():
            wall = datetime.combine(day, self.start)
            start = wall.replace(tzinfo=tz).astimezone(UTC)
            exists = start.astimezone(tz).replace(tzinfo=None) == wall
            if day in schedule.days_off or not exists:
                skipped.append(day)
                continue
            occurrences.append(Occurrence(day, TimeRange(start, start + schedule.lesson_duration)))
        return occurrences, skipped


@dataclass(frozen=True, slots=True)
class LessonSeries:
    """A weekly series a tutor has set up, as it is remembered."""

    id: UUID
    tutor_id: UUID
    plan: WeeklySeries
    created_at: datetime
