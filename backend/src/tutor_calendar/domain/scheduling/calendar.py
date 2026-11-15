"""The tutor's own calendar: which instants belong to which of their days.

A day is a local idea. It starts at midnight on the tutor's clock, except in
the few zones that change their clocks at midnight, where once a year a day
starts at 01:00 because 00:00 never happens.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tutor_calendar.domain.scheduling.booking import Booking
from tutor_calendar.domain.scheduling.time_range import TimeRange

_ONE_DAY = timedelta(days=1)


def start_of_day(day: date, tz: ZoneInfo) -> datetime:
    """The first instant of a local calendar day.

    When midnight does not exist the wall time is read with the offset in force
    before the change, which lands exactly on the instant the clocks jump - the
    first moment that belongs to the new day.
    """
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def local_day(instant: datetime, tz: ZoneInfo) -> date:
    return instant.astimezone(tz).date()


@dataclass(frozen=True, slots=True)
class Day:
    day: date
    lessons: tuple[Booking, ...]


@dataclass(frozen=True, slots=True)
class Week:
    """Monday to Sunday on the tutor's calendar, with the lessons of each day."""

    days: tuple[Day, ...]

    @property
    def start(self) -> date:
        return self.days[0].day

    @property
    def previous(self) -> date:
        return self.start - 7 * _ONE_DAY

    @property
    def next(self) -> date:
        return self.start + 7 * _ONE_DAY


def monday_of(day: date) -> date:
    return day - day.weekday() * _ONE_DAY


def week_range(day: date, tz: ZoneInfo) -> TimeRange:
    """Every instant of the Monday-to-Sunday week that contains ``day``."""
    monday = monday_of(day)
    return TimeRange(start_of_day(monday, tz), start_of_day(monday + 7 * _ONE_DAY, tz))


def lay_out_week(day: date, tz: ZoneInfo, bookings: Iterable[Booking]) -> Week:
    """Place lessons on the days of the week containing ``day``.

    A lesson belongs to the local day it starts on. Lessons that start outside
    the week are ignored.
    """
    monday = monday_of(day)
    by_day: dict[date, list[Booking]] = {monday + n * _ONE_DAY: [] for n in range(7)}
    for booking in bookings:
        lessons = by_day.get(local_day(booking.slot.start, tz))
        if lessons is not None:
            lessons.append(booking)
    return Week(
        tuple(
            Day(each, tuple(sorted(lessons, key=lambda lesson: lesson.slot.start)))
            for each, lessons in by_day.items()
        )
    )
