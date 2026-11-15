"""Tests that need a real PostgreSQL with migrations applied.

Locally they are skipped when no database answers (``docker compose up -d db``
and ``alembic upgrade head`` to run them). In CI a missing database is a failure.
"""

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings

pytestmark = pytest.mark.integration


async def _installed_extensions(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text("SELECT extname FROM pg_extension"))
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def extensions() -> set[str]:
    try:
        return asyncio.run(_installed_extensions(Settings().database_url))
    except Exception as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL is not reachable: {error!r}")


@pytest.fixture
def client(extensions: set[str]) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_readiness_reports_ok_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_migrations_enabled_btree_gist(extensions: set[str]) -> None:
    # Needed for the exclusion constraint that prevents double bookings.
    assert "btree_gist" in extensions
