"""The demo tutor, and a command that stores them in the database.

    python -m tutor_calendar.demo            the demo tutor; in demo mode, activity too
    python -m tutor_calendar.demo --reset    demo mode only: wipe all activity and start over

Safe to run repeatedly: what is already there is left untouched.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_calendar.adapters.clock import SystemClock
from tutor_calendar.adapters.postgres.billing import PostgresLedger
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.config import Settings
from tutor_calendar.demo_activity import populate
from tutor_calendar.domain.scheduling import Schedule, Tutor, Weekday, WeeklyRule

DEMO_TUTOR_ID = UUID("0b5c1f4e-6f0a-4c59-9a43-6d2f6f0c7d11")
DEMO_SLUG = "demo"


def demo_tutor() -> Tutor:
    afternoons = tuple(
        WeeklyRule(weekday, time(15, 0), time(19, 0))
        for weekday in (Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY)
    )
    saturday_morning = WeeklyRule(Weekday.SATURDAY, time(9, 0), time(13, 0))
    return Tutor(
        id=DEMO_TUTOR_ID,
        slug=DEMO_SLUG,
        display_name="Demo Tutor",
        email="demo@example.com",
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


async def wipe_activity(engine: AsyncEngine) -> None:
    """Remove every lesson, account entry, queued message and session. Tutors stay.

    The ledger refuses to have rows changed or deleted; emptying the table is
    the one thing its owner can still do, and a demo is the one place for it.
    """
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE bookings, lesson_series, ledger_entries, students, outbox,"
                " sign_in_tokens, sessions"
            )
        )
        # Whatever visitors changed in the demo tutor's hours goes too.
        await connection.execute(text("DELETE FROM tutors WHERE slug = :slug"), {"slug": DEMO_SLUG})


async def run(settings: Settings, *, reset: bool) -> list[str]:
    """Do what the command line asked, and say what was done."""
    done: list[str] = []
    engine = create_async_engine(settings.database_url)
    try:
        if reset:
            if not settings.demo_mode:
                raise SystemExit("--reset wipes all activity and is only allowed in demo mode.")
            await wipe_activity(engine)
            done.append("Activity wiped.")
        created = await PostgresTutorRepository(engine).add_if_absent(demo_tutor())
        done.append("Demo tutor created." if created else "Demo tutor already exists.")
        if settings.demo_mode:
            populated = await populate(
                demo_tutor(),
                PostgresBookingRepository(engine),
                PostgresLedger(engine),
                SystemClock().now(),
            )
            done.append("Demo activity added." if populated else "Demo activity already exists.")
    finally:
        await engine.dispose()
    return done


def main() -> None:
    for line in asyncio.run(run(Settings(), reset="--reset" in sys.argv[1:])):
        print(line)


if __name__ == "__main__":
    main()
