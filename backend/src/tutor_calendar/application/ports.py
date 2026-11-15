"""Interfaces the application needs from the outside world."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from tutor_calendar.domain.scheduling import Tutor


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, timezone-aware."""
        ...


class TutorRepository(Protocol):
    async def get_by_slug(self, slug: str) -> Tutor | None: ...
