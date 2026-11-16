"""The demo command against a real PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.adapters.postgres.billing import PostgresLedger
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor, run

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as connection:
        return {
            table: int(await connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0)
            for table in ("tutors", "bookings", "lesson_series", "ledger_entries", "outbox")
        }


async def test_outside_demo_mode_only_the_tutor_is_stored(
    engine: AsyncEngine, database_url: str
) -> None:
    done = await run(Settings(database_url=database_url, demo_mode=False), reset=False)

    assert done == ["Demo tutor created."]
    assert await counts(engine) == {
        "tutors": 1,
        "bookings": 0,
        "lesson_series": 0,
        "ledger_entries": 0,
        "outbox": 0,
    }


async def test_in_demo_mode_the_calendar_and_the_accounts_are_filled_once(
    engine: AsyncEngine, database_url: str
) -> None:
    demo = Settings(database_url=database_url, demo_mode=True)

    first = await run(demo, reset=False)
    after_first = await counts(engine)
    again = await run(demo, reset=False)

    assert first == ["Demo tutor created.", "Demo activity added."]
    assert again == ["Demo tutor already exists.", "Demo activity already exists."]
    assert await counts(engine) == after_first
    assert after_first["lesson_series"] == 2
    assert after_first["bookings"] >= 14
    # Seeding sends nobody an e-mail.
    assert after_first["outbox"] == 0
    balances = await PostgresLedger(engine).balances(demo_tutor().id)
    assert balances["olek.wojcik@example.com"] == 300
    assert balances["zofia.maj@example.com"] == -120


async def test_a_reset_undoes_what_visitors_did(engine: AsyncEngine, database_url: str) -> None:
    demo = Settings(database_url=database_url, demo_mode=True)
    await run(demo, reset=False)
    fresh = await counts(engine)
    # A visitor clears the tutor's hours and leaves a session behind.
    tutors = PostgresTutorRepository(engine)
    await tutors.replace_weekly_hours(demo_tutor().id, ())
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO sessions (digest, tutor_id, expires_at) VALUES ('x', :id, now())"),
            {"id": demo_tutor().id},
        )

    done = await run(demo, reset=True)

    assert done == ["Activity wiped.", "Demo tutor created.", "Demo activity added."]
    assert await counts(engine) == fresh
    assert await tutors.get_by_slug("demo") == demo_tutor()
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM sessions")) == 0


async def test_a_reset_is_refused_outside_demo_mode(engine: AsyncEngine, database_url: str) -> None:
    demo = Settings(database_url=database_url, demo_mode=True)
    await run(demo, reset=False)
    before = await counts(engine)

    with pytest.raises(SystemExit, match="only allowed in demo mode"):
        await run(Settings(database_url=database_url, demo_mode=False), reset=True)

    assert await counts(engine) == before
