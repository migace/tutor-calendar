"""The demo tutor, and a command that stores them in the database.

    python -m tutor_calendar.demo

Safe to run repeatedly: an existing demo tutor is left untouched.
"""

from __future__ import annotations

import asyncio
from datetime import time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import create_async_engine

from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.config import Settings
from tutor_calendar.domain.scheduling import Schedule, Tutor, Weekday, WeeklyRule

DEMO_TUTOR_ID = UUID("0b5c1f4e-6f0a-4c59-9a43-6d2f6f0c7d11")


def demo_tutor() -> Tutor:
    afternoons = tuple(
        WeeklyRule(weekday, time(15, 0), time(19, 0))
        for weekday in (Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY)
    )
    saturday_morning = WeeklyRule(Weekday.SATURDAY, time(9, 0), time(13, 0))
    return Tutor(
        id=DEMO_TUTOR_ID,
        slug="demo",
        display_name="Demo Tutor",
        schedule=Schedule(
            timezone=ZoneInfo("Europe/Warsaw"),
            lesson_duration=timedelta(minutes=60),
            rules=(*afternoons, saturday_morning),
        ),
        min_notice=timedelta(hours=12),
    )


async def seed(database_url: str) -> bool:
    """Store the demo tutor. Returns False when they were already there."""
    engine = create_async_engine(database_url)
    try:
        return await PostgresTutorRepository(engine).add_if_absent(demo_tutor())
    finally:
        await engine.dispose()


def main() -> None:
    created = asyncio.run(seed(Settings().database_url))
    print("Demo tutor created." if created else "Demo tutor already exists.")


if __name__ == "__main__":
    main()
