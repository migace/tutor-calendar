"""What a signed-in tutor can see and change."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from tutor_calendar.application.errors import InvalidAvailabilityError
from tutor_calendar.application.ports import BookingRepository, Clock, TutorRepository
from tutor_calendar.domain.scheduling import (
    Tutor,
    Week,
    WeeklyRule,
    lay_out_week,
    local_day,
    week_range,
)


@dataclass(frozen=True, slots=True)
class WeekView:
    week: Week
    # Today on the tutor's calendar, which need not be today on the server's.
    today: date


class ShowWeek:
    """One Monday-to-Sunday week of the tutor's lessons."""

    def __init__(self, bookings: BookingRepository, clock: Clock) -> None:
        self._bookings = bookings
        self._clock = clock

    async def execute(self, tutor: Tutor, day: date | None = None) -> WeekView:
        tz = tutor.schedule.timezone
        today = local_day(self._clock.now(), tz)
        shown = day or today
        lessons = await self._bookings.starting_between(tutor.id, week_range(shown, tz))
        return WeekView(lay_out_week(shown, tz, lessons), today)


class ChangeWeeklyHours:
    """Replace the hours a tutor teaches each week.

    Lessons that are already booked stay as they are, including any that fall
    outside the new hours: a booking is a promise about a specific moment, not
    about a rule that happened to produce it.
    """

    def __init__(self, tutors: TutorRepository) -> None:
        self._tutors = tutors

    async def execute(self, tutor: Tutor, rules: Sequence[WeeklyRule]) -> Tutor:
        try:
            changed = tutor.with_weekly_hours(tuple(rules))
        except ValueError as error:
            raise InvalidAvailabilityError(str(error)) from error
        await self._tutors.replace_weekly_hours(tutor.id, changed.schedule.rules)
        return changed
