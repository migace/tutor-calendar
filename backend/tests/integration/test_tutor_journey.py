"""A tutor's whole visit, through HTTP, against a real PostgreSQL."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import NOW
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

FIRST_SLOT = "2026-11-17T14:00:00Z"


@dataclass
class Visit:
    http: AsyncClient
    mailer: InMemoryMailer
    settings: Settings

    async def request_token(self) -> str:
        await self.http.post("/api/v1/auth/links", json={"email": "demo@example.com"})
        match = re.search(r"#token=(\S+)", self.mailer.sent[-1].body)
        assert match
        return match.group(1)

    def another_browser(self) -> AsyncClient:
        app = self.http._transport.app  # type: ignore[attr-defined]
        return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


@pytest.fixture
async def visit(engine: AsyncEngine, database_url: str) -> AsyncIterator[Visit]:
    await PostgresTutorRepository(engine).add_if_absent(demo_tutor())
    settings = Settings(database_url=database_url)
    mailer = InMemoryMailer()
    # Everything but the clock and the mailbox is the real thing.
    app = create_app(settings, clock=FixedClock(NOW), mailer=mailer)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as http:
            yield Visit(http, mailer, settings)
    finally:
        await app.state.engine.dispose()


async def test_a_tutor_signs_in_sees_a_new_lesson_and_changes_their_hours(visit: Visit) -> None:
    http = visit.http
    token = await visit.request_token()
    assert (await http.post("/api/v1/auth/session", json={"token": token})).status_code == 200
    assert (await http.get("/api/v1/me")).json()["slug"] == "demo"

    # Meanwhile a parent, in a browser of their own, books a lesson.
    async with visit.another_browser() as parent:
        booked = await parent.post(
            "/api/v1/tutors/demo/bookings",
            json={"start": FIRST_SLOT, "student_name": "Anna", "student_email": "anna@example.com"},
            headers={"Idempotency-Key": "a" * 32},
        )
        assert booked.status_code == 201
        assert (await parent.get("/api/v1/me/week")).status_code == 401

    week = (await http.get("/api/v1/me/week")).json()
    assert [lesson["student_name"] for lesson in week["days"][1]["lessons"]] == ["Anna"]

    changed = await http.put(
        "/api/v1/me/availability",
        json={"rules": [{"weekday": 4, "start": "08:00", "end": "10:00"}]},
    )
    assert changed.status_code == 200
    slots = (await http.get("/api/v1/tutors/demo/slots")).json()["slots"]
    assert [slot["start"] for slot in slots] == [
        "2026-11-20T07:00:00Z",
        "2026-11-20T08:00:00Z",
        "2026-11-27T07:00:00Z",
        "2026-11-27T08:00:00Z",
    ]
    # The lesson booked under the old hours is still there.
    week = (await http.get("/api/v1/me/week")).json()
    assert len(week["days"][1]["lessons"]) == 1

    assert (await http.delete("/api/v1/auth/session")).status_code == 204
    assert (await http.get("/api/v1/me")).status_code == 401


async def test_a_sign_in_link_opened_many_times_at_once_signs_in_once(
    visit: Visit, engine: AsyncEngine
) -> None:
    token = await visit.request_token()
    browsers = [visit.another_browser() for _ in range(12)]

    try:
        responses = await asyncio.gather(
            *(b.post("/api/v1/auth/session", json={"token": token}) for b in browsers)
        )
    finally:
        await asyncio.gather(*(browser.aclose() for browser in browsers))

    assert Counter(response.status_code for response in responses) == {200: 1, 401: 11}
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM sessions")) == 1


async def test_secrets_are_not_in_the_database(visit: Visit, engine: AsyncEngine) -> None:
    token = await visit.request_token()
    await visit.http.post("/api/v1/auth/session", json={"token": token})
    session_token = visit.http.cookies["tc_session"]

    async with engine.connect() as connection:
        stored = {
            row[0]
            for table in ("sign_in_tokens", "sessions")
            for row in await connection.execute(text(f"SELECT digest FROM {table}"))
        }

    assert len(stored) == 2
    assert token not in stored
    assert session_token not in stored
