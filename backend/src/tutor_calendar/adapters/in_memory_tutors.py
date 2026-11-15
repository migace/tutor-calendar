"""In-memory tutor repository: the fake that fast tests use instead of PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from tutor_calendar.domain.scheduling import Tutor, WeeklyRule


class InMemoryTutorRepository:
    def __init__(self, tutors: Iterable[Tutor] = ()) -> None:
        self._by_id = {tutor.id: tutor for tutor in tutors}

    async def get_by_slug(self, slug: str) -> Tutor | None:
        return next((tutor for tutor in self._by_id.values() if tutor.slug == slug), None)

    async def get_by_id(self, tutor_id: UUID) -> Tutor | None:
        return self._by_id.get(tutor_id)

    async def get_by_email(self, email: str) -> Tutor | None:
        wanted = email.strip().lower()
        return next(
            (tutor for tutor in self._by_id.values() if tutor.email.lower() == wanted), None
        )

    async def replace_weekly_hours(self, tutor_id: UUID, rules: tuple[WeeklyRule, ...]) -> None:
        self._by_id[tutor_id] = self._by_id[tutor_id].with_weekly_hours(rules)
