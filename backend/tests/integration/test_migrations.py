"""Migrations as a deployment runs them: several at once, and over data that is already there."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.conftest import BACKEND
from tests.factories import FIRST_SLOT

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

REPLICAS = 4
DAY = timedelta(days=1)


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


def _enrol_everyone_known() -> str:
    """The statement migration 0006 enrols existing students with."""
    path = BACKEND / "migrations" / "versions" / "0006_students.py"
    spec = importlib.util.spec_from_file_location("migration_0006", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statement: str = module.ENROL_EVERYONE_KNOWN
    return statement


async def test_students_who_were_there_before_ids_existed_each_get_one(
    empty_database_url: str, empty_database: AsyncEngine
) -> None:
    # The database as it was before students had ids (migration 0005), with
    # the three ways someone can be known: lessons, a package, and both.
    code, output = await _migrate(empty_database_url, "0005")
    assert code == 0, output
    ewa, jan = uuid4(), uuid4()
    async with empty_database.begin() as connection:
        for tutor_id, slug in ((ewa, "ewa"), (jan, "jan")):
            await connection.execute(
                text(
                    "INSERT INTO tutors (id, slug, display_name, email, timezone,"
                    " lesson_minutes, min_notice_minutes)"
                    " VALUES (:id, :slug, :slug, :slug || '@example.com', 'Europe/Warsaw', 60, 0)"
                ),
                {"id": tutor_id, "slug": slug},
            )
        lessons = [
            (ewa, "Ania", "Anna@Example.com", FIRST_SLOT),
            (ewa, "Anna Nowak", "anna@example.com", FIRST_SLOT + 7 * DAY),
            (ewa, "Bartek Lis", "bartek@example.com", FIRST_SLOT + DAY),
            (jan, "Anna Nowak", "anna@example.com", FIRST_SLOT),
        ]
        for tutor_id, name, email, start in lessons:
            await connection.execute(
                text(
                    "INSERT INTO bookings (id, tutor_id, during, student_name, student_email,"
                    " idempotency_key, created_at, status)"
                    " VALUES (gen_random_uuid(), :tutor, tstzrange(:start, :end), :name, :email,"
                    " gen_random_uuid()::text, now(), 'confirmed')"
                ),
                {
                    "tutor": tutor_id,
                    "name": name,
                    "email": email,
                    "start": start,
                    "end": start + timedelta(hours=1),
                },
            )
        for account in ("bartek@example.com", "zofia@example.com"):
            await connection.execute(
                text(
                    "INSERT INTO ledger_entries (id, tutor_id, account, kind, minutes, note,"
                    " created_at, effective_at)"
                    " VALUES (gen_random_uuid(), :tutor, :account, 'purchase', 600, '',"
                    " now(), now())"
                ),
                {"tutor": ewa, "account": account},
            )

    code, output = await _migrate(empty_database_url)
    assert code == 0, output

    async def enrolled() -> list[tuple[str, str, str]]:
        async with empty_database.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT tutors.slug, students.account, students.id::text"
                    " FROM students JOIN tutors ON tutors.id = students.tutor_id"
                    " ORDER BY tutors.slug, students.account"
                )
            )
            return [(row.slug, row.account, row.id) for row in rows]

    students = await enrolled()
    # Anna booked under two spellings of one address and is one student. Zofia
    # only ever bought a package. Jan's Anna is somebody else's student.
    assert [(slug, account) for slug, account, _ in students] == [
        ("ewa", "anna@example.com"),
        ("ewa", "bartek@example.com"),
        ("ewa", "zofia@example.com"),
        ("jan", "anna@example.com"),
    ]
    assert len({student_id for _, _, student_id in students}) == 4

    # Run again, as after a deployment during which the old version kept taking
    # bookings: nobody is enrolled twice and nobody's id changes.
    async with empty_database.begin() as connection:
        await connection.execute(text(_enrol_everyone_known()))
    assert await enrolled() == students
