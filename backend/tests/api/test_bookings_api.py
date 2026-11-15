from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

URL = "/api/v1/tutors/demo/bookings"
KEY = "3f1c8a52-6f6e-4d0b-9a44-1c2d3e4f5a6b"
OTHER_KEY = "9e8d7c6b-5a49-4382-b1a0-0f1e2d3c4b5a"
# Tuesday 17 November 2026, 15:00 in Warsaw.
FIRST_SLOT = "2026-11-17T14:00:00Z"


def book(client: TestClient, key: str | None = KEY, **changes: Any) -> Response:
    body = {"start": FIRST_SLOT, "student_name": "Anna Nowak", "student_email": "anna@example.com"}
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post(URL, json=body | changes, headers=headers)


def free_starts(client: TestClient) -> list[str]:
    slots = client.get("/api/v1/tutors/demo/slots").json()["slots"]
    return [slot["start"] for slot in slots]


def test_booking_a_free_slot(client: TestClient) -> None:
    response = book(client)

    assert response.status_code == 201
    body = response.json()
    assert body["start"] == FIRST_SLOT
    assert body["end"] == "2026-11-17T15:00:00Z"
    assert "Idempotency-Replayed" not in response.headers
    # What the visitor typed stays out of the response; it has no use for it.
    assert set(body) == {"id", "start", "end"}


def test_a_booked_slot_disappears_from_the_listing(client: TestClient) -> None:
    assert FIRST_SLOT in free_starts(client)

    book(client)

    remaining = free_starts(client)
    assert FIRST_SLOT not in remaining
    assert len(remaining) == 39


def test_the_start_may_be_written_in_any_offset(client: TestClient) -> None:
    response = book(client, start="2026-11-17T15:00:00+01:00")

    assert response.status_code == 201
    assert response.json()["start"] == FIRST_SLOT


def test_a_taken_slot_is_a_conflict(client: TestClient) -> None:
    book(client)

    response = book(client, key=OTHER_KEY, student_name="Bartek Lis")

    assert response.status_code == 409
    assert response.json() == {"detail": "this time has just been booked by someone else"}


def test_repeating_a_request_returns_the_same_booking(client: TestClient) -> None:
    first = book(client)

    again = book(client)

    assert again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["Idempotency-Replayed"] == "true"


def test_a_key_cannot_be_reused_for_a_different_request(client: TestClient) -> None:
    book(client)

    response = book(client, start="2026-11-17T15:00:00Z")

    assert response.status_code == 422
    assert "Idempotency-Key" in response.json()["detail"]
    assert "2026-11-17T15:00:00Z" in free_starts(client)


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(None, id="missing"),
        pytest.param("short", id="too short to be random"),
        pytest.param("k" * 65, id="too long"),
        pytest.param("not a token, has spaces", id="unexpected characters"),
    ],
)
def test_a_proper_idempotency_key_is_required(client: TestClient, key: str | None) -> None:
    response = book(client, key=key)

    assert response.status_code == 422
    assert FIRST_SLOT in free_starts(client)


@pytest.mark.parametrize(
    "start",
    [
        pytest.param("2026-11-17T14:30:00Z", id="between two slots"),
        pytest.param("2026-11-20T14:00:00Z", id="a day the tutor does not teach"),
        pytest.param("2026-11-16T14:00:00Z", id="inside the notice period"),
        pytest.param("2026-11-10T14:00:00Z", id="in the past"),
    ],
)
def test_a_time_that_is_not_offered_is_a_conflict(client: TestClient, start: str) -> None:
    response = book(client, start=start)

    assert response.status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"student_name": "   "}, id="blank name"),
        pytest.param({"student_name": "x" * 121}, id="name too long"),
        pytest.param({"student_email": "not-an-address"}, id="malformed email"),
        pytest.param({"student_email": ""}, id="empty email"),
        pytest.param({"start": "2026-11-17T15:00:00"}, id="start without an offset"),
        pytest.param({"start": "next tuesday"}, id="start that is not a date"),
    ],
)
def test_invalid_details_are_rejected(client: TestClient, changes: dict[str, str]) -> None:
    response = book(client, **changes)

    assert response.status_code == 422
    assert FIRST_SLOT in free_starts(client)


def test_surrounding_whitespace_in_the_name_is_not_a_different_request(client: TestClient) -> None:
    first = book(client)

    again = book(client, student_name="  Anna   Nowak ")

    assert again.status_code == 201
    assert again.json() == first.json()


def test_unknown_tutor_is_a_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tutors/nobody/bookings",
        json={"start": FIRST_SLOT, "student_name": "Anna", "student_email": "anna@example.com"},
        headers={"Idempotency-Key": KEY},
    )

    assert response.status_code == 404
