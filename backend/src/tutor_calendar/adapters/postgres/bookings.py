from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Row, Select, func, insert, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tutor_calendar.adapters.postgres.billing import outbox_row
from tutor_calendar.adapters.postgres.tables import (
    BOOKINGS_IDEMPOTENCY_KEY,
    STUDENTS_ACCOUNT,
    bookings,
    lesson_series,
    outbox,
    students,
    tutors,
)
from tutor_calendar.application.errors import SeriesConflictError, SlotTakenError
from tutor_calendar.application.ports import Email, StudentRecord
from tutor_calendar.domain.billing import account_key
from tutor_calendar.domain.scheduling import (
    Actor,
    Booking,
    Cancellation,
    LessonSeries,
    LessonStatus,
    Student,
    TimeRange,
    WeeklySeries,
)

# https://www.postgresql.org/docs/current/errcodes-appendix.html
_EXCLUSION_VIOLATION = "23P01"

_occupies_time = bookings.c.status != LessonStatus.CANCELLED.value


class PostgresBookingRepository:
    """Bookings in PostgreSQL.

    Both guarantees of the port are enforced by constraints, so they hold no
    matter how many requests, processes or servers write at the same time.

    Writers for one tutor additionally queue on that tutor's row. The queue is
    not what prevents a double booking - the exclusion constraint does that on
    its own. It is there because conflicting inserts that run at the very same
    moment can find each other half-done and wait on each other, which
    PostgreSQL resolves by aborting one of them with a deadlock error a second
    later. In a queue the loser instead sees a committed booking and gets a
    plain, immediate answer. See ADR 0003.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def busy_between(self, tutor_id: UUID, window: TimeRange) -> list[TimeRange]:
        query = (
            select(bookings.c.during)
            .where(
                bookings.c.tutor_id == tutor_id,
                _occupies_time,
                bookings.c.during.overlaps(_range(window)),
            )
            .order_by(bookings.c.during)
        )
        async with self._engine.connect() as connection:
            rows = await connection.execute(query)
            return [TimeRange(row.during.lower, row.during.upper) for row in rows]

    async def starting_between(self, tutor_id: UUID, window: TimeRange) -> list[Booking]:
        starts = func.lower(bookings.c.during)
        query = (
            select(bookings)
            .where(bookings.c.tutor_id == tutor_id, starts >= window.start, starts < window.end)
            .order_by(starts)
        )
        async with self._engine.connect() as connection:
            return [_booking(row) for row in await connection.execute(query)]

    async def get(self, booking_id: UUID) -> Booking | None:
        return await self._one(bookings.c.id == booking_id)

    async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None:
        return await self._one(bookings.c.tutor_id == tutor_id, bookings.c.idempotency_key == key)

    async def _one(self, *conditions: Any) -> Booking | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(bookings).where(*conditions))).one_or_none()
            return None if row is None else _booking(row)

    async def add(
        self, booking: Booking, idempotency_key: str, confirmation: Email | None = None
    ) -> Booking:
        # A repeated key is not an error but "do nothing"; an overlap is an
        # error raised by the exclusion constraint.
        insert_booking = (
            pg_insert(bookings)
            .values(_values(booking, idempotency_key))
            .on_conflict_do_nothing(constraint=BOOKINGS_IDEMPOTENCY_KEY)
            .returning(bookings.c.id)
        )
        try:
            async with self._engine.begin() as connection:
                await _queue_behind_other_writers(connection, booking.tutor_id)
                inserted = (await connection.execute(insert_booking)).one_or_none()
                if inserted is not None:
                    await _enrol(
                        connection, booking.tutor_id, booking.student.email, booking.created_at
                    )
                if inserted is not None and confirmation is not None:
                    # Same transaction as the booking: the message is queued if
                    # and only if the booking is stored. See ADR 0007.
                    await connection.execute(
                        insert(outbox).values(outbox_row(confirmation, booking.created_at))
                    )
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == _EXCLUSION_VIOLATION:
                raise SlotTakenError from error
            raise

        if inserted is not None:
            return booking
        earlier = await self.get_by_idempotency_key(booking.tutor_id, idempotency_key)
        if earlier is None:
            raise RuntimeError("idempotency key conflicted with a booking that no longer exists")
        return earlier

    async def apply(self, changes: Sequence[tuple[Booking, Booking]]) -> int:
        applied = 0
        async with self._engine.begin() as connection:
            for before, after in changes:
                cancellation = after.cancellation
                # Compare-and-set on the status: the UPDATE matches only if nobody
                # has changed the lesson since ``before`` was read.
                result = await connection.execute(
                    update(bookings)
                    .where(bookings.c.id == before.id, bookings.c.status == before.status.value)
                    .values(
                        status=after.status.value,
                        cancelled_by=cancellation.by.value if cancellation else None,
                        cancelled_at=cancellation.at if cancellation else None,
                        cancelled_late=cancellation.late if cancellation else None,
                    )
                )
                applied += result.rowcount
        return applied

    async def students(self, tutor_id: UUID) -> list[StudentRecord]:
        async with self._engine.connect() as connection:
            rows = await connection.execute(_students_where(students.c.tutor_id == tutor_id))
            return [_student(row) for row in rows]

    async def get_student(self, student_id: UUID) -> StudentRecord | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(_students_where(students.c.id == student_id))
            ).one_or_none()
            return None if row is None else _student(row)

    async def find_student(self, tutor_id: UUID, account: str) -> StudentRecord | None:
        async with self._engine.connect() as connection:
            return await _find_student(connection, tutor_id, account)

    async def enrol(self, tutor_id: UUID, account: str, now: datetime) -> StudentRecord:
        async with self._engine.begin() as connection:
            await _enrol(connection, tutor_id, account, now)
            student = await _find_student(connection, tutor_id, account)
        if student is None:
            raise RuntimeError("a student vanished between being enrolled and being read")
        return student

    async def awaiting_settlement(self, now: datetime, limit: int) -> list[Booking]:
        # The same rule as ``is_settled`` in the domain, said in SQL.
        final = (bookings.c.status != LessonStatus.CONFIRMED.value) | (
            func.upper(bookings.c.during) <= now
        )
        query = (
            select(bookings)
            .where(bookings.c.settled_at.is_(None), final)
            .order_by(func.lower(bookings.c.during))
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            return [_booking(row) for row in await connection.execute(query)]

    async def mark_settled(self, booking_ids: Sequence[UUID], now: datetime) -> None:
        if not booking_ids:
            return
        async with self._engine.begin() as connection:
            await connection.execute(
                update(bookings)
                .where(bookings.c.id.in_(booking_ids), bookings.c.settled_at.is_(None))
                .values(settled_at=now)
            )

    async def due_for_reminder(self, now: datetime, lead: timedelta, limit: int) -> list[Booking]:
        starts = func.lower(bookings.c.during)
        query = (
            select(bookings)
            .where(
                bookings.c.reminded_at.is_(None),
                bookings.c.status == LessonStatus.CONFIRMED.value,
                starts > now,
                starts <= now + lead,
                bookings.c.created_at <= starts - lead,
            )
            .order_by(starts)
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            return [_booking(row) for row in await connection.execute(query)]

    async def record_reminders(
        self, reminders: Sequence[tuple[Booking, Email]], now: datetime
    ) -> int:
        queued = 0
        async with self._engine.begin() as connection:
            for booking, email in reminders:
                # Compare-and-set again: only the worker whose UPDATE matches
                # queues the message, so a lesson gets one reminder.
                marked = await connection.execute(
                    update(bookings)
                    .where(
                        bookings.c.id == booking.id,
                        bookings.c.reminded_at.is_(None),
                        bookings.c.status == LessonStatus.CONFIRMED.value,
                    )
                    .values(reminded_at=now)
                )
                if marked.rowcount == 1:
                    await connection.execute(insert(outbox).values(outbox_row(email, now)))
                    queued += 1
        return queued

    async def series(self, tutor_id: UUID) -> list[LessonSeries]:
        query = (
            select(lesson_series)
            .where(lesson_series.c.tutor_id == tutor_id)
            .order_by(lesson_series.c.created_at, lesson_series.c.id)
        )
        async with self._engine.connect() as connection:
            return [_series(row) for row in await connection.execute(query)]

    async def get_series(self, series_id: UUID) -> LessonSeries | None:
        query = select(lesson_series).where(lesson_series.c.id == series_id)
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
            return None if row is None else _series(row)

    async def lessons_of_series(self, series_id: UUID) -> list[Booking]:
        query = (
            select(bookings)
            .where(bookings.c.series_id == series_id)
            .order_by(func.lower(bookings.c.during))
        )
        async with self._engine.connect() as connection:
            return [_booking(row) for row in await connection.execute(query)]

    async def add_series(
        self, series: LessonSeries, lessons: Sequence[Booking], *, skip_conflicts: bool
    ) -> list[Booking]:
        if not lessons:
            return []
        span = TimeRange(
            min(lesson.slot.start for lesson in lessons), max(lesson.slot.end for lesson in lessons)
        )
        try:
            async with self._engine.begin() as connection:
                # Every writer for this tutor is behind this lock, so what is
                # read next cannot change before the inserts below.
                await _queue_behind_other_writers(connection, series.tutor_id)
                busy = [
                    TimeRange(row.during.lower, row.during.upper)
                    for row in await connection.execute(
                        select(bookings.c.during).where(
                            bookings.c.tutor_id == series.tutor_id,
                            _occupies_time,
                            bookings.c.during.overlaps(_range(span)),
                        )
                    )
                ]
                in_the_way = [
                    lesson for lesson in lessons if any(lesson.slot.overlaps(b) for b in busy)
                ]
                if in_the_way and not skip_conflicts:
                    raise SeriesConflictError([lesson.slot for lesson in in_the_way])
                free = [lesson for lesson in lessons if lesson not in in_the_way]
                if not free:
                    return []

                plan = series.plan
                await connection.execute(
                    insert(lesson_series).values(
                        id=series.id,
                        tutor_id=series.tutor_id,
                        student_name=plan.student.name,
                        student_email=plan.student.email,
                        first_day=plan.first_day,
                        start_time=plan.start,
                        weeks=plan.weeks,
                        created_at=series.created_at,
                    )
                )
                await connection.execute(
                    insert(bookings), [_values(lesson, f"series-{lesson.id}") for lesson in free]
                )
                await _enrol(connection, series.tutor_id, plan.student.email, series.created_at)
                return free
        except IntegrityError as error:
            # Not reachable through the lock above, but the constraint is the
            # guarantee and this is what it would say.
            if getattr(error.orig, "sqlstate", None) == _EXCLUSION_VIOLATION:
                raise SeriesConflictError([lesson.slot for lesson in lessons]) from error
            raise


async def _queue_behind_other_writers(connection: AsyncConnection, tutor_id: UUID) -> None:
    # FOR NO KEY UPDATE: the weakest row lock that two writers cannot both hold.
    await connection.execute(
        select(tutors.c.id).where(tutors.c.id == tutor_id).with_for_update(key_share=True)
    )


async def _enrol(connection: AsyncConnection, tutor_id: UUID, email: str, now: datetime) -> None:
    # Someone who is enrolled already stays as they are, id included. The
    # constraint decides, so two requests for a new address leave one student.
    await connection.execute(
        pg_insert(students)
        .values(tutor_id=tutor_id, account=account_key(email), created_at=now)
        .on_conflict_do_nothing(constraint=STUDENTS_ACCOUNT)
    )


def _students_where(*conditions: Any) -> Select[Any]:
    # The name on each student's most recent booking, found through
    # bookings_student_idx. NULL for a student with no booking yet.
    latest_name = (
        select(bookings.c.student_name)
        .where(
            bookings.c.tutor_id == students.c.tutor_id,
            func.lower(bookings.c.student_email) == students.c.account,
        )
        .order_by(bookings.c.created_at.desc(), bookings.c.id)
        .limit(1)
        .scalar_subquery()
    )
    return select(
        students.c.id, students.c.tutor_id, students.c.account, latest_name.label("name")
    ).where(*conditions)


async def _find_student(
    connection: AsyncConnection, tutor_id: UUID, account: str
) -> StudentRecord | None:
    row = (
        await connection.execute(
            _students_where(students.c.tutor_id == tutor_id, students.c.account == account)
        )
    ).one_or_none()
    return None if row is None else _student(row)


def _student(row: Row[Any]) -> StudentRecord:
    return StudentRecord(id=row.id, tutor_id=row.tutor_id, account=row.account, name=row.name)


def _range(time_range: TimeRange) -> Range[Any]:
    return Range(time_range.start, time_range.end, bounds="[)")


def _values(booking: Booking, idempotency_key: str) -> dict[str, Any]:
    cancellation = booking.cancellation
    return {
        "id": booking.id,
        "tutor_id": booking.tutor_id,
        "during": _range(booking.slot),
        "student_name": booking.student.name,
        "student_email": booking.student.email,
        "idempotency_key": idempotency_key,
        "created_at": booking.created_at,
        "status": booking.status.value,
        "cancelled_by": cancellation.by.value if cancellation else None,
        "cancelled_at": cancellation.at if cancellation else None,
        "cancelled_late": cancellation.late if cancellation else None,
        "series_id": booking.series_id,
    }


def _booking(row: Row[Any]) -> Booking:
    return Booking(
        id=row.id,
        tutor_id=row.tutor_id,
        slot=TimeRange(row.during.lower, row.during.upper),
        student=Student(row.student_name, row.student_email),
        created_at=row.created_at,
        status=LessonStatus(row.status),
        cancellation=(
            None
            if row.cancelled_by is None
            else Cancellation(Actor(row.cancelled_by), row.cancelled_at, row.cancelled_late)
        ),
        series_id=row.series_id,
    )


def _series(row: Row[Any]) -> LessonSeries:
    return LessonSeries(
        id=row.id,
        tutor_id=row.tutor_id,
        plan=WeeklySeries(
            first_day=row.first_day,
            start=row.start_time,
            weeks=row.weeks,
            student=Student(row.student_name, row.student_email),
        ),
        created_at=row.created_at,
    )
