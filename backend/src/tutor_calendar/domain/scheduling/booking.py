from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tutor_calendar.domain.scheduling.time_range import TimeRange

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


@dataclass(frozen=True, slots=True)
class Booking:
    """One lesson a student has reserved with a tutor."""

    id: UUID
    tutor_id: UUID
    slot: TimeRange
    student: Student
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
