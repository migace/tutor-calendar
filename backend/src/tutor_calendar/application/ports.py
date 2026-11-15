"""Interfaces the application needs from the outside world."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from tutor_calendar.domain.scheduling import Booking, TimeRange, Tutor, WeeklyRule


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
        """Times inside or overlapping ``window`` that the tutor's bookings occupy."""
        ...

    async def starting_between(self, tutor_id: UUID, window: TimeRange) -> list[Booking]:
        """The tutor's bookings that start inside ``window``, earliest first."""
        ...

    async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None: ...

    async def add(self, booking: Booking, idempotency_key: str) -> Booking:
        """Store ``booking`` unless that would break one of two guarantees.

        * A tutor's bookings never overlap. If ``booking`` overlaps one that is
          already stored, ``SlotTakenError`` is raised and nothing is stored.
        * A key creates at most one booking per tutor. If the key has been used
          before, nothing is stored and the booking it created is returned, so
          the caller can tell a repeat from a first attempt by comparing ids.

        Both hold when several calls run at the same time, which is the whole
        point: the implementation, not the caller, has to make them atomic.
        """
        ...


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
