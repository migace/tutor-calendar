"""How often one visitor may ask, and who counts as one visitor. See ADR 0009."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.factories import LINKS, NOW, STATEMENT_LINKS
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_credentials import InMemoryCredentialStore
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.api.main import create_app
from tutor_calendar.api.rate_limit import (
    ANY_REQUEST,
    BOOKINGS,
    SIGN_IN_LINKS,
    Limit,
    RateLimiter,
    visitor_of,
)
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor

FIVE_A_MINUTE = Limit("test", burst=5, per_seconds=60)


class Stopwatch:
    """Time that only moves when a test says so."""

    def __init__(self) -> None:
        self.seconds = 1000.0

    def __call__(self) -> float:
        return self.seconds

    def wait(self, seconds: float) -> None:
        self.seconds += seconds


@pytest.fixture
def time() -> Stopwatch:
    return Stopwatch()


@pytest.fixture
def limiter(time: Stopwatch) -> RateLimiter:
    return RateLimiter(now=time)


def allowed(limiter: RateLimiter, limit: Limit, visitor: str = "a") -> bool:
    return limiter.seconds_to_wait(limit, visitor) == 0


# The counting


def test_the_whole_allowance_can_be_used_at_once_and_then_no_more(limiter: RateLimiter) -> None:
    assert [allowed(limiter, FIVE_A_MINUTE) for _ in range(6)] == [True] * 5 + [False]


def test_a_refusal_says_how_long_until_the_next_request_is_allowed(
    limiter: RateLimiter, time: Stopwatch
) -> None:
    for _ in range(5):
        limiter.seconds_to_wait(FIVE_A_MINUTE, "a")

    # Five a minute is one every twelve seconds.
    assert limiter.seconds_to_wait(FIVE_A_MINUTE, "a") == pytest.approx(12)
    time.wait(11)
    assert limiter.seconds_to_wait(FIVE_A_MINUTE, "a") == pytest.approx(1)
    time.wait(1)
    assert allowed(limiter, FIVE_A_MINUTE)


def test_requests_are_earned_back_one_at_a_time_not_all_at_once(
    limiter: RateLimiter, time: Stopwatch
) -> None:
    for _ in range(5):
        limiter.seconds_to_wait(FIVE_A_MINUTE, "a")

    time.wait(24)

    assert [allowed(limiter, FIVE_A_MINUTE) for _ in range(3)] == [True, True, False]


def test_being_refused_costs_nothing(limiter: RateLimiter, time: Stopwatch) -> None:
    for _ in range(5):
        limiter.seconds_to_wait(FIVE_A_MINUTE, "a")
    # Hammering while over the limit must not push the wait further away.
    for _ in range(100):
        limiter.seconds_to_wait(FIVE_A_MINUTE, "a")

    time.wait(12)

    assert allowed(limiter, FIVE_A_MINUTE)


def test_an_allowance_never_grows_beyond_its_size(limiter: RateLimiter, time: Stopwatch) -> None:
    limiter.seconds_to_wait(FIVE_A_MINUTE, "a")

    time.wait(3600)

    assert [allowed(limiter, FIVE_A_MINUTE) for _ in range(6)] == [True] * 5 + [False]


def test_visitors_and_limits_are_counted_apart(limiter: RateLimiter) -> None:
    other = Limit("other", burst=1, per_seconds=60)
    for _ in range(5):
        limiter.seconds_to_wait(FIVE_A_MINUTE, "a")

    assert not allowed(limiter, FIVE_A_MINUTE, "a")
    assert allowed(limiter, FIVE_A_MINUTE, "b")
    assert allowed(limiter, other, "a")


@pytest.mark.parametrize("limit", [ANY_REQUEST, SIGN_IN_LINKS, BOOKINGS])
def test_rounding_never_takes_a_request_away(limit: Limit, limiter: RateLimiter) -> None:
    assert [allowed(limiter, limit) for _ in range(limit.burst + 1)] == [
        *[True] * limit.burst,
        False,
    ]


def test_visitors_who_went_quiet_are_forgotten(limiter: RateLimiter, time: Stopwatch) -> None:
    # Otherwise the table would grow with every address that ever called.
    for visitor in range(2000):
        limiter.seconds_to_wait(FIVE_A_MINUTE, str(visitor))
    assert len(limiter) == 2000

    time.wait(60)
    for visitor in range(2000, 4100):
        limiter.seconds_to_wait(FIVE_A_MINUTE, str(visitor))

    assert len(limiter) < 2200


# Who is one visitor


def request_from(connection: str | None, **headers: str) -> Request:
    return Request(
        {
            "type": "http",
            "client": (connection, 50000) if connection else None,
            "headers": [
                (name.replace("_", "-").encode(), value.encode()) for name, value in headers.items()
            ],
        }
    )


def test_without_a_proxy_the_visitor_is_the_address_of_the_connection() -> None:
    assert visitor_of(request_from("203.0.113.7"), None) == "203.0.113.7"


def test_a_header_is_not_believed_unless_a_proxy_was_named() -> None:
    request = request_from("203.0.113.7", x_real_ip="198.51.100.1")

    assert visitor_of(request, None) == "203.0.113.7"
    assert visitor_of(request, "X-Real-IP") == "198.51.100.1"


def test_in_a_list_of_addresses_the_one_the_nearest_proxy_added_counts() -> None:
    # Everything before the last entry was written by someone further away,
    # possibly the visitor.
    request = request_from("10.0.0.1", x_forwarded_for="1.2.3.4, 198.51.100.1")

    assert visitor_of(request, "X-Forwarded-For") == "198.51.100.1"


def test_a_request_that_did_not_come_through_the_proxy_is_counted_by_its_connection() -> None:
    assert visitor_of(request_from("127.0.0.1"), "CF-Connecting-IP") == "127.0.0.1"


def test_one_ipv6_network_is_one_visitor() -> None:
    first = visitor_of(request_from("2001:db8:1:2:aaaa::1"), None)
    second = visitor_of(request_from("2001:db8:1:2:bbbb::2"), None)
    neighbour = visitor_of(request_from("2001:db8:1:3::1"), None)

    assert first == second == "2001:db8:1:2::"
    assert neighbour != first


def test_an_ipv4_address_written_as_ipv6_is_the_same_visitor() -> None:
    assert visitor_of(request_from("::ffff:203.0.113.7"), None) == "203.0.113.7"


@pytest.mark.parametrize("connection", [None, "testclient", ""])
def test_what_is_not_an_address_shares_one_allowance(connection: str | None) -> None:
    assert visitor_of(request_from(connection), None) == "unknown"


# Through the API


@pytest.fixture
def api(time: Stopwatch) -> Iterator[TestClient]:
    app = create_app(
        Settings(rate_limits=True, client_address_header="X-Real-IP"),
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor()]),
        bookings=InMemoryBookingRepository(),
        credentials=InMemoryCredentialStore(),
        mailer=InMemoryMailer(),
        ledger=InMemoryLedger(),
        links=LINKS,
        statement_links=STATEMENT_LINKS,
    )
    app.state.rate_limiter = RateLimiter(now=time)
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def ask_for_a_link(api: TestClient, visitor: str = "203.0.113.7") -> int:
    response = api.post(
        "/api/v1/auth/links", json={"email": "demo@example.com"}, headers={"X-Real-IP": visitor}
    )
    return response.status_code


def test_the_sixth_sign_in_link_in_a_row_is_refused(api: TestClient) -> None:
    assert [ask_for_a_link(api) for _ in range(5)] == [202] * 5

    response = api.post(
        "/api/v1/auth/links",
        json={"email": "demo@example.com"},
        headers={"X-Real-IP": "203.0.113.7"},
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "too many requests, try again later"}
    # Five in a quarter of an hour is one every three minutes.
    assert response.headers["retry-after"] == "180"


def test_one_visitor_over_the_limit_does_not_hold_up_another(api: TestClient) -> None:
    for _ in range(6):
        ask_for_a_link(api, "203.0.113.7")

    assert ask_for_a_link(api, "203.0.113.7") == 429
    assert ask_for_a_link(api, "198.51.100.1") == 202


def test_after_the_wait_it_says_the_next_request_goes_through(
    api: TestClient, time: Stopwatch
) -> None:
    for _ in range(6):
        ask_for_a_link(api)

    time.wait(179)
    assert ask_for_a_link(api) == 429
    time.wait(1)
    assert ask_for_a_link(api) == 202


def test_bookings_are_limited_before_they_are_looked_at(api: TestClient) -> None:
    def book() -> int:
        # Not even a valid request: the limit comes first, so that a loop of
        # nonsense cannot keep the application busy either.
        return api.post("/api/v1/tutors/demo/bookings", json={}).status_code

    assert [book() for _ in range(11)] == [422] * 10 + [429]


def test_the_api_as_a_whole_has_a_limit_too(api: TestClient) -> None:
    answers = [api.get("/api/v1/config").status_code for _ in range(121)]

    assert answers == [200] * 120 + [429]


def test_the_health_checks_are_never_told_to_wait(api: TestClient) -> None:
    assert {api.get("/health").status_code for _ in range(300)} == {200}


def test_the_limits_can_be_turned_off() -> None:
    app = create_app(
        Settings(rate_limits=False),
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor()]),
        bookings=InMemoryBookingRepository(),
        credentials=InMemoryCredentialStore(),
        mailer=InMemoryMailer(),
        ledger=InMemoryLedger(),
        links=LINKS,
        statement_links=STATEMENT_LINKS,
    )
    with TestClient(app) as client:
        assert {client.get("/api/v1/config").status_code for _ in range(300)} == {200}
