"""Prepaid lesson time, kept as a ledger.

A student's balance is never stored. It is the sum of entries that are only
ever added: time bought, time used by lessons, and corrections. A mistake is
fixed by adding an entry that says so, not by changing an old one, so the
history a parent was shown last month is the history that is shown today.

Time is counted in whole minutes. Lessons differ in length from tutor to
tutor, and "ten lessons" stops meaning anything the day a tutor changes theirs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid5

from tutor_calendar.domain.scheduling.booking import Booking, LessonStatus
from tutor_calendar.domain.scheduling.time_range import TimeRange

MAX_NOTE_LENGTH = 200
# More than a year of daily two-hour lessons: a typo guard, not a business rule.
MAX_MINUTES_PER_ENTRY = 60_000


class EntryKind(StrEnum):
    PURCHASE = "purchase"
    LESSON = "lesson"
    ADJUSTMENT = "adjustment"


def account_key(email: str) -> str:
    """How a student is identified in the ledger: their address, ignoring case."""
    return email.strip().lower()


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: UUID
    tutor_id: UUID
    # The student's address in lower case. See ``account_key``.
    account: str
    kind: EntryKind
    # Positive adds time to the balance, negative uses it up.
    minutes: int
    note: str
    created_at: datetime
    # When the entry counts on a statement. For a lesson that is the start of
    # the lesson, which can be long before the charge was recorded.
    effective_at: datetime
    # The lesson a charge is for. At most one entry exists per lesson.
    booking_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.account != account_key(self.account) or "@" not in self.account:
            raise ValueError("a ledger account is a lower-case e-mail address")
        if self.minutes == 0 or abs(self.minutes) > MAX_MINUTES_PER_ENTRY:
            raise ValueError("an entry moves between 1 and 60000 minutes")
        if len(self.note) > MAX_NOTE_LENGTH:
            raise ValueError(f"a note cannot be longer than {MAX_NOTE_LENGTH} characters")
        if self.created_at.tzinfo is None or self.effective_at.tzinfo is None:
            raise ValueError("entry times must be timezone-aware")
        if self.kind is EntryKind.PURCHASE and self.minutes < 0:
            raise ValueError("a purchase adds time")
        if (self.kind is EntryKind.LESSON) != (self.booking_id is not None):
            raise ValueError("an entry names a lesson exactly when it is a charge for one")
        if self.kind is EntryKind.LESSON and self.minutes > 0:
            raise ValueError("a lesson uses time up")
        if self.kind is EntryKind.ADJUSTMENT and not self.note.strip():
            raise ValueError("an adjustment has to say why")


def is_settled(lesson: Booking, now: datetime) -> bool:
    """Whether what the lesson costs can no longer change.

    A confirmed lesson might still be cancelled until it is over; everything
    else is final the moment it happens.
    """
    return lesson.status is not LessonStatus.CONFIRMED or lesson.slot.end <= now


def charge_for(lesson: Booking, now: datetime) -> LedgerEntry | None:
    """The ledger entry a settled lesson calls for, or None if it costs nothing."""
    if not is_settled(lesson, now):
        raise ValueError("a lesson that can still change cannot be charged yet")
    if not lesson.is_charged:
        return None
    if lesson.status is LessonStatus.NO_SHOW:
        note = "Missed lesson"
    elif lesson.status is LessonStatus.CANCELLED:
        note = "Lesson cancelled late"
    else:
        note = "Lesson"
    return LedgerEntry(
        # Derived from the lesson, so charging twice produces the same entry
        # twice, which a store can recognise and keep once.
        id=uuid5(lesson.id, "charge"),
        tutor_id=lesson.tutor_id,
        account=account_key(lesson.student.email),
        kind=EntryKind.LESSON,
        minutes=-(lesson.slot.duration // timedelta(minutes=1)),
        note=note,
        created_at=now,
        effective_at=lesson.slot.start,
        booking_id=lesson.id,
    )


def balance(entries: Iterable[LedgerEntry]) -> int:
    """Minutes of lessons paid for and not yet used. Negative means time is owed."""
    return sum(entry.minutes for entry in entries)


@dataclass(frozen=True, slots=True)
class Statement:
    """What happened on one account during a period, and where it started and ended."""

    period: TimeRange
    opening: int
    entries: tuple[LedgerEntry, ...]

    @property
    def closing(self) -> int:
        return self.opening + balance(self.entries)


def statement_for(entries: Sequence[LedgerEntry], period: TimeRange) -> Statement:
    """Split an account's history at a period: what came before it, and what fell inside.

    Entries are placed by when they take effect, so a lesson held in November
    is on November's statement even if it was charged in December.
    """
    before = [entry for entry in entries if entry.effective_at < period.start]
    during = sorted(
        (entry for entry in entries if period.start <= entry.effective_at < period.end),
        key=lambda entry: (entry.effective_at, entry.created_at),
    )
    return Statement(period, balance(before), tuple(during))
