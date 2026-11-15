"""Interfaces the application needs from the outside world."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from tutor_calendar.domain.scheduling import Booking, TimeRange, Tutor


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, timezone-aware."""
        ...


class TutorRepository(Protocol):
    async def get_by_slug(self, slug: str) -> Tutor | None: ...


class BookingRepository(Protocol):
    async def busy_between(self, tutor_id: UUID, window: TimeRange) -> list[TimeRange]:
        """Times inside or overlapping ``window`` that the tutor's bookings occupy."""
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
