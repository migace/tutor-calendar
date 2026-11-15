from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import sign_in
from tutor_calendar.adapters.mail import InMemoryMailer

WEEK = "/api/v1/me/week"
AVAILABILITY = "/api/v1/me/availability"
# Tuesday 17 November 2026, 15:00 in Warsaw.
FIRST_SLOT = "2026-11-17T14:00:00Z"

MONDAY_MORNING = {"weekday": 0, "start": "09:00", "end": "12:00"}


@pytest.fixture
def tutor(client: TestClient, mailer: InMemoryMailer) -> TestClient:
    """A client signed in as the demo tutor."""
    sign_in(client, mailer)
    return client


def book(client: TestClient, start: str, key: str, slug: str = "demo") -> None:
    response = client.post(
        f"/api/v1/tutors/{slug}/bookings",
        json={"start": start, "student_name": "Anna Nowak", "student_email": "anna@example.com"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text


def test_the_week_lists_lessons_with_who_booked_them(tutor: TestClient) -> None:
    book(tutor, FIRST_SLOT, "k" * 16)

    week = tutor.get(WEEK).json()

    assert week["timezone"] == "Europe/Warsaw"
    assert (week["previous"], week["today"], week["next"]) == (
        "2026-11-09",
        "2026-11-16",
        "2026-11-23",
    )
    assert [day["date"] for day in week["days"]] == [f"2026-11-{n}" for n in range(16, 23)]
    [lesson] = week["days"][1]["lessons"]
    assert lesson == {
        "id": lesson["id"],
        "start": FIRST_SLOT,
        "end": "2026-11-17T15:00:00Z",
        "student_name": "Anna Nowak",
        "student_email": "anna@example.com",
    }
    assert sum(len(day["lessons"]) for day in week["days"]) == 1


def test_any_day_selects_its_week(tutor: TestClient) -> None:
    week = tutor.get(WEEK, params={"date": "2026-11-29"}).json()

    assert week["days"][0]["date"] == "2026-11-23"
    assert week["days"][6]["date"] == "2026-11-29"
    assert week["today"] == "2026-11-16"


def test_a_malformed_date_is_rejected(tutor: TestClient) -> None:
    assert tutor.get(WEEK, params={"date": "next week"}).status_code == 422


def test_a_tutor_sees_only_their_own_lessons(client: TestClient, mailer: InMemoryMailer) -> None:
    # Ewa teaches 45-minute lessons on Monday mornings, with 24 hours' notice.
    book(client, "2026-11-23T07:00:00Z", "e" * 16, slug="ewa")
    book(client, FIRST_SLOT, "d" * 16)

    sign_in(client, mailer, "ewa@example.com")
    this_week = client.get(WEEK).json()
    next_week = client.get(WEEK, params={"date": "2026-11-23"}).json()

    assert all(day["lessons"] == [] for day in this_week["days"])
    assert [lesson["start"] for lesson in next_week["days"][0]["lessons"]] == [
        "2026-11-23T07:00:00Z"
    ]


def test_availability_shows_the_weekly_hours(tutor: TestClient) -> None:
    availability = tutor.get(AVAILABILITY).json()

    assert availability["timezone"] == "Europe/Warsaw"
    assert availability["lesson_minutes"] == 60
    assert availability["rules"][0] == {"weekday": 0, "start": "15:00:00", "end": "19:00:00"}
    assert [rule["weekday"] for rule in availability["rules"]] == [0, 1, 2, 3, 5]


def test_changing_the_hours_changes_what_visitors_are_offered(tutor: TestClient) -> None:
    response = tutor.put(AVAILABILITY, json={"rules": [MONDAY_MORNING]})

    assert response.status_code == 200
    assert response.json()["rules"] == [{"weekday": 0, "start": "09:00:00", "end": "12:00:00"}]
    assert tutor.get(AVAILABILITY).json() == response.json()
    slots = tutor.get("/api/v1/tutors/demo/slots").json()["slots"]
    # Monday 23 and 30 November, 09:00-12:00 in Warsaw.
    assert [slot["start"] for slot in slots] == [
        f"2026-11-{day}T{hour:02}:00:00Z" for day in (23, 30) for hour in (8, 9, 10)
    ]


def test_changing_the_hours_leaves_booked_lessons_alone(tutor: TestClient) -> None:
    book(tutor, FIRST_SLOT, "k" * 16)

    tutor.put(AVAILABILITY, json={"rules": [MONDAY_MORNING]})

    assert len(tutor.get(WEEK).json()["days"][1]["lessons"]) == 1


def test_one_tutor_cannot_change_anothers_hours(client: TestClient, mailer: InMemoryMailer) -> None:
    sign_in(client, mailer, "ewa@example.com")

    client.put(AVAILABILITY, json={"rules": []})

    assert client.get("/api/v1/tutors/ewa/slots").json()["slots"] == []
    assert len(client.get("/api/v1/tutors/demo/slots").json()["slots"]) == 40


@pytest.mark.parametrize(
    "rules",
    [
        pytest.param(
            [MONDAY_MORNING, {"weekday": 0, "start": "11:00", "end": "13:00"}], id="overlapping"
        ),
        pytest.param(
            [{"weekday": 0, "start": "12:00", "end": "09:00"}], id="ends before it starts"
        ),
        pytest.param([{"weekday": 0, "start": "09:00", "end": "09:00"}], id="empty"),
        pytest.param([{"weekday": 7, "start": "09:00", "end": "12:00"}], id="no such weekday"),
        pytest.param([{"weekday": 0, "start": "09:00:30", "end": "12:00"}], id="seconds"),
        pytest.param([{"weekday": 0, "start": "09:00+01:00", "end": "12:00"}], id="with an offset"),
        pytest.param([{"weekday": 0, "start": "nine", "end": "12:00"}], id="not a time"),
    ],
)
def test_impossible_hours_are_rejected_and_nothing_changes(
    tutor: TestClient, rules: list[dict[str, Any]]
) -> None:
    before = tutor.get(AVAILABILITY).json()

    response = tutor.put(AVAILABILITY, json={"rules": rules})

    assert response.status_code == 422
    assert tutor.get(AVAILABILITY).json() == before


def test_overlapping_hours_are_explained(tutor: TestClient) -> None:
    response = tutor.put(
        AVAILABILITY,
        json={"rules": [MONDAY_MORNING, {"weekday": 0, "start": "11:00", "end": "13:00"}]},
    )

    assert response.json() == {"detail": "rules overlap on Monday"}
