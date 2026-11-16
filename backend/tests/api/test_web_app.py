"""The API serving the built web app, as it does in production."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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

INDEX = "<!doctype html><title>Tutor Calendar</title><div id=root></div>"


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """A folder shaped like the output of the frontend build."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def client_for(static_dir: Path | None) -> Iterator[TestClient]:
    app = create_app(
        Settings(static_dir=static_dir),
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor()]),
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
def web(built: Path) -> Iterator[TestClient]:
    yield from client_for(built)


@pytest.mark.parametrize("path", ["/", "/book/demo", "/panel/students/anna%40example.com"])
def test_any_page_of_the_app_is_answered_with_the_app(web: TestClient, path: str) -> None:
    response = web.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    # The page names the current assets, so it must not be served stale.
    assert response.headers["cache-control"] == "no-cache"


def test_assets_are_served_and_cached_for_good(web: TestClient) -> None:
    response = web.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == "console.log(1)"
    assert "immutable" in response.headers["cache-control"]


@pytest.mark.parametrize("path", ["/assets/gone-000000.js", "/favicon.ico", "/robots.txt"])
def test_a_missing_file_is_missing_not_the_app(web: TestClient, path: str) -> None:
    # Answering a request for a script with HTML would hide a broken deployment.
    assert web.get(path).status_code == 404


def test_the_api_is_not_shadowed_by_the_app(web: TestClient) -> None:
    assert web.get("/health").json() == {"status": "ok"}
    assert web.get("/api/v1/tutors/demo/slots").headers["content-type"] == "application/json"
    assert web.get("/api/v1/tutors/nobody/slots").status_code == 404
    assert web.get("/api/v1/no/such/endpoint").status_code == 404
    assert web.post("/api/v1/auth/links", json={"email": "demo@example.com"}).status_code == 202


def test_without_a_built_app_only_the_api_answers() -> None:
    [client] = list(client_for(None))

    assert client.get("/health").status_code == 200
    assert client.get("/book/demo").status_code == 404


@pytest.mark.parametrize("path", ["/", "/book/demo", "/api/v1/tutors/demo/slots", "/health"])
def test_every_answer_carries_the_security_headers(web: TestClient, path: str) -> None:
    headers = web.get(path).headers

    policy = headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy  # the app cannot be framed by another site
    assert "unsafe-inline" not in policy
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_the_api_documentation_still_works(web: TestClient) -> None:
    # It loads scripts from a CDN, which the policy would block.
    assert "content-security-policy" not in web.get("/docs").headers
