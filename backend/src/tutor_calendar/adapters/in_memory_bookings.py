"""In-memory booking repository: the fake that fast tests use instead of PostgreSQL.

It keeps the same guarantees as the real adapter, and the contract tests in
``tests/contract`` run against both to keep them from drifting apart. There is
no ``await`` between any check and the write that follows it, so on a single
event loop each method is atomic without a lock.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from tutor_calendar.adapters.in_memory_billing import InMemoryOutbox
from tutor_calendar.application.errors import SeriesConflictError, SlotTakenError
from tutor_calendar.application.ports import Email, StudentRecord
from tutor_calendar.domain.billing import account_key, is_settled
from tutor_calendar.domain.scheduling import Booking, LessonSeries, LessonStatus, TimeRange


class InMemoryBookingRepository:
    def __init__(self, outbox: InMemoryOutbox | None = None) -> None:
        self._bookings: dict[UUID, Booking] = {}
        self._by_key: dict[tuple[UUID, str], UUID] = {}
        self._series: dict[UUID, LessonSeries] = {}
        # (tutor, address) to the student's id.
        self._students: dict[tuple[UUID, str], UUID] = {}
        self._settled: set[UUID] = set()
        self._reminded: set[UUID] = set()
        # Where confirmations and reminders are queued. Shared with whoever delivers them.
        self.outbox = outbox or InMemoryOutbox()

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

    async def add(
        self, booking: Booking, idempotency_key: str, confirmation: Email | None = None
    ) -> Booking:
        earlier = self._with_key(booking.tutor_id, idempotency_key)
        if earlier is not None:
            return earlier
        if self._is_taken(booking):
            raise SlotTakenError
        self._store(booking, idempotency_key)
        if confirmation is not None:
            self.outbox.put(confirmation, booking.created_at)
        return booking

    async def students(self, tutor_id: UUID) -> list[StudentRecord]:
        return [
            self._record(tutor, account) for tutor, account in self._students if tutor == tutor_id
        ]

    async def get_student(self, student_id: UUID) -> StudentRecord | None:
        return next(
            (self._record(*key) for key, each in self._students.items() if each == student_id),
            None,
        )

    async def find_student(self, tutor_id: UUID, account: str) -> StudentRecord | None:
        return self._record(tutor_id, account) if (tutor_id, account) in self._students else None

    async def enrol(self, tutor_id: UUID, account: str, now: datetime) -> StudentRecord:
        self._students.setdefault((tutor_id, account), uuid4())
        return self._record(tutor_id, account)

    def _record(self, tutor_id: UUID, account: str) -> StudentRecord:
        lessons = sorted(
            (
                booking
                for booking in self._bookings.values()
                if booking.tutor_id == tutor_id and account_key(booking.student.email) == account
            ),
            key=lambda booking: booking.created_at,
        )
        name = lessons[-1].student.name if lessons else None
        return StudentRecord(self._students[tutor_id, account], tutor_id, account, name)

    async def awaiting_settlement(self, now: datetime, limit: int) -> list[Booking]:
        waiting = [
            booking
            for booking in self._bookings.values()
            if booking.id not in self._settled and is_settled(booking, now)
        ]
        return sorted(waiting, key=lambda booking: booking.slot.start)[:limit]

    async def mark_settled(self, booking_ids: Sequence[UUID], now: datetime) -> None:
        self._settled.update(booking_ids)

    async def due_for_reminder(self, now: datetime, lead: timedelta, limit: int) -> list[Booking]:
        due = [
            booking
            for booking in self._bookings.values()
            if booking.id not in self._reminded
            and booking.status is LessonStatus.CONFIRMED
            and now < booking.slot.start <= now + lead
            and booking.created_at <= booking.slot.start - lead
        ]
        return sorted(due, key=lambda booking: booking.slot.start)[:limit]

    async def record_reminders(
        self, reminders: Sequence[tuple[Booking, Email]], now: datetime
    ) -> int:
        queued = 0
        for booking, email in reminders:
            stored = self._bookings.get(booking.id)
            if (
                stored is None
                or stored.status is not LessonStatus.CONFIRMED
                or booking.id in self._reminded
            ):
                continue
            self._reminded.add(booking.id)
            self.outbox.put(email, now)
            queued += 1
        return queued

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
        self._students.setdefault((booking.tutor_id, account_key(booking.student.email)), uuid4())
        self._bookings[booking.id] = booking
        self._by_key[(booking.tutor_id, idempotency_key)] = booking.id
