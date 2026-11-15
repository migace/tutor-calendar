"""The promise of this project, tested the way it is broken in real life.

Many requests are fired at once through the whole stack - HTTP, the use case,
the repository, a pool of real PostgreSQL connections - and the database is
then asked what it actually stored.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Coroutine
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests import factories
from tests.factories import ANNA, NOW, a_booking, a_tutor
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.main import create_app
from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor
from tutor_calendar.domain.scheduling import Booking, Student

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

URL = "/api/v1/tutors/demo/bookings"
FIRST_SLOT = "2026-11-17T14:00:00Z"
RIVALS = 25
ROUNDS = 8


@pytest.fixture
async def client(engine: AsyncEngine, database_url: str) -> AsyncIterator[AsyncClient]:
    await PostgresTutorRepository(engine).add_if_absent(demo_tutor())
    app = create_app(Settings(database_url=database_url), clock=FixedClock(NOW))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield http
    finally:
        await app.state.engine.dispose()


def booking(
    client: AsyncClient, n: int, *, start: str = FIRST_SLOT, key: str | None = None
) -> Coroutine[Any, Any, Response]:
    return client.post(
        URL,
        json={
            "start": start,
            "student_name": f"Student {n}",
            "student_email": f"student{n}@example.com",
        },
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def stored_bookings(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return int(await connection.scalar(text("SELECT count(*) FROM bookings")) or 0)


async def test_only_one_of_many_simultaneous_requests_gets_the_slot(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    responses: list[Response] = await asyncio.gather(*(booking(client, n) for n in range(RIVALS)))

    assert Counter(response.status_code for response in responses) == {201: 1, 409: RIVALS - 1}
    assert await stored_bookings(engine) == 1

    slots = (await client.get("/api/v1/tutors/demo/slots")).json()["slots"]
    assert FIRST_SLOT not in [slot["start"] for slot in slots]


async def test_simultaneous_retries_of_one_request_create_one_booking(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    key = str(uuid4())

    responses: list[Response] = await asyncio.gather(
        *(booking(client, 1, key=key) for _ in range(RIVALS))
    )

    assert {response.status_code for response in responses} == {201}
    assert len({response.json()["id"] for response in responses}) == 1
    replays = [r for r in responses if r.headers.get("Idempotency-Replayed") == "true"]
    assert len(replays) == RIVALS - 1
    assert await stored_bookings(engine) == 1


async def test_requests_for_different_slots_all_succeed(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    starts = [f"2026-11-{day}T{hour}:00:00Z" for day in (17, 18, 19) for hour in (14, 15, 16, 17)]

    responses: list[Response] = await asyncio.gather(
        *(booking(client, n, start=start) for n, start in enumerate(starts))
    )

    assert {response.status_code for response in responses} == {201}
    assert await stored_bookings(engine) == len(starts)


async def test_a_mixed_rush_leaves_every_slot_booked_exactly_once(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    starts = [f"2026-11-17T{hour}:00:00Z" for hour in (14, 15, 16, 17)]

    responses: list[Response] = await asyncio.gather(
        *(booking(client, n, start=starts[n % len(starts)]) for n in range(40))
    )

    won = Counter(r.json()["start"] for r in responses if r.status_code == 201)
    assert won == dict.fromkeys(starts, 1)
    assert await stored_bookings(engine) == len(starts)


async def test_a_rush_only_ever_ends_in_a_booking_or_a_clean_refusal(engine: AsyncEngine) -> None:
    """Hammer the repository so that rare interleavings get their chance.

    Each round sends 25 writes at one slot: ten are retries of a single request
    (one key), the rest are rivals with keys of their own. Whatever order
    PostgreSQL happens to run them in, the outcome must be one stored booking,
    and every caller must get either that booking or ``SlotTakenError``.

    This test exists because the first version of the repository failed it:
    without the queue on the tutor row, round one or two ended with PostgreSQL
    reporting a deadlock between inserts that had found each other half-done.
    """
    tutor = a_tutor()
    await PostgresTutorRepository(engine).add_if_absent(tutor)
    repository = PostgresBookingRepository(engine)

    for round_number in range(ROUNDS):
        start = factories.FIRST_SLOT + timedelta(hours=round_number)
        retries = [
            repository.add(a_booking(tutor.id, start, student=ANNA), f"retried-{round_number}")
            for _ in range(10)
        ]
        rivals = [
            repository.add(
                a_booking(tutor.id, start, student=Student(f"Rival {n}", f"r{n}@example.com")),
                f"rival-{round_number}-{n}",
            )
            for n in range(15)
        ]

        outcomes = await asyncio.gather(*retries, *rivals, return_exceptions=True)

        unexpected = [o for o in outcomes if not isinstance(o, Booking | SlotTakenError)]
        assert unexpected == [], f"round {round_number}"
        assert len({o.id for o in outcomes if isinstance(o, Booking)}) == 1, f"round {round_number}"

    assert await stored_bookings(engine) == ROUNDS
