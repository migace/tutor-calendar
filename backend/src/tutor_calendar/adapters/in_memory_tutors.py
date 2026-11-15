"""In-memory tutor repository: the fake that fast tests use instead of PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable

from tutor_calendar.domain.scheduling import Tutor


class InMemoryTutorRepository:
    def __init__(self, tutors: Iterable[Tutor] = ()) -> None:
        self._by_slug = {tutor.slug: tutor for tutor in tutors}

    async def get_by_slug(self, slug: str) -> Tutor | None:
        return self._by_slug.get(slug)
