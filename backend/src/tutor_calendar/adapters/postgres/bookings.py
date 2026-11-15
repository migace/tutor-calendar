from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.adapters.postgres.tables import BOOKINGS_IDEMPOTENCY_KEY, bookings, tutors
from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.domain.scheduling import Booking, Student, TimeRange

# https://www.postgresql.org/docs/current/errcodes-appendix.html
_EXCLUSION_VIOLATION = "23P01"


class PostgresBookingRepository:
    """Bookings in PostgreSQL.

    Both guarantees of the port are enforced by constraints, so they hold no
    matter how many requests, processes or servers write at the same time.
    Nothing here reads before it writes in order to decide.

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
            .where(bookings.c.tutor_id == tutor_id, bookings.c.during.overlaps(_range(window)))
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

    async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None:
        query = select(bookings).where(
            bookings.c.tutor_id == tutor_id, bookings.c.idempotency_key == key
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).one_or_none()
            return None if row is None else _booking(row)

    async def add(self, booking: Booking, idempotency_key: str) -> Booking:
        # FOR NO KEY UPDATE: the weakest row lock that two writers cannot both hold.
        queue_behind_other_writers = (
            select(tutors.c.id)
            .where(tutors.c.id == booking.tutor_id)
            .with_for_update(key_share=True)
        )
        # A repeated key is not an error but "do nothing"; an overlap is an
        # error raised by the exclusion constraint.
        insert_booking = (
            pg_insert(bookings)
            .values(
                id=booking.id,
                tutor_id=booking.tutor_id,
                during=_range(booking.slot),
                student_name=booking.student.name,
                student_email=booking.student.email,
                idempotency_key=idempotency_key,
                created_at=booking.created_at,
            )
            .on_conflict_do_nothing(constraint=BOOKINGS_IDEMPOTENCY_KEY)
            .returning(bookings.c.id)
        )
        try:
            async with self._engine.begin() as connection:
                await connection.execute(queue_behind_other_writers)
                inserted = (await connection.execute(insert_booking)).one_or_none()
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


def _range(time_range: TimeRange) -> Range[Any]:
    return Range(time_range.start, time_range.end, bounds="[)")


def _booking(row: Row[Any]) -> Booking:
    return Booking(
        id=row.id,
        tutor_id=row.tutor_id,
        slot=TimeRange(row.during.lower, row.during.upper),
        student=Student(row.student_name, row.student_email),
        created_at=row.created_at,
    )
