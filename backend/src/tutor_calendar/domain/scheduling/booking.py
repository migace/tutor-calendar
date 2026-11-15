"""A booked lesson and the few things that can happen to it.

    confirmed ──cancel──▶ cancelled
        │
        └──mark no-show──▶ no-show

Both arrows lead to states nothing leaves. A lesson that simply took place is
not a state of its own: it is a confirmed lesson whose time has passed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from tutor_calendar.domain.scheduling.time_range import TimeRange

if TYPE_CHECKING:
    from tutor_calendar.domain.scheduling.cancellation import CancellationPolicy

MAX_NAME_LENGTH = 120
# The longest address SMTP can deliver to (RFC 5321).
MAX_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class Student:
    """Who the lesson is for and where to reach them."""

    name: str
    email: str

    def __post_init__(self) -> None:
        name = " ".join(self.name.split())
        email = self.email.strip()
        if not name:
            raise ValueError("student name cannot be blank")
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"student name cannot be longer than {MAX_NAME_LENGTH} characters")
        # Syntax is checked properly at the edge of the system. This only keeps
        # values that could never be an address out of the domain.
        local, at, host = email.rpartition("@")
        if not (at and local and host) or any(character.isspace() for character in email):
            raise ValueError("student email is not an address")
        if len(email) > MAX_EMAIL_LENGTH:
            raise ValueError(f"student email cannot be longer than {MAX_EMAIL_LENGTH} characters")
        object.__setattr__(self, "name", name)
        # Only the host part is case-insensitive by specification.
        object.__setattr__(self, "email", f"{local}@{host.lower()}")


class LessonStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class Actor(StrEnum):
    """Who did something to a lesson."""

    STUDENT = "student"
    TUTOR = "tutor"


class LessonTransitionError(Exception):
    """Something was asked of a lesson that its current state does not allow."""


@dataclass(frozen=True, slots=True)
class Cancellation:
    by: Actor
    at: datetime
    # Cancelled after the tutor's free-cancellation deadline. The lesson is
    # still paid for, which is what the deadline is for.
    late: bool


@dataclass(frozen=True, slots=True)
class Booking:
    """One lesson a student has reserved with a tutor."""

    id: UUID
    tutor_id: UUID
    slot: TimeRange
    student: Student
    created_at: datetime
    status: LessonStatus = LessonStatus.CONFIRMED
    cancellation: Cancellation | None = None
    # Set when the lesson is one occurrence of a weekly series.
    series_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if (self.status is LessonStatus.CANCELLED) != (self.cancellation is not None):
            raise ValueError("a lesson has cancellation details exactly when it is cancelled")

    @property
    def occupies_time(self) -> bool:
        """Whether the tutor is (or was) busy during this lesson's slot."""
        return self.status is not LessonStatus.CANCELLED

    @property
    def is_charged(self) -> bool:
        """Whether the student owes for this lesson, whether or not it took place."""
        if self.cancellation is not None:
            return self.cancellation.late
        return True

    def cancel(self, by: Actor, at: datetime, policy: CancellationPolicy) -> Booking:
        """Cancel the lesson. ``policy`` decides whether it is still charged."""
        self._require_confirmed("cancelled")
        if at >= self.slot.start:
            raise LessonTransitionError("a lesson that has started can no longer be cancelled")
        late = policy.is_late(self, by, at)
        return replace(self, status=LessonStatus.CANCELLED, cancellation=Cancellation(by, at, late))

    def mark_no_show(self, at: datetime) -> Booking:
        """Record that the student did not turn up. Only possible once the lesson has begun."""
        self._require_confirmed("marked as a no-show")
        if at < self.slot.start:
            raise LessonTransitionError("a lesson that has not started cannot be a no-show")
        return replace(self, status=LessonStatus.NO_SHOW)

    def _require_confirmed(self, verb: str) -> None:
        if self.status is not LessonStatus.CONFIRMED:
            state = self.status.value.replace("_", "-")
            raise LessonTransitionError(f"a {state} lesson cannot be {verb}")
