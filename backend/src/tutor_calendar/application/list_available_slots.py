from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tutor_calendar.application.errors import InvalidWindowError, TutorNotFoundError
from tutor_calendar.application.ports import BookingRepository, Clock, TutorRepository
from tutor_calendar.domain.scheduling import TimeRange, Tutor, generate_slots


@dataclass(frozen=True, slots=True)
class AvailableSlots:
    tutor: Tutor
    slots: list[TimeRange]


class ListAvailableSlots:
    """Slots a visitor can still book with a tutor inside a requested window."""

    DEFAULT_WINDOW = timedelta(days=14)
    MAX_WINDOW = timedelta(days=62)

    def __init__(self, tutors: TutorRepository, bookings: BookingRepository, clock: Clock) -> None:
        self._tutors = tutors
        self._bookings = bookings
        self._clock = clock

    async def execute(
        self,
        slug: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> AvailableSlots:
        if start is not None and end is not None and end <= start:
            raise InvalidWindowError("'to' must be later than 'from'")

        tutor = await self._tutors.get_by_slug(slug)
        if tutor is None:
            raise TutorNotFoundError(slug)

        # The past and anything inside the notice period is never bookable,
        # whatever the caller asked for.
        earliest = self._clock.now() + tutor.min_notice
        window_start = earliest if start is None else max(start, earliest)
        window_end = window_start + self.DEFAULT_WINDOW if end is None else end

        if window_end <= window_start:
            return AvailableSlots(tutor, [])
        if window_end - window_start > self.MAX_WINDOW:
            raise InvalidWindowError(f"window cannot be longer than {self.MAX_WINDOW.days} days")

        window = TimeRange(window_start, window_end)
        busy = await self._bookings.busy_between(tutor.id, window)
        return AvailableSlots(tutor, generate_slots(tutor.schedule, window, busy))
