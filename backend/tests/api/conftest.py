from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.factories import LINKS, NOW, STATEMENT_LINKS, a_tutor
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_credentials import InMemoryCredentialStore
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.api.main import create_app
from tutor_calendar.demo import demo_tutor


@pytest.fixture
def mailer() -> InMemoryMailer:
    return InMemoryMailer()


@pytest.fixture
def client(mailer: InMemoryMailer) -> Iterator[TestClient]:
    """The API with fakes behind it.

    Two tutors (the demo one and "ewa"), no bookings, a clock stopped at NOW.
    Served over https so that the client sends the Secure session cookie back.
    """
    app = create_app(
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor(), a_tutor("ewa")]),
        bookings=InMemoryBookingRepository(),
        credentials=InMemoryCredentialStore(),
        mailer=mailer,
        ledger=InMemoryLedger(),
        links=LINKS,
        statement_links=STATEMENT_LINKS,
    )
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def token_in(mailer: InMemoryMailer) -> str:
    """The token from the most recent sign-in e-mail."""
    match = re.search(r"/sign-in/verify#token=(\S+)", mailer.sent[-1].body)
    assert match, mailer.sent[-1].body
    return match.group(1)


def sign_in(client: TestClient, mailer: InMemoryMailer, email: str = "demo@example.com") -> None:
    """Go through the whole flow; afterwards the client carries the session cookie."""
    assert client.post("/api/v1/auth/links", json={"email": email}).status_code == 202
    response = client.post("/api/v1/auth/session", json={"token": token_in(mailer)})
    assert response.status_code == 200, response.text
