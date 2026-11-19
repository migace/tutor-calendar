"""Fixtures shared by every kind of test.

Tests that need PostgreSQL get a database of their own, ``<name>_test``, next
to the one the application is configured for, so running the suite never
touches development data. It is created and migrated once per run. Locally the
tests that need it are skipped when no server answers; in CI that is a failure.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_calendar.config import Settings

BACKEND = Path(__file__).parents[1]

# The tests send hundreds of requests from one address. The limits have tests
# of their own, which turn them back on.
os.environ.setdefault("TC_RATE_LIMITS", "false")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


def alembic_config(database_url: str) -> Config:
    # No ini file: Alembic would reconfigure logging from it in the middle of a test run.
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _create_database_if_missing(server_url: str, name: str) -> None:
    engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of an empty, fully migrated test database."""
    configured = make_url(Settings().database_url)
    name = f"{configured.database}_test"
    url = configured.set(database=name).render_as_string(hide_password=False)
    try:
        asyncio.run(
            _create_database_if_missing(configured.render_as_string(hide_password=False), name)
        )
    except Exception as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL is not reachable: {error!r}")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine on the test database, with every table emptied first."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE tutors, bookings, lesson_series, ledger_entries, students, outbox,"
                " background_jobs CASCADE"
            )
        )
    try:
        yield engine
    finally:
        await engine.dispose()
