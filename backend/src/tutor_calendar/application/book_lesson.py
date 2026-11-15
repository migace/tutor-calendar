from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from tutor_calendar.application.errors import (
    IdempotencyKeyReusedError,
    SlotNotOfferedError,
    TutorNotFoundError,
)
from tutor_calendar.application.ports import BookingRepository, Clock, ManageLinks, TutorRepository
from tutor_calendar.domain.scheduling import Booking, Student, slot_starting_at


@dataclass(frozen=True, slots=True)
class BookingResult:
    booking: Booking
    # True when this request repeated an earlier one and created nothing new.
    replayed: bool
    # Lets the student look at and cancel this booking later. The same for a
    # repeat as for the first attempt, because it is computed, not stored.
    manage_token: str


class BookLesson:
    """Reserve one lesson with a tutor.

    Safe to repeat: sending the same request again with the same idempotency
    key returns the booking the first attempt created. A client that lost the
    response to a timeout can therefore simply try again.

    Whether the time is still free is deliberately not checked here. Two
    requests can both pass such a check before either has stored anything, so
    the answer comes from ``BookingRepository.add``, which decides atomically.
    """

    def __init__(
        self,
        tutors: TutorRepository,
        bookings: BookingRepository,
        links: ManageLinks,
        clock: Clock,
    ) -> None:
        self._tutors = tutors
        self._bookings = bookings
        self._links = links
        self._clock = clock

    async def execute(
        self,
        slug: str,
        start: datetime,
        student: Student,
        idempotency_key: str,
    ) -> BookingResult:
        tutor = await self._tutors.get_by_slug(slug)
        if tutor is None:
            raise TutorNotFoundError(slug)

        # Before any other check: a repeat must get the original answer even if
        # the time has meanwhile slipped inside the notice period.
        earlier = await self._bookings.get_by_idempotency_key(tutor.id, idempotency_key)
        if earlier is not None:
            return self._replay(earlier, start, student)

        now = self._clock.now()
        if start < now + tutor.min_notice:
            raise SlotNotOfferedError("this time is too soon to be booked")
        slot = slot_starting_at(tutor.schedule, start)
        if slot is None:
            raise SlotNotOfferedError("the tutor does not offer a lesson at this time")

        booking = Booking(id=uuid4(), tutor_id=tutor.id, slot=slot, student=student, created_at=now)
        stored = await self._bookings.add(booking, idempotency_key)
        if stored.id != booking.id:
            # The same key arrived twice at once and the other request won.
            return self._replay(stored, start, student)
        return BookingResult(stored, replayed=False, manage_token=self._links.token_for(stored.id))

    def _replay(self, earlier: Booking, start: datetime, student: Student) -> BookingResult:
        if earlier.slot.start != start or earlier.student != student:
            raise IdempotencyKeyReusedError
        return BookingResult(earlier, replayed=True, manage_token=self._links.token_for(earlier.id))
