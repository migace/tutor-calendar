"""The schema and the tutor repository, against a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import a_booking, a_tutor
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tables import metadata
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def test_readiness_reports_ok_when_the_database_answers(database_url: str) -> None:
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_migrations_build_the_tables_the_code_expects(engine: AsyncEngine) -> None:
    def differences(connection: Connection) -> list[Any]:
        return list(compare_metadata(MigrationContext.configure(connection), metadata))

    async with engine.connect() as connection:
        assert await connection.run_sync(differences) == []


async def test_bookings_carry_both_guarantees_as_constraints(engine: AsyncEngine) -> None:
    # Alembic does not compare exclusion constraints, so this one is checked by name.
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT conname, contype::text FROM pg_constraint"
                " WHERE conrelid = 'bookings'::regclass AND contype IN ('x', 'u')"
            )
        )
        assert {(row.conname, row.contype) for row in rows} == {
            ("bookings_no_overlap", "x"),
            ("bookings_idempotency_key_unique", "u"),
        }


@pytest.mark.parametrize("tutor_slug", ["ewa", "demo"])
async def test_a_tutor_comes_back_from_the_database_unchanged(
    engine: AsyncEngine, tutor_slug: str
) -> None:
    tutor = demo_tutor() if tutor_slug == "demo" else a_tutor(tutor_slug)
    repository = PostgresTutorRepository(engine)

    assert await repository.add_if_absent(tutor)

    assert await repository.get_by_slug(tutor_slug) == tutor
    assert await repository.get_by_slug("nobody") is None


async def test_adding_a_tutor_whose_slug_exists_changes_nothing(engine: AsyncEngine) -> None:
    repository = PostgresTutorRepository(engine)
    original = a_tutor("ewa")
    await repository.add_if_absent(original)

    assert not await repository.add_if_absent(a_tutor("ewa"))

    assert await repository.get_by_slug("ewa") == original


async def test_a_tutor_with_bookings_cannot_be_deleted(engine: AsyncEngine) -> None:
    tutor = a_tutor()
    await PostgresTutorRepository(engine).add_if_absent(tutor)
    await PostgresBookingRepository(engine).add(a_booking(tutor.id), "key-1")

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM tutors"))
