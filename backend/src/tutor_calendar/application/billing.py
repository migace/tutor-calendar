"""Prepaid lesson time: recording what was bought, and showing where it went."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from tutor_calendar.application.errors import (
    InvalidEntryError,
    StatementNotFoundError,
    StudentNotFoundError,
)
from tutor_calendar.application.ports import (
    Clock,
    Ledger,
    StatementLinks,
    StudentDirectory,
    StudentRecord,
    TutorRepository,
)
from tutor_calendar.domain.billing import (
    EntryKind,
    LedgerEntry,
    Statement,
    account_key,
    balance,
    statement_for,
)
from tutor_calendar.domain.scheduling import TimeRange, Tutor, local_day, start_of_day


class RecordEntry:
    """Add time a student bought, or a correction, to their account.

    The caller chooses the id of the entry. Recording the same entry again with
    the same id changes nothing, so a repeated request cannot credit a package
    twice.

    The address is enrolled before anything is filed under it, so whoever has
    an entry also has an id. See ADR 0010.
    """

    def __init__(self, ledger: Ledger, students: StudentDirectory, clock: Clock) -> None:
        self._ledger = ledger
        self._students = students
        self._clock = clock

    async def execute(
        self,
        tutor: Tutor,
        entry_id: UUID,
        student_email: str,
        kind: EntryKind,
        minutes: int,
        note: str,
    ) -> LedgerEntry:
        if kind is EntryKind.LESSON:
            raise InvalidEntryError("charges for lessons are recorded by the system, not by hand")
        now = self._clock.now()
        try:
            entry = LedgerEntry(
                id=entry_id,
                tutor_id=tutor.id,
                account=account_key(student_email),
                kind=kind,
                minutes=minutes,
                note=" ".join(note.split()),
                created_at=now,
                effective_at=now,
            )
        except ValueError as error:
            raise InvalidEntryError(str(error)) from error

        await self._students.enrol(tutor.id, entry.account, now)
        if await self._ledger.post([entry]) == 1:
            return entry
        # The id was there already: a repeat, unless it now means something else.
        earlier = next(
            (
                each
                for each in await self._ledger.entries(tutor.id, entry.account)
                if each.id == entry_id
            ),
            None,
        )
        same = earlier is not None and (earlier.kind, earlier.minutes, earlier.note) == (
            entry.kind,
            entry.minutes,
            entry.note,
        )
        if earlier is None or not same:
            raise InvalidEntryError("this entry id is already used for a different entry")
        return earlier


class FindStudent:
    """One of the tutor's own students, by the id that stands for their address."""

    def __init__(self, students: StudentDirectory) -> None:
        self._students = students

    async def execute(self, tutor: Tutor, student_id: UUID) -> StudentRecord:
        student = await self._students.get_student(student_id)
        # Another tutor's student is reported exactly like one that does not exist.
        if student is None or student.tutor_id != tutor.id:
            raise StudentNotFoundError
        return student


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    email: str
    name: str | None
    # Minutes of lessons paid for and not yet used; negative means time is owed.
    balance: int


class ListAccounts:
    """Every student of a tutor, with what is left of the time they paid for.

    An address that was only ever looked up, with no lesson and no entry, is
    left out: a mistyped address should not stay on the list for ever.
    """

    def __init__(self, ledger: Ledger, students: StudentDirectory) -> None:
        self._ledger = ledger
        self._students = students

    async def execute(self, tutor: Tutor) -> list[Account]:
        balances = await self._ledger.balances(tutor.id)
        accounts = [
            Account(student.id, student.account, student.name, balances.get(student.account, 0))
            for student in await self._students.students(tutor.id)
            if student.name is not None or student.account in balances
        ]
        return sorted(accounts, key=lambda account: (account.name or account.email).casefold())


class OpenAccount:
    """The account for an address, opened first if the tutor has none for it.

    This is how a tutor reaches a student who has not booked anything yet:
    selling a package before the first lesson is common. The address is given
    once, here; from then on the id that comes back stands for it.
    """

    def __init__(self, ledger: Ledger, students: StudentDirectory, clock: Clock) -> None:
        self._ledger = ledger
        self._students = students
        self._clock = clock

    async def execute(self, tutor: Tutor, email: str) -> Account:
        student = await self._students.enrol(tutor.id, account_key(email), self._clock.now())
        entries = await self._ledger.entries(tutor.id, student.account)
        return Account(student.id, student.account, student.name, balance(entries))


@dataclass(frozen=True, slots=True)
class StatementView:
    tutor: Tutor
    account: str
    student_name: str | None
    # First day of the month shown, and of the months either side of it.
    month: date
    previous: date
    next: date
    statement: Statement
    # What is left today, which is the closing balance only for the current month.
    balance_now: int
    # No lesson and no entry, in any month: so far the account is only an address.
    nothing_recorded: bool


def _first_of_month(day: date) -> date:
    return day.replace(day=1)


def _next_month(first: date) -> date:
    return _first_of_month(first + timedelta(days=32))


class ShowStatement:
    """One calendar month of an account, on the tutor's calendar."""

    def __init__(self, ledger: Ledger, students: StudentDirectory, clock: Clock) -> None:
        self._ledger = ledger
        self._students = students
        self._clock = clock

    async def execute(self, tutor: Tutor, student_email: str, month: date | None) -> StatementView:
        tz = tutor.schedule.timezone
        account = account_key(student_email)
        first = _first_of_month(month or local_day(self._clock.now(), tz))
        following = _next_month(first)
        # A month is a local idea: it starts at midnight on the tutor's clock.
        period = TimeRange(start_of_day(first, tz), start_of_day(following, tz))

        student = await self._students.find_student(tutor.id, account)
        if student is None:
            raise StatementNotFoundError
        entries = await self._ledger.entries(tutor.id, account)
        return StatementView(
            tutor=tutor,
            account=account,
            student_name=student.name,
            month=first,
            previous=_first_of_month(first - timedelta(days=1)),
            next=following,
            statement=statement_for(entries, period),
            balance_now=balance(entries),
            # A student has a name from their first booking on.
            nothing_recorded=not entries and student.name is None,
        )


class ShareStatement:
    """Statements for parents: a link that shows one student's account and nothing else."""

    def __init__(self, tutors: TutorRepository, show: ShowStatement, links: StatementLinks) -> None:
        self._tutors = tutors
        self._show = show
        self._links = links

    def token_for(self, tutor: Tutor, student_email: str) -> str:
        return self._links.token_for(tutor.id, account_key(student_email))

    async def view(self, token: str, month: date | None) -> StatementView:
        subject = self._links.account_in(token)
        tutor = None if subject is None else await self._tutors.get_by_id(subject[0])
        if subject is None or tutor is None:
            # One answer for a forged token and for an account that is gone.
            raise StatementNotFoundError
        return await self._show.execute(tutor, subject[1], month)
