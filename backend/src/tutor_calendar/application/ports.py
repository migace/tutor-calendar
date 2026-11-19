"""Interfaces the application needs from the outside world."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from tutor_calendar.domain.billing import LedgerEntry
from tutor_calendar.domain.scheduling import (
    Booking,
    LessonSeries,
    TimeRange,
    Tutor,
    WeeklyRule,
)


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, timezone-aware."""
        ...


class TutorRepository(Protocol):
    async def get_by_slug(self, slug: str) -> Tutor | None: ...

    async def get_by_id(self, tutor_id: UUID) -> Tutor | None: ...

    async def get_by_email(self, email: str) -> Tutor | None:
        """Look a tutor up by address, ignoring case."""
        ...

    async def replace_weekly_hours(self, tutor_id: UUID, rules: tuple[WeeklyRule, ...]) -> None:
        """Swap all of a tutor's weekly rules for ``rules``, as one change."""
        ...


class BookingRepository(Protocol):
    async def busy_between(self, tutor_id: UUID, window: TimeRange) -> list[TimeRange]:
        """Times inside or overlapping ``window`` that the tutor's lessons occupy.

        Cancelled lessons occupy nothing.
        """
        ...

    async def starting_between(self, tutor_id: UUID, window: TimeRange) -> list[Booking]:
        """The tutor's lessons that start inside ``window``, earliest first.

        Includes cancelled ones: a tutor wants to see what was called off.
        """
        ...

    async def get(self, booking_id: UUID) -> Booking | None: ...

    async def apply(self, changes: Sequence[tuple[Booking, Booking]]) -> int:
        """Store new states of lessons, each given as (before, after).

        A change is applied only if the stored lesson still has the status it
        had in ``before``, so two people acting on one lesson at the same time
        cannot both win. Returns how many changes were applied; all of them
        happen together or, on an error, none.
        """
        ...

    async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None: ...

    async def add(
        self, booking: Booking, idempotency_key: str, confirmation: Email | None = None
    ) -> Booking:
        """Store ``booking`` unless that would break one of two guarantees.

        * A tutor's bookings never overlap. If ``booking`` overlaps one that is
          already stored, ``SlotTakenError`` is raised and nothing is stored.
        * A key creates at most one booking per tutor. If the key has been used
          before, nothing is stored and the booking it created is returned, so
          the caller can tell a repeat from a first attempt by comparing ids.

        Both hold when several calls run at the same time, which is the whole
        point: the implementation, not the caller, has to make them atomic.

        ``confirmation`` is queued for sending as part of the same change: it
        is queued if and only if the booking is stored. See ADR 0007.

        The student is enrolled in the ``StudentDirectory`` as part of the same
        change too, so nobody has a lesson without an id. See ADR 0010.
        """
        ...


class SeriesRepository(Protocol):
    """Weekly series and the lessons laid out from them. See ADR 0006."""

    async def series(self, tutor_id: UUID) -> list[LessonSeries]:
        """The tutor's weekly series, oldest first."""
        ...

    async def get_series(self, series_id: UUID) -> LessonSeries | None: ...

    async def lessons_of_series(self, series_id: UUID) -> list[Booking]:
        """Every lesson of a series, cancelled ones included, earliest first."""
        ...

    async def add_series(
        self, series: LessonSeries, lessons: Sequence[Booking], *, skip_conflicts: bool
    ) -> list[Booking]:
        """Store a series and its lessons as one change, and return those stored.

        A lesson that overlaps one already booked is left out when
        ``skip_conflicts`` is set. Otherwise nothing at all is stored and
        ``SeriesConflictError`` names the days in the way.

        If anything is stored, the student is enrolled with it, as in ``add``.
        """
        ...


@dataclass(frozen=True, slots=True)
class StudentRecord:
    """A student as the directory knows them."""

    # Stands for the address wherever the address must not appear. See ADR 0010.
    id: UUID
    tutor_id: UUID
    # The address in lower case: what bookings and the ledger file the student under.
    account: str
    # The name on the student's latest booking. None until they have one.
    name: str | None


class StudentDirectory(Protocol):
    """Who a tutor teaches, each under an id that is safe to put in an address.

    A student is in the directory from their first booking: ``add`` and
    ``add_series`` enrol them as part of storing the lesson. A tutor can also
    enrol an address by hand, before any lesson. See ADR 0010.
    """

    async def students(self, tutor_id: UUID) -> list[StudentRecord]:
        """Everyone the tutor has enrolled or taught, in no particular order."""
        ...

    async def get_student(self, student_id: UUID) -> StudentRecord | None: ...

    async def find_student(self, tutor_id: UUID, account: str) -> StudentRecord | None:
        """The tutor's student with this address, if they have one."""
        ...

    async def enrol(self, tutor_id: UUID, account: str, now: datetime) -> StudentRecord:
        """The tutor's student with this address, added first if there was none.

        Enrolling the same address twice, even at the same moment, leaves one
        student, and both callers get that one.
        """
        ...


