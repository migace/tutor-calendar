from __future__ import annotations

from collections.abc import Iterator
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient

from tests.factories import LINKS, NOW, STATEMENT_LINKS
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_credentials import InMemoryCredentialStore
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor

DEMO_SESSION = "/api/v1/auth/demo-session"


def app_with(*, demo_mode: bool, with_demo_tutor: bool = True) -> Iterator[TestClient]:
    app = create_app(
        Settings(demo_mode=demo_mode),
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor()] if with_demo_tutor else []),
        bookings=InMemoryBookingRepository(),
        credentials=InMemoryCredentialStore(),
        mailer=InMemoryMailer(),
        ledger=InMemoryLedger(),
        links=LINKS,
        statement_links=STATEMENT_LINKS,
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


@pytest.fixture
def demo() -> Iterator[TestClient]:
    yield from app_with(demo_mode=True)


@pytest.fixture
def real() -> Iterator[TestClient]:
    yield from app_with(demo_mode=False)


def test_the_web_app_can_ask_whether_this_is_a_demonstration(
    demo: TestClient, real: TestClient
) -> None:
    assert demo.get("/api/v1/config").json() == {"demo_mode": True}
    assert real.get("/api/v1/config").json() == {"demo_mode": False}


def test_on_a_demonstration_anyone_can_enter_the_demo_tutors_panel(demo: TestClient) -> None:
    response = demo.post(DEMO_SESSION)

    assert response.status_code == 200
    assert response.json()["slug"] == "demo"
    assert demo.get("/api/v1/me").json()["display_name"] == "Demo Tutor"


def test_a_demo_session_is_short_and_as_locked_down_as_a_real_one(demo: TestClient) -> None:
    response = demo.post(DEMO_SESSION)

    cookie = SimpleCookie(response.headers["set-cookie"])["tc_session"]
    assert cookie["max-age"] == str(2 * 60 * 60)
    assert cookie["httponly"]
    assert cookie["secure"]
    assert cookie["samesite"] == "lax"


def test_anywhere_else_the_door_does_not_exist(real: TestClient) -> None:
    response = real.post(DEMO_SESSION)

    assert response.status_code == 404
    assert "set-cookie" not in response.headers
    assert real.get("/api/v1/me").status_code == 401


def test_a_demonstration_without_its_tutor_says_so() -> None:
    [client] = list(app_with(demo_mode=True, with_demo_tutor=False))

    assert client.post(DEMO_SESSION).status_code == 404


def test_demo_mode_is_off_unless_asked_for() -> None:
    assert Settings().demo_mode is False
