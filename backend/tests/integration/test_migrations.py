"""Migrations as a deployment runs them: several copies of the application at once."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.conftest import BACKEND

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

REPLICAS = 4


@pytest.fixture
async def empty_database_url(database_url: str) -> AsyncIterator[str]:
    """A database with nothing in it, not even the table that records migrations."""
    test_database = make_url(database_url)
    name = f"{test_database.database}_migrations"
    server = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with server.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield test_database.set(database=name).render_as_string(hide_password=False)
        async with server.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await server.dispose()


@pytest.fixture
async def empty_database(empty_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(empty_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _migrate(database_url: str, revision: str = "head") -> tuple[int | None, str]:
    """Run the migrations the way a starting container does: as its own process."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        revision,
        cwd=BACKEND,
        env={**os.environ, "TC_DATABASE_URL": database_url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    return process.returncode, output.decode(errors="replace")


async def test_replicas_starting_together_all_migrate_cleanly(
    empty_database_url: str, empty_database: AsyncEngine
) -> None:
    # The image migrates when it starts, so replicas started together all run
    # ``alembic upgrade head`` against the same empty database. Without the
    # lock in migrations/env.py each reads "nothing applied yet" and they
    # collide creating the same tables.
    results = await asyncio.gather(*(_migrate(empty_database_url) for _ in range(REPLICAS)))

    failed = [output for code, output in results if code != 0]
    assert not failed, failed[0]

    async with empty_database.connect() as connection:
        versions = (await connection.execute(text("SELECT version_num FROM alembic_version"))).all()
        bookings = await connection.scalar(text("SELECT to_regclass('public.bookings')"))
    # One row: the schema was built once and every replica agrees on where it stands.
    assert len(versions) == 1
    assert bookings is not None
