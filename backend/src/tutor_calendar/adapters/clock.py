from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock that stands still. For tests and for reproducible demos."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("instant must be timezone-aware")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant
