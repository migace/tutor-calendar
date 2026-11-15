"""Cancelling and weekly series through HTTP, against a real PostgreSQL."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import LINKS, NOW
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

FIRST_SLOT = "2026-11-17T14:00:00Z"


@pytest.fixture
async def http(engine: AsyncEngine, database_url: str) -> AsyncIterator[AsyncClient]:
    """A client signed in as the demo tutor, with everything real but the clock and the mail."""
    await PostgresTutorRepository(engine).add_if_absent(demo_tutor())
    mailer = InMemoryMailer()
    app = create_app(
        Settings(database_url=database_url), clock=FixedClock(NOW), mailer=mailer, links=LINKS
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
            await client.post("/api/v1/auth/links", json={"email": "demo@example.com"})
            token = re.search(r"#token=(\S+)", mailer.sent[-1].body)
            assert token
            await client.post("/api/v1/auth/session", json={"token": token.group(1)})
            yield client
    finally:
        await app.state.engine.dispose()


async def book(http: AsyncClient, start: str = FIRST_SLOT) -> dict[str, str]:
    response = await http.post(
        "/api/v1/tutors/demo/bookings",
        json={"start": start, "student_name": "Anna", "student_email": "anna@example.com"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


async def test_a_cancelled_slot_can_be_booked_again_and_both_lessons_are_kept(
    http: AsyncClient, engine: AsyncEngine
) -> None:
    first = await book(http)
    cancelled = await http.delete(
        "/api/v1/booking", headers={"Authorization": f"Bearer {first['manage_token']}"}
    )
    assert cancelled.status_code == 200

    second = await book(http)

    assert second["id"] != first["id"]
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT status FROM bookings ORDER BY status"))
        assert [row.status for row in rows] == ["cancelled", "confirmed"]


async def test_the_student_and_the_tutor_cancelling_at_once_cancel_it_once(
    http: AsyncClient, engine: AsyncEngine
) -> None:
    booked = await book(http)
    as_student = {"Authorization": f"Bearer {booked['manage_token']}"}

    responses = await asyncio.gather(
        *(http.delete("/api/v1/booking", headers=as_student) for _ in range(6)),
        *(http.post(f"/api/v1/me/lessons/{booked['id']}/cancellation") for _ in range(6)),
    )

    assert Counter(response.status_code for response in responses) == {200: 1, 409: 11}
    [winner] = [response.json() for response in responses if response.status_code == 200]
    async with engine.connect() as connection:
        stored = (await connection.execute(text("SELECT cancelled_by FROM bookings"))).scalar_one()
    # Whoever won is the one on record.
    assert stored == winner["cancelled_by"]


async def test_a_series_and_visitors_racing_for_the_same_times_never_double_book(
    http: AsyncClient, engine: AsyncEngine
) -> None:
    plan = {
        "student_name": "Bartek",
        "student_email": "bartek@example.com",
        "first_day": "2026-11-17",
        "start": "15:00",
        "weeks": 4,
        "skip_conflicts": True,
    }
    visitors = [
        http.post(
            "/api/v1/tutors/demo/bookings",
            json={"start": start, "student_name": "Anna", "student_email": "anna@example.com"},
            headers={"Idempotency-Key": uuid4().hex},
        )
        for start in ("2026-11-17T14:00:00Z", "2026-11-24T14:00:00Z")
        for _ in range(4)
    ]

    responses = await asyncio.gather(http.put(f"/api/v1/me/series/{uuid4()}", json=plan), *visitors)

    assert {response.status_code for response in responses} <= {200, 201, 409}
    async with engine.connect() as connection:
        starts = [
            row[0]
            for row in await connection.execute(
                text("SELECT lower(during) FROM bookings WHERE status <> 'cancelled'")
            )
        ]
        overlapping = await connection.scalar(
            text(
                "SELECT count(*) FROM bookings a JOIN bookings b"
                " ON a.id < b.id AND a.tutor_id = b.tutor_id AND a.during && b.during"
                " WHERE a.status <> 'cancelled' AND b.status <> 'cancelled'"
            )
        )
    # Four Tuesdays, each taken exactly once by someone.
    assert len(starts) == len(set(starts)) == 4
    assert overlapping == 0


async def test_the_database_itself_refuses_a_half_recorded_cancellation(
    http: AsyncClient, engine: AsyncEngine
) -> None:
    await book(http)

    for broken in (
        "UPDATE bookings SET status = 'cancelled'",  # no details
        "UPDATE bookings SET cancelled_by = 'student', cancelled_at = now()",  # not cancelled
        "UPDATE bookings SET status = 'postponed'",  # no such state
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(text(broken))
