"""Changing a lesson after it has been booked: cancelling it, or recording a no-show."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tutor_calendar.application.errors import LessonChangeRefusedError, LessonNotFoundError
from tutor_calendar.application.ports import BookingRepository, Clock, ManageLinks, TutorRepository
from tutor_calendar.domain.scheduling import (
    Actor,
    Booking,
    LessonStatus,
    LessonTransitionError,
    Tutor,
)


async def _change(
    bookings: BookingRepository, lesson: Booking, transition: Callable[[Booking], Booking]
) -> Booking:
    """Apply a transition to a lesson and store the result, or refuse."""
    try:
        changed = transition(lesson)
    except LessonTransitionError as error:
        raise LessonChangeRefusedError(str(error)) from error
    if await bookings.apply([(lesson, changed)]) != 1:
        # Someone else changed the lesson between our read and our write.
        raise LessonChangeRefusedError("this lesson has just been changed by someone else")
    return changed


@dataclass(frozen=True, slots=True)
class ManagedLesson:
    """A lesson as the student who booked it sees it."""

    lesson: Booking
    tutor: Tutor
    # Until when cancelling is free; None when it always is.
    free_until: datetime | None
    can_cancel: bool
    # Whether cancelling right now would still be charged.
    late_now: bool


class ManageBooking:
    """What a student can do with the link they got when booking: look, and cancel."""

    def __init__(
        self,
        bookings: BookingRepository,
        tutors: TutorRepository,
        links: ManageLinks,
        clock: Clock,
    ) -> None:
        self._bookings = bookings
        self._tutors = tutors
        self._links = links
        self._clock = clock

    async def view(self, token: str) -> ManagedLesson:
        lesson, tutor = await self._find(token)
        return self._describe(lesson, tutor)

    async def cancel(self, token: str) -> ManagedLesson:
        lesson, tutor = await self._find(token)
        now = self._clock.now()
        cancelled = await _change(
            self._bookings,
            lesson,
            lambda each: each.cancel(Actor.STUDENT, now, tutor.cancellation_policy),
        )
        return self._describe(cancelled, tutor)

    async def _find(self, token: str) -> tuple[Booking, Tutor]:
        booking_id = self._links.booking_id_in(token)
        lesson = None if booking_id is None else await self._bookings.get(booking_id)
        tutor = None if lesson is None else await self._tutors.get_by_id(lesson.tutor_id)
        if lesson is None or tutor is None:
            # One answer for a forged token and for a booking that is gone.
            raise LessonNotFoundError
        return lesson, tutor

    def _describe(self, lesson: Booking, tutor: Tutor) -> ManagedLesson:
        now = self._clock.now()
        policy = tutor.cancellation_policy
        can_cancel = lesson.status is LessonStatus.CONFIRMED and now < lesson.slot.start
        return ManagedLesson(
            lesson=lesson,
            tutor=tutor,
            free_until=policy.free_until(lesson),
            can_cancel=can_cancel,
            late_now=can_cancel and policy.is_late(lesson, Actor.STUDENT, now),
        )


class ChangeOwnLesson:
    """What a tutor can do to one of their own lessons."""

    def __init__(self, bookings: BookingRepository, clock: Clock) -> None:
        self._bookings = bookings
        self._clock = clock

    async def cancel(self, tutor: Tutor, lesson_id: UUID) -> Booking:
        now = self._clock.now()
        return await _change(
            self._bookings,
            await self._own(tutor, lesson_id),
            lambda lesson: lesson.cancel(Actor.TUTOR, now, tutor.cancellation_policy),
        )

    async def mark_no_show(self, tutor: Tutor, lesson_id: UUID) -> Booking:
        now = self._clock.now()
        return await _change(
            self._bookings,
            await self._own(tutor, lesson_id),
            lambda lesson: lesson.mark_no_show(now),
        )

    async def _own(self, tutor: Tutor, lesson_id: UUID) -> Booking:
        lesson = await self._bookings.get(lesson_id)
        # Another tutor's lesson is reported exactly like one that does not exist.
        if lesson is None or lesson.tutor_id != tutor.id:
            raise LessonNotFoundError
        return lesson
