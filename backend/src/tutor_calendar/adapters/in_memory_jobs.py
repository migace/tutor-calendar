"""In-memory job log: the fake that fast tests use instead of PostgreSQL."""

from __future__ import annotations

from datetime import datetime


class InMemoryJobLog:
    def __init__(self) -> None:
        self._last: dict[str, datetime] = {}

    async def record_success(self, job: str, at: datetime) -> None:
        self._last[job] = max(at, self._last.get(job, at))

    async def last_successes(self) -> dict[str, datetime]:
        return dict(self._last)
