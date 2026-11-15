"""In-memory booking repository: the fake that fast tests use instead of PostgreSQL.

It keeps the same guarantees as the real adapter, and the contract tests in
``tests/contract`` run against both to keep them from drifting apart. There is
no ``await`` between any check and the write that follows it, so on a single
event loop each method is atomic without a lock.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from tutor_calendar.application.errors import SeriesConflictError, SlotTakenError
from tutor_calendar.domain.scheduling import Booking, LessonSeries, TimeRange


class InMemoryBookingRepository:
    def __init__(self) -> None:
        self._bookings: dict[UUID, Booking] = {}
        self._by_key: dict[tuple[UUID, str], UUID] = {}
        self._series: dict[UUID, LessonSeries] = {}

    async def busy_between(self, tutor_id: UUID, window: TimeRange) -> list[TimeRange]:
        return sorted(
            booking.slot
            for booking in self._bookings.values()
            if booking.tutor_id == tutor_id
            and booking.occupies_time
            and booking.slot.overlaps(window)
        )

    async def starting_between(self, tutor_id: UUID, window: TimeRange) -> list[Booking]:
        return sorted(
            (
                booking
                for booking in self._bookings.values()
                if booking.tutor_id == tutor_id and window.start <= booking.slot.start < window.end
            ),
            key=lambda booking: booking.slot.start,
        )

    async def get(self, booking_id: UUID) -> Booking | None:
        return self._bookings.get(booking_id)

    async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None:
        return self._with_key(tutor_id, key)

    async def add(self, booking: Booking, idempotency_key: str) -> Booking:
        earlier = self._with_key(booking.tutor_id, idempotency_key)
        if earlier is not None:
            return earlier
        if self._is_taken(booking):
            raise SlotTakenError
        self._store(booking, idempotency_key)
        return booking

    async def apply(self, changes: Sequence[tuple[Booking, Booking]]) -> int:
        applied = 0
        for before, after in changes:
            stored = self._bookings.get(before.id)
            if stored is not None and stored.status is before.status:
                self._bookings[before.id] = after
                applied += 1
        return applied

    async def series(self, tutor_id: UUID) -> list[LessonSeries]:
        return sorted(
            (series for series in self._series.values() if series.tutor_id == tutor_id),
            key=lambda series: series.created_at,
        )

    async def get_series(self, series_id: UUID) -> LessonSeries | None:
        return self._series.get(series_id)

    async def lessons_of_series(self, series_id: UUID) -> list[Booking]:
        return sorted(
            (booking for booking in self._bookings.values() if booking.series_id == series_id),
            key=lambda booking: booking.slot.start,
        )

    async def add_series(
        self, series: LessonSeries, lessons: Sequence[Booking], *, skip_conflicts: bool
    ) -> list[Booking]:
        free = [lesson for lesson in lessons if not self._is_taken(lesson)]
        if len(free) < len(lessons) and not skip_conflicts:
            raise SeriesConflictError([each.slot for each in lessons if self._is_taken(each)])
        if not free:
            return []
        self._series[series.id] = series
        for lesson in free:
            self._store(lesson, f"series-{lesson.id}")
        return free

    def _with_key(self, tutor_id: UUID, key: str) -> Booking | None:
        booking_id = self._by_key.get((tutor_id, key))
        return None if booking_id is None else self._bookings[booking_id]

    def _is_taken(self, booking: Booking) -> bool:
        return any(
            other.tutor_id == booking.tutor_id
            and other.occupies_time
            and other.slot.overlaps(booking.slot)
            for other in self._bookings.values()
        )

    def _store(self, booking: Booking, idempotency_key: str) -> None:
        self._bookings[booking.id] = booking
        self._by_key[(booking.tutor_id, idempotency_key)] = booking.id
