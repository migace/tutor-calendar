"""In-memory booking repository: the fake that fast tests use instead of PostgreSQL.

It keeps the same two guarantees as the real adapter, and the contract tests in
``tests/contract`` run against both to keep them from drifting apart. There is
no ``await`` between its check and its write, so on a single event loop the
pair is atomic without a lock.
"""

from __future__ import annotations

from uuid import UUID

from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.domain.scheduling import Booking, TimeRange


class InMemoryBookingRepository:
    def __init__(self) -> None:
        self._bookings: list[Booking] = []
        self._by_key: dict[tuple[UUID, str], Booking] = {}

    async def busy_between(self, tutor_id: UUID, window: TimeRange) -> list[TimeRange]:
        return sorted(
            booking.slot
            for booking in self._bookings
            if booking.tutor_id == tutor_id and booking.slot.overlaps(window)
        )

    async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None:
        return self._by_key.get((tutor_id, key))

    async def add(self, booking: Booking, idempotency_key: str) -> Booking:
        earlier = self._by_key.get((booking.tutor_id, idempotency_key))
        if earlier is not None:
            return earlier
        if any(
            other.tutor_id == booking.tutor_id and other.slot.overlaps(booking.slot)
            for other in self._bookings
        ):
            raise SlotTakenError
        self._bookings.append(booking)
        self._by_key[(booking.tutor_id, idempotency_key)] = booking
        return booking