class SettlementQueue(Protocol):
    """Lessons waiting to be charged, for the worker. See ADR 0007."""

    async def awaiting_settlement(self, now: datetime, limit: int) -> list[Booking]:
        """Lessons whose cost is final (see ``is_settled``) and not yet marked as settled."""
        ...

    async def mark_settled(self, booking_ids: Sequence[UUID], now: datetime) -> None: ...

    async def count_awaiting_settlement(self, now: datetime) -> int:
        """How many lessons ``awaiting_settlement`` would return if it had no limit."""
        ...


class ReminderQueue(Protocol):
    """Lessons waiting for a reminder, for the worker."""

    async def due_for_reminder(self, now: datetime, lead: timedelta, limit: int) -> list[Booking]:
        """Confirmed lessons starting within ``lead`` that have had no reminder.

        Lessons booked less than ``lead`` before they start are left out: the
        confirmation they just received is reminder enough.
        """
        ...

    async def record_reminders(
        self, reminders: Sequence[tuple[Booking, Email]], now: datetime
    ) -> int:
        """Queue each reminder and mark its lesson as reminded, as one change.

        A lesson that was reminded or changed in the meantime is skipped, so a
        lesson gets one reminder however many workers run. Returns how many
        were queued.
        """
        ...


class LessonStore(
    BookingRepository,
    SeriesRepository,
    StudentDirectory,
    SettlementQueue,
    ReminderQueue,
    Protocol,
):
    """The five ports for lessons, at once.

    Lessons live in one table, so one object fills all five roles. Only the
    composition root asks for the whole of it; a use case names the one role
    it needs, and cannot reach the rest.
    """


class CredentialStore(Protocol):
    """Sign-in links and sessions, kept as digests of the secrets handed out.

    The secrets themselves are never stored, so a copy of the database is not
    enough to sign in as anyone.
    """

    async def add_sign_in_token(
        self, digest: str, tutor_id: UUID, expires_at: datetime
    ) -> None: ...

    async def redeem_sign_in_token(self, digest: str, now: datetime) -> UUID | None:
        """Use a sign-in token up and say whose it was.

        Returns None for a token that is unknown, expired or already used. A
        token can be redeemed once, even if two requests try at the same time.
        """
        ...

    async def add_session(self, digest: str, tutor_id: UUID, expires_at: datetime) -> None: ...

    async def tutor_for_session(self, digest: str, now: datetime) -> UUID | None:
        """Whose session this is, or None if it is unknown or has expired."""
        ...

    async def remove_session(self, digest: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Email:
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    async def send(self, email: Email) -> None: ...


class ManageLinks(Protocol):
    """Unforgeable tokens that let a student manage one booking without an account."""

    def token_for(self, booking_id: UUID) -> str: ...

    def booking_id_in(self, token: str) -> UUID | None:
        """The booking a token was issued for, or None if it was not issued by us."""
        ...


class StatementLinks(Protocol):
    """Unforgeable tokens that let a parent read one student's statement."""

    def token_for(self, tutor_id: UUID, account: str) -> str: ...

    def account_in(self, token: str) -> tuple[UUID, str] | None:
        """The tutor and account a token was issued for, or None if we did not issue it."""
        ...


class Ledger(Protocol):
    """An append-only record of lesson time bought and used. See ADR 0007."""

    async def post(self, entries: Sequence[LedgerEntry]) -> int:
        """Add entries and return how many were new.

        An entry whose id is already recorded, or that charges a lesson already
        charged, is skipped. Posting the same thing twice is therefore harmless.
        """
        ...

    async def entries(self, tutor_id: UUID, account: str) -> list[LedgerEntry]:
        """One account's whole history, in the order it took effect."""
        ...

    async def balances(self, tutor_id: UUID) -> dict[str, int]:
        """Minutes left on each of the tutor's accounts that has any entry."""
        ...


@dataclass(frozen=True, slots=True)
class Delivery:
    sent: int
    failed: int


@dataclass(frozen=True, slots=True)
class OutboxBacklog:
    waiting: int
    # When the oldest of them was queued. None when nothing is waiting.
    oldest_queued_at: datetime | None


class Outbox(Protocol):
    """E-mail waiting to be sent. See ADR 0007."""

    async def add(self, email: Email, now: datetime) -> None: ...

    async def deliver_due(
        self, now: datetime, send: Callable[[Email], Awaitable[None]], limit: int
    ) -> Delivery:
        """Hand each waiting message to ``send`` and record how it went.

        A message whose send raises stays queued and is tried again later, with
        a growing pause. Two workers never take the same message at once. A
        message can be sent twice if a worker dies after sending and before
        recording it: delivery is at least once, not exactly once.
        """
        ...

    async def backlog(self) -> OutboxBacklog:
        """How many messages have not been sent, and how long the oldest has waited.

        Every unsent message counts, also one whose send failed and that is
        pausing before its next try: its age is counted from when it was first
        queued, so a message that keeps failing keeps growing older.
        """
        ...


class JobLog(Protocol):
    """When each background job last finished without an error. See ADR 0011.

    The worker writes it and the web process reads it, which is how one process
    can say whether another is still doing its work.
    """

    async def record_success(self, job: str, at: datetime) -> None:
        """Note that ``job`` finished at ``at``.

        The record only moves forwards: with several workers, a slow one that
        reports late does not put the time back.
        """
        ...

    async def last_successes(self) -> dict[str, datetime]:
        """The latest recorded finish of every job that has ever finished."""
        ...
