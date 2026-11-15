from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.api.main import create_app

# A Monday morning. The demo tutor teaches Mon-Thu 15:00-19:00 and Sat 09:00-13:00
# Warsaw time (UTC+1 in November) and needs 12 hours' notice.
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(clock=FixedClock(NOW))) as test_client:
        yield test_client


def test_liveness(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lists_slots_in_utc_with_the_tutors_zone_alongside(client: TestClient) -> None:
    response = client.get(
        "/api/v1/tutors/demo/slots",
        params={"from": "2026-11-17T00:00:00Z", "to": "2026-11-18T00:00:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tutor"] == {
        "slug": "demo",
        "display_name": "Demo Tutor",
        "timezone": "Europe/Warsaw",
        "lesson_minutes": 60,
    }
    assert [slot["start"] for slot in body["slots"]] == [
        "2026-11-17T14:00:00Z",
        "2026-11-17T15:00:00Z",
        "2026-11-17T16:00:00Z",
        "2026-11-17T17:00:00Z",
    ]
    assert body["slots"][0]["end"] == "2026-11-17T15:00:00Z"


def test_slots_inside_the_notice_period_are_not_offered(client: TestClient) -> None:
    # Monday's lessons start 6-9 hours from "now"; the tutor needs 12.
    response = client.get(
        "/api/v1/tutors/demo/slots",
        params={"from": "2026-11-16T00:00:00Z", "to": "2026-11-17T00:00:00Z"},
    )

    assert response.status_code == 200
    assert response.json()["slots"] == []


def test_defaults_to_the_next_two_weeks(client: TestClient) -> None:
    slots = client.get("/api/v1/tutors/demo/slots").json()["slots"]

    # Tue-Thu this week, Saturday, then Mon-Thu and Saturday next week, plus the
    # Monday after: 3 + 1 + 4 + 1 + 1 days of four lessons each.
    assert len(slots) == 40
    assert slots[0]["start"] == "2026-11-17T14:00:00Z"
    assert slots[-1]["start"] == "2026-11-30T17:00:00Z"


def test_accepts_offsets_other_than_utc(client: TestClient) -> None:
    response = client.get(
        "/api/v1/tutors/demo/slots",
        params={"from": "2026-11-17T17:00:00+01:00", "to": "2026-11-17T19:00:00+01:00"},
    )

    assert [slot["start"] for slot in response.json()["slots"]] == [
        "2026-11-17T16:00:00Z",
        "2026-11-17T17:00:00Z",
    ]


def test_unknown_tutor_is_a_404(client: TestClient) -> None:
    response = client.get("/api/v1/tutors/nobody/slots")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-18T00:00:00Z", "2026-11-17T00:00:00Z"),  # reversed
        ("2026-11-17T00:00:00Z", "2027-03-01T00:00:00Z"),  # longer than 62 days
        ("2026-11-17T00:00:00", "2026-11-18T00:00:00"),  # no offset: which midnight?
    ],
)
def test_invalid_windows_are_rejected(client: TestClient, start: str, end: str) -> None:
    response = client.get("/api/v1/tutors/demo/slots", params={"from": start, "to": end})

    assert response.status_code == 422
