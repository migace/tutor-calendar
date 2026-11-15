"""In-memory tutor repository.

Stands in for the PostgreSQL adapter until tutors are persisted; afterwards it
stays as the fake used by fast tests.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from tutor_calendar.domain.scheduling import Schedule, Tutor, Weekday, WeeklyRule


class InMemoryTutorRepository:
    def __init__(self, tutors: Iterable[Tutor] = ()) -> None:
        self._by_slug = {tutor.slug: tutor for tutor in tutors}

    async def get_by_slug(self, slug: str) -> Tutor | None:
        return self._by_slug.get(slug)


def demo_tutor() -> Tutor:
    afternoons = tuple(
        WeeklyRule(weekday, time(15, 0), time(19, 0))
        for weekday in (Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY)
    )
    saturday_morning = WeeklyRule(Weekday.SATURDAY, time(9, 0), time(13, 0))
    return Tutor(
        slug="demo",
        display_name="Demo Tutor",
        schedule=Schedule(
            timezone=ZoneInfo("Europe/Warsaw"),
            lesson_duration=timedelta(minutes=60),
            rules=(*afternoons, saturday_morning),
        ),
        min_notice=timedelta(hours=12),
    )
