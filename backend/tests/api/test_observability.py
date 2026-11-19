"""What is written down about a request: its id, its log line, and the counts. See ADR 0011."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from pydantic import ValidationError

from tests.api.conftest import sign_in
from tests.factories import LINKS, NOW, STATEMENT_LINKS
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger, InMemoryOutbox
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_credentials import InMemoryCredentialStore
from tutor_calendar.adapters.in_memory_jobs import InMemoryJobLog
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.api.main import create_app
from tutor_calendar.api.observed import REQUEST_ID_HEADER
from tutor_calendar.application.ports import Email
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor
from tutor_calendar.logs import JsonFormatter

TOKEN = "a-metrics-token-used-only-by-the-tests-0123456789"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
BOOKINGS = "/api/v1/tutors/demo/bookings"
KEY = "3f1c8a52-6f6e-4d0b-9a44-1c2d3e4f5a6b"
OTHER_KEY = "9e8d7c6b-5a49-4382-b1a0-0f1e2d3c4b5a"
# Tuesday 17 November 2026, 15:00 in Warsaw: free in the demo tutor's calendar.
FIRST_SLOT = "2026-11-17T14:00:00Z"
ANNA = {"start": FIRST_SLOT, "student_name": "Anna Nowak", "student_email": "anna@example.com"}

Lines = Callable[[], list[dict[str, Any]]]


@pytest.fixture
def lines() -> Iterator[Lines]:
    """The log as the image writes it: each line formatted the moment it is logged.

    Formatting on the spot matters. The request's id is read while the request
    is being answered, and is gone afterwards.
    """
    written = io.StringIO()
    handler = logging.StreamHandler(written)
    handler.setFormatter(JsonFormatter("web"))
    ours = logging.getLogger("tutor_calendar")
    level = ours.level
    ours.addHandler(handler)
    ours.setLevel(logging.INFO)
    try:
        yield lambda: [json.loads(line) for line in written.getvalue().splitlines()]
    finally:
        ours.removeHandler(handler)
        ours.setLevel(level)


class Stores:
    def __init__(self) -> None:
        self.outbox = InMemoryOutbox()
        self.bookings = InMemoryBookingRepository(self.outbox)
        self.jobs = InMemoryJobLog()
        self.mailer = InMemoryMailer()


@pytest.fixture
def stores() -> Stores:
    return Stores()


def an_app(stores: Stores, **settings: Any) -> FastAPI:
    return create_app(
        Settings(**settings),
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor()]),
        bookings=stores.bookings,
        credentials=InMemoryCredentialStore(),
        mailer=stores.mailer,
        ledger=InMemoryLedger(),
        links=LINKS,
        statement_links=STATEMENT_LINKS,
        outbox=stores.outbox,
        jobs=stores.jobs,
    )


@pytest.fixture
def client(stores: Stores) -> Iterator[TestClient]:
    with TestClient(an_app(stores, metrics_token=TOKEN), base_url="https://testserver") as client:
        yield client


def book(client: TestClient, key: str = KEY, **changes: Any) -> int:
    response = client.post(BOOKINGS, json=ANNA | changes, headers={"Idempotency-Key": key})
    return response.status_code


def samples(client: TestClient) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    """Every number on the metrics page, by name and labels."""
    response = client.get("/metrics", headers=BEARER)
    assert response.status_code == 200, response.text
    return {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
    }


def value(client: TestClient, name: str, **labels: str) -> float | None:
    return samples(client).get((name, tuple(sorted(labels.items()))))


# The request's id


def test_a_request_without_an_id_is_given_one(client: TestClient) -> None:
    first = client.get("/api/v1/config").headers[REQUEST_ID_HEADER]
    second = client.get("/api/v1/config").headers[REQUEST_ID_HEADER]

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_an_id_the_caller_sent_comes_back_and_is_on_the_log_line(
    client: TestClient, lines: Lines
) -> None:
    response = client.get("/api/v1/config", headers={REQUEST_ID_HEADER: "ticket-4821.retry_2"})

    assert response.headers[REQUEST_ID_HEADER] == "ticket-4821.retry_2"
    assert [line["request_id"] for line in lines()] == ["ticket-4821.retry_2"]


@pytest.mark.parametrize(
    "unsafe",
    [
        "short",
        "x" * 65,
        "has spaces in it",
        'quote"and{brace}',
        "line\tbreak-attempt",
        "anna@example.com",
        "",
    ],
)
def test_an_id_that_is_not_short_and_plain_is_replaced(
    client: TestClient, lines: Lines, unsafe: str
) -> None:
    response = client.get("/api/v1/config", headers={REQUEST_ID_HEADER: unsafe})

    given = response.headers[REQUEST_ID_HEADER]
    assert re.fullmatch(r"[0-9a-f]{32}", given)
    assert [line["request_id"] for line in lines()] == [given]


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/api/v1/me", 401),
        ("GET", "/api/v1/no-such-thing", 404),
        ("POST", BOOKINGS, 422),
        ("GET", "/metrics", 401),
        ("GET", "/health", 200),
    ],
)
def test_refusals_carry_the_id_as_well(
    client: TestClient, method: str, path: str, status: int
) -> None:
    response = client.request(method, path)

    assert response.status_code == status
    assert response.headers[REQUEST_ID_HEADER]


def test_a_redirect_to_https_carries_the_id(stores: Stores) -> None:
    app = an_app(stores, public_url="https://calendar.example.com")
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/v1/config", headers={"X-Forwarded-Proto": "http"})

    assert response.status_code == 308
    assert response.headers[REQUEST_ID_HEADER]


def test_an_error_nobody_handled_is_answered_and_logged_under_one_id(
    stores: Stores, lines: Lines
) -> None:
    app = an_app(stores)

    @app.get("/broken")
    async def broken() -> None:
        raise RuntimeError("something nobody expected")

    with TestClient(app) as client:
        response = client.get("/broken")

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    failure, request = lines()
    assert failure["message"] == "unhandled error"
    assert failure["level"] == "error"
    assert "RuntimeError: something nobody expected" in failure["error"]
    assert (request["status"], request["route"], request["level"]) == (500, "/broken", "error")
    assert failure["request_id"] == request["request_id"] == response.headers[REQUEST_ID_HEADER]


# The log line of a request


def test_a_request_is_one_line_with_the_route_and_how_it_ended(
    client: TestClient, lines: Lines
) -> None:
    response = client.get("/api/v1/tutors/demo/slots")

    (line,) = lines()
    assert line["duration_ms"] >= 0
    assert {name: line[name] for name in line if name not in {"time", "duration_ms"}} == {
        "level": "info",
        "service": "web",
        "logger": "tutor_calendar.access",
        "message": "GET /api/v1/tutors/demo/slots 200",
        "request_id": response.headers[REQUEST_ID_HEADER],
        "method": "GET",
        "path": "/api/v1/tutors/demo/slots",
        "route": "/api/v1/tutors/{slug}/slots",
        "status": 200,
    }


def test_a_student_is_in_the_log_by_id_and_never_by_address(
    client: TestClient, stores: Stores, lines: Lines
) -> None:
    # Everything that sends an address: a booking, a sign-in, opening an account.
    assert book(client) == 201
    sign_in(client, stores.mailer)
    student = client.post("/api/v1/me/students", json={"email": "Anna@Example.com"}).json()
    statement = client.get(f"/api/v1/me/students/{student['id']}/statement")
    assert statement.status_code == 200

    log = lines()
    written = json.dumps(log).lower()
    assert "anna@example.com" not in written
    assert "demo@example.com" not in written
    assert "@" not in written
    # The id is what makes the line worth having.
    assert log[-1]["path"] == f"/api/v1/me/students/{student['id']}/statement"
    assert log[-1]["route"] == "/api/v1/me/students/{student_id}/statement"


def test_neither_a_sign_in_token_nor_a_session_reaches_the_log(
    client: TestClient, stores: Stores, lines: Lines
) -> None:
    client.post("/api/v1/auth/links", json={"email": "demo@example.com"})
    token = re.search(r"#token=(\S+)", stores.mailer.sent[-1].body)
    assert token
    assert client.post("/api/v1/auth/session", json={"token": token.group(1)}).status_code == 200
    session = client.cookies["tc_session"]
    assert client.get("/api/v1/me").status_code == 200

    written = json.dumps(lines())
    assert token.group(1) not in written
    assert session not in written


def test_the_query_string_is_not_logged(client: TestClient, lines: Lines) -> None:
    client.get("/api/v1/tutors/demo/slots?token=a-secret-in-the-wrong-place&email=anna@example.com")

    (line,) = lines()
    assert line["path"] == "/api/v1/tutors/demo/slots"
    assert "a-secret-in-the-wrong-place" not in json.dumps(line)
    assert "anna" not in json.dumps(line)


def test_an_address_typed_into_a_path_is_cut_out(
    stores: Stores, lines: Lines, tmp_path: Path
) -> None:
    # A bookmark from before students had ids still holds an address. See ADR 0010.
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with TestClient(an_app(stores, static_dir=tmp_path)) as client:
        assert client.get("/panel/students/anna@example.com").status_code == 200
        assert client.get("/api/v1/me/students/anna%40example.com/statement").status_code == 401

    page, request = lines()
    assert (page["path"], page["route"]) == ("/panel/students/[address]", "static")
    assert request["path"] == "/api/v1/me/students/[address]/statement"
    assert "anna" not in json.dumps([page, request])


def test_what_the_web_app_could_not_serve_is_not_counted_as_the_web_app(
    stores: Stores, tmp_path: Path
) -> None:
    # The web app is mounted last, so an API path that does not exist, or a
    # method an API route does not take, ends up being refused by it.
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with TestClient(an_app(stores, static_dir=tmp_path, metrics_token=TOKEN)) as client:
        assert client.get("/panel").status_code == 200
        assert client.get("/api/v1/no-such-thing").status_code == 404
        assert client.post("/api/v1/config").status_code == 405
        numbers = samples(client)

    counted = {
        (dict(labels)["route"], dict(labels)["status"]): count
        for (name, labels), count in numbers.items()
        if name == "tutor_calendar_http_request_duration_seconds_count"
    }
    assert counted == {("static", "200"): 1, ("unmatched", "404"): 1, ("unmatched", "405"): 1}


def test_checks_that_pass_stay_out_of_the_log_and_ones_that_fail_do_not(
    stores: Stores, lines: Lines
) -> None:
    # Port 1 is never a PostgreSQL server, so readiness fails at once.
    down = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere"
    with TestClient(an_app(stores, metrics_token=TOKEN, database_url=down)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/metrics", headers=BEARER).status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.get("/metrics").status_code == 401

    assert [(line["path"], line["status"]) for line in lines()] == [
        ("/health/ready", 503),
        ("/metrics", 401),
    ]


# The metrics


def test_metrics_are_off_until_a_token_is_set(stores: Stores) -> None:
    with TestClient(an_app(stores)) as client:
        assert client.get("/metrics").status_code == 404
        assert client.get("/metrics", headers=BEARER).status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {TOKEN[:-1]}"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": TOKEN},
        {"Authorization": "Bearer zażółć-gęślą-jaźń"},
    ],
)
def test_metrics_are_refused_without_the_token(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get(
        "/metrics", headers={name.encode(): value.encode() for name, value in headers.items()}
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "tutor_calendar" not in response.text


@pytest.mark.parametrize("token", ["", None])
def test_no_token_means_no_token(token: str | None) -> None:
    # Compose hands an unset variable on as an empty one.
    assert Settings(metrics_token=token).metrics_token is None


def test_a_token_short_enough_to_guess_is_refused_at_start() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters") as refusal:
        Settings(metrics_token="hunter2-typed-by-an-operator")

    # The refusal ends up in the log of every container that fails to start.
    assert "hunter2" not in str(refusal.value)


def test_a_booking_shows_up_in_the_metrics(client: TestClient) -> None:
    def outcomes() -> dict[str, float | None]:
        numbers = samples(client)
        return {
            outcome: numbers.get(("tutor_calendar_booking_requests_total", (("outcome", outcome),)))
            for outcome in ("booked", "replayed", "taken", "not_offered")
        }

    # All there from the start, at zero, so that the first one is a change and not an arrival.
    assert outcomes() == {"booked": 0, "replayed": 0, "taken": 0, "not_offered": 0}
    assert value(client, "tutor_calendar_outbox_waiting_messages") == 0

    assert book(client) == 201
    assert outcomes() == {"booked": 1, "replayed": 0, "taken": 0, "not_offered": 0}
    # The confirmation was queued with the booking and nothing has sent it yet.
    assert value(client, "tutor_calendar_outbox_waiting_messages") == 1

    # The same request again, as after a lost response.
    assert book(client) == 201
    # Someone else, for the time that is gone.
    assert book(client, key=OTHER_KEY, student_name="Bartek Lis") == 409
    # A time the tutor does not teach.
    assert book(client, key=OTHER_KEY, start="2026-11-17T03:00:00Z") == 409
    assert outcomes() == {"booked": 1, "replayed": 1, "taken": 1, "not_offered": 1}
    assert value(client, "tutor_calendar_outbox_waiting_messages") == 1


def test_requests_are_counted_by_route_template_and_status(client: TestClient) -> None:
    def count(route: str, status: str, method: str = "POST") -> float | None:
        return value(
            client,
            "tutor_calendar_http_request_duration_seconds_count",
            method=method,
            route=route,
            status=status,
        )

    book(client)
    book(client, key=OTHER_KEY)
    client.get("/api/v1/tutors/demo/slots")
    client.get("/api/v1/tutors/nobody/slots")
    client.get("/somewhere/else")

    assert count("/api/v1/tutors/{slug}/bookings", "201") == 1
    assert count("/api/v1/tutors/{slug}/bookings", "409") == 1
    assert count("/api/v1/tutors/{slug}/slots", "200", "GET") == 1
    assert count("/api/v1/tutors/{slug}/slots", "404", "GET") == 1
    assert count("unmatched", "404", "GET") == 1
    # The framework's own pages are counted under their own, fixed, paths.
    client.get("/openapi.json")
    assert count("/openapi.json", "200", "GET") == 1
    in_time = value(
        client,
        "tutor_calendar_http_request_duration_seconds_bucket",
        method="POST",
        route="/api/v1/tutors/{slug}/bookings",
        status="201",
        le="+Inf",
    )
    assert in_time == 1


def test_no_metric_names_a_tutor_a_student_or_a_made_up_method(
    client: TestClient, stores: Stores
) -> None:
    book(client)
    sign_in(client, stores.mailer)
    student = client.post("/api/v1/me/students", json={"email": "anna@example.com"}).json()
    client.get(f"/api/v1/me/students/{student['id']}/statement")
    client.request("BREW", "/api/v1/tutors/demo/slots")

    page = client.get("/metrics", headers=BEARER).text

    assert student["id"] not in page
    assert "anna" not in page
    assert "/tutors/demo" not in page
    assert "BREW" not in page
    assert "_created" not in page
    assert 'method="OTHER"' in page


def test_the_background_work_is_read_when_the_metrics_are_asked_for(
    stores: Stores,
) -> None:
    now = NOW + timedelta(hours=3)
    app = create_app(
        Settings(metrics_token=TOKEN),
        clock=FixedClock(now),
        tutors=InMemoryTutorRepository([demo_tutor()]),
        bookings=stores.bookings,
        outbox=stores.outbox,
        jobs=stores.jobs,
    )
    stores.outbox.put(Email("anna@example.com", "Hello", "A message"), now - timedelta(minutes=5))
    stores.outbox.put(Email("anna@example.com", "Again", "A message"), now - timedelta(minutes=1))

    with TestClient(app) as client:
        assert value(client, "tutor_calendar_database_up") == 1
        assert value(client, "tutor_calendar_outbox_waiting_messages") == 2
        assert value(client, "tutor_calendar_outbox_oldest_waiting_seconds") == 300
        assert value(client, "tutor_calendar_lessons_awaiting_settlement") == 0
        last_success = "tutor_calendar_worker_last_success_timestamp_seconds"
        # A worker that has never finished a job has no time to report.
        assert value(client, last_success, job="deliver") is None

        asyncio.run(stores.jobs.record_success("deliver", now - timedelta(seconds=30)))

        assert value(client, last_success, job="deliver") == (now.timestamp() - 30)
        assert value(client, last_success, job="settle") is None


def test_with_the_database_down_the_process_still_reports_what_it_counted(
    lines: Lines,
) -> None:
    down = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere"
    with TestClient(create_app(Settings(metrics_token=TOKEN, database_url=down))) as client:
        client.get("/health")
        numbers = samples(client)

    assert numbers[("tutor_calendar_database_up", ())] == 0
    # Left out, not reported as zero: "nothing is waiting" would be a lie.
    assert not [name for name, _ in numbers if name.startswith("tutor_calendar_outbox")]
    health = (("method", "GET"), ("route", "/health"), ("status", "200"))
    assert numbers[("tutor_calendar_http_request_duration_seconds_count", health)] == 1
    said = [line for line in lines() if line["logger"] == "tutor_calendar.api"]
    assert [line["level"] for line in said] == ["warning"]
