"""Weekly lessons a tutor sets up for a regular student."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid5

from tutor_calendar.application.errors import (
    InvalidSeriesError,
    SeriesConflictError,
    SeriesNotFoundError,
)
from tutor_calendar.application.ports import BookingRepository, Clock
from tutor_calendar.domain.scheduling import (
    Actor,
    Booking,
    LessonSeries,
    LessonStatus,
    Tutor,
    WeeklySeries,
    local_day,
)


@dataclass(frozen=True, slots=True)
class SeriesOverview:
    series: LessonSeries
    lessons: list[Booking]
    # Days of the plan that have no lesson: days off, a start the clocks
    # skipped, or days left out because something else was already booked.
    days_without_lesson: list[date]


def _overview(series: LessonSeries, lessons: list[Booking], tutor: Tutor) -> SeriesOverview:
    tz = tutor.schedule.timezone
    with_lesson = {local_day(lesson.slot.start, tz) for lesson in lessons}
    return SeriesOverview(
        series, lessons, [day for day in series.plan.days() if day not in with_lesson]
    )


class StartSeries:
    """Book a lesson every week for a number of weeks.

    The lessons are stored as ordinary bookings, so everything that protects a
    single booking protects them too, and nothing else in the system needs to
    know that series exist. See ADR 0006.

    The caller chooses the id of the series. Asking again with the same id
    returns the series as it was first created, which makes the request safe
    to repeat.
    """

    def __init__(self, bookings: BookingRepository, clock: Clock) -> None:
        self._bookings = bookings
        self._clock = clock

    async def execute(
        self, tutor: Tutor, series_id: UUID, plan: WeeklySeries, *, skip_conflicts: bool = False
    ) -> SeriesOverview:
        earlier = await self._bookings.get_series(series_id)
        if earlier is not None:
            if earlier.tutor_id != tutor.id or earlier.plan != plan:
                raise InvalidSeriesError("this series id is already used for a different series")
            return _overview(earlier, await self._bookings.lessons_of_series(series_id), tutor)

        now = self._clock.now()
        occurrences, _ = plan.lay_out(tutor.schedule)
        upcoming = [each for each in occurrences if each.slot.start > now]
        if not upcoming:
            raise InvalidSeriesError("none of these lessons would be in the future")

        series = LessonSeries(series_id, tutor.id, plan, now)
        lessons = [
            Booking(
                # Derived from the series and the day, so that a repeat of this
                # request can never create a second lesson for the same day.
                id=uuid5(series_id, each.day.isoformat()),
                tutor_id=tutor.id,
                slot=each.slot,
                student=plan.student,
                created_at=now,
                series_id=series_id,
            )
            for each in upcoming
        ]
        stored = await self._bookings.add_series(series, lessons, skip_conflicts=skip_conflicts)
        if not stored:
            # Every single lesson was in the way of something: there is no series to keep.
            raise SeriesConflictError([each.slot for each in upcoming])
        return _overview(series, stored, tutor)


class ListSeries:
    def __init__(self, bookings: BookingRepository) -> None:
        self._bookings = bookings

    async def execute(self, tutor: Tutor) -> list[SeriesOverview]:
        return [
            _overview(series, await self._bookings.lessons_of_series(series.id), tutor)
            for series in await self._bookings.series(tutor.id)
        ]


class EndSeries:
    """Cancel the lessons of a series that have not started yet.

    Lessons that already took place, or were cancelled one by one, are history
    and stay as they are.
    """

    def __init__(self, bookings: BookingRepository, clock: Clock) -> None:
        self._bookings = bookings
        self._clock = clock

    async def execute(self, tutor: Tutor, series_id: UUID) -> SeriesOverview:
        series = await self._bookings.get_series(series_id)
        if series is None or series.tutor_id != tutor.id:
            raise SeriesNotFoundError

        now = self._clock.now()
        lessons = await self._bookings.lessons_of_series(series_id)
        changes = [
            (lesson, lesson.cancel(Actor.TUTOR, now, tutor.cancellation_policy))
            for lesson in lessons
            if lesson.status is LessonStatus.CONFIRMED and lesson.slot.start > now
        ]
        await self._bookings.apply(changes)
        return _overview(series, await self._bookings.lessons_of_series(series_id), tutor)
