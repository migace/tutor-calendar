from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from tests.api.conftest import sign_in
from tutor_calendar.adapters.mail import InMemoryMailer

BOOKING = "/api/v1/booking"
WEEK = "/api/v1/me/week"
SERIES = "/api/v1/me/series"
# Tuesday 17 November 2026, 15:00 in Warsaw. The clock stands at Monday 09:00.
FIRST_SLOT = "2026-11-17T14:00:00Z"
TUESDAYS_AT_FIVE = {
    "student_name": "Anna Nowak",
    "student_email": "anna@example.com",
    "first_day": "2026-11-17",
    "start": "17:00",
    "weeks": 3,
}


def book(client: TestClient, start: str = FIRST_SLOT) -> dict[str, Any]:
    response = client.post(
        "/api/v1/tutors/demo/bookings",
        json={"start": start, "student_name": "Anna Nowak", "student_email": "anna@example.com"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def with_token(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def free_starts(client: TestClient) -> list[str]:
    slots = client.get("/api/v1/tutors/demo/slots").json()["slots"]
    return [slot["start"] for slot in slots]


@pytest.fixture
def tutor(client: TestClient, mailer: InMemoryMailer) -> TestClient:
    sign_in(client, mailer)
    return client


class TestManagingABookingWithItsLink:
    def test_the_student_sees_their_lesson_and_the_terms(self, client: TestClient) -> None:
        token = book(client)["manage_token"]

        response = client.get(BOOKING, headers=with_token(token))

        assert response.status_code == 200
        assert response.json() == {
            "tutor_name": "Demo Tutor",
            "timezone": "Europe/Warsaw",
            "start": FIRST_SLOT,
            "end": "2026-11-17T15:00:00Z",
            "student_name": "Anna Nowak",
            "status": "confirmed",
            "cancelled_by": None,
            "cancelled_late": None,
            "free_cancellation_until": "2026-11-16T14:00:00Z",
            "can_cancel": True,
            "late_if_cancelled_now": False,
        }

    def test_cancelling_frees_the_slot(self, client: TestClient) -> None:
        token = book(client)["manage_token"]
        assert FIRST_SLOT not in free_starts(client)

        response = client.delete(BOOKING, headers=with_token(token))

        assert response.status_code == 200
        body = response.json()
        assert (body["status"], body["cancelled_by"], body["cancelled_late"]) == (
            "cancelled",
            "student",
            False,
        )
        assert not body["can_cancel"]
        assert FIRST_SLOT in free_starts(client)

    def test_cancelling_twice_is_a_conflict(self, client: TestClient) -> None:
        token = book(client)["manage_token"]
        client.delete(BOOKING, headers=with_token(token))

        again = client.delete(BOOKING, headers=with_token(token))

        assert again.status_code == 409
        assert again.json() == {"detail": "a cancelled lesson cannot be cancelled"}

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Authorization": "Bearer made-up"},
            {"Authorization": f"Bearer {uuid4().hex}.forged"},
            {"Authorization": "Basic abc"},
        ],
        ids=["no token", "garbage", "forged signature", "wrong scheme"],
    )
    def test_without_a_genuine_token_there_is_nothing_to_see_or_cancel(
        self, client: TestClient, headers: dict[str, str]
    ) -> None:
        book(client)

        assert client.get(BOOKING, headers=headers).status_code == 401
        assert client.delete(BOOKING, headers=headers).status_code == 401
        assert FIRST_SLOT not in free_starts(client)

    def test_knowing_the_booking_id_is_not_enough(self, client: TestClient) -> None:
        booking_id = book(client)["id"].replace("-", "")

        response = client.get(BOOKING, headers=with_token(f"{booking_id}.{booking_id}"))

        assert response.status_code == 401

    def test_a_repeated_booking_request_returns_the_same_token(self, client: TestClient) -> None:
        def send() -> Response:
            return client.post(
                "/api/v1/tutors/demo/bookings",
                json={
                    "start": FIRST_SLOT,
                    "student_name": "Anna",
                    "student_email": "a@example.com",
                },
                headers={"Idempotency-Key": "k" * 20},
            )

        first = send()
        again = send()

        assert again.headers["Idempotency-Replayed"] == "true"
        assert again.json()["manage_token"] == first.json()["manage_token"]


class TestATutorsLessons:
    def lesson_url(self, lesson_id: str, action: str) -> str:
        return f"/api/v1/me/lessons/{lesson_id}/{action}"

    def test_a_tutor_cancels_a_lesson_and_still_sees_it_in_the_week(
        self, tutor: TestClient
    ) -> None:
        lesson_id = book(tutor)["id"]

        response = tutor.post(self.lesson_url(lesson_id, "cancellation"))

        assert response.status_code == 200
        assert (response.json()["status"], response.json()["cancelled_by"]) == (
            "cancelled",
            "tutor",
        )
        [shown] = tutor.get(WEEK).json()["days"][1]["lessons"]
        assert shown["status"] == "cancelled"
        assert FIRST_SLOT in free_starts(tutor)

    def test_a_no_show_cannot_be_recorded_before_the_lesson(self, tutor: TestClient) -> None:
        lesson_id = book(tutor)["id"]

        response = tutor.post(self.lesson_url(lesson_id, "no-show"))

        assert response.status_code == 409
        assert "has not started" in response.json()["detail"]

    @pytest.mark.parametrize("action", ["cancellation", "no-show"])
    def test_lessons_of_other_tutors_and_unknown_lessons_are_not_found(
        self, client: TestClient, mailer: InMemoryMailer, action: str
    ) -> None:
        lesson_id = book(client)["id"]  # a lesson of the demo tutor
        sign_in(client, mailer, "ewa@example.com")

        assert client.post(self.lesson_url(lesson_id, action)).status_code == 404
        assert client.post(self.lesson_url(str(uuid4()), action)).status_code == 404
        assert client.post(self.lesson_url("not-an-id", action)).status_code == 422

    @pytest.mark.parametrize("action", ["cancellation", "no-show"])
    def test_changing_a_lesson_requires_a_session(self, client: TestClient, action: str) -> None:
        lesson_id = book(client)["id"]

        assert client.post(self.lesson_url(lesson_id, action)).status_code == 401


class TestWeeklySeries:
    def start(self, client: TestClient, series_id: str | None = None, **changes: Any) -> Response:
        return client.put(f"{SERIES}/{series_id or uuid4()}", json=TUESDAYS_AT_FIVE | changes)

    def test_a_series_books_a_lesson_each_week(self, tutor: TestClient) -> None:
        series_id = str(uuid4())

        response = self.start(tutor, series_id)

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == series_id
        assert [lesson["start"] for lesson in body["lessons"]] == [
            "2026-11-17T16:00:00Z",
            "2026-11-24T16:00:00Z",
            "2026-12-01T16:00:00Z",
        ]
        assert all(lesson["series_id"] == series_id for lesson in body["lessons"])
        assert body["days_without_lesson"] == []
        assert tutor.get(SERIES).json() == [body]
        assert "2026-11-17T16:00:00Z" not in free_starts(tutor)

    def test_repeating_the_request_changes_nothing(self, tutor: TestClient) -> None:
        series_id = str(uuid4())
        first = self.start(tutor, series_id)

        again = self.start(tutor, series_id)

        assert again.status_code == 200
        assert again.json() == first.json()
        assert len(tutor.get(SERIES).json()) == 1

    def test_a_clash_is_reported_by_day_and_nothing_is_booked(self, tutor: TestClient) -> None:
        book(tutor, "2026-11-24T16:00:00Z")

        response = self.start(tutor)

        assert response.status_code == 409
        assert response.json() == {
            "detail": "some of these lessons overlap lessons that are already booked",
            "conflicts": ["2026-11-24"],
        }
        assert tutor.get(SERIES).json() == []

    def test_the_tutor_can_leave_the_clashing_days_out(self, tutor: TestClient) -> None:
        book(tutor, "2026-11-24T16:00:00Z")

        response = self.start(tutor, skip_conflicts=True)

        assert response.status_code == 200
        assert len(response.json()["lessons"]) == 2
        assert response.json()["days_without_lesson"] == ["2026-11-24"]

    def test_ending_a_series_cancels_its_lessons_without_charging(self, tutor: TestClient) -> None:
        series_id = str(uuid4())
        self.start(tutor, series_id)

        response = tutor.delete(f"{SERIES}/{series_id}")

        assert response.status_code == 200
        assert {lesson["status"] for lesson in response.json()["lessons"]} == {"cancelled"}
        assert {lesson["cancelled_late"] for lesson in response.json()["lessons"]} == {False}
        assert "2026-11-17T16:00:00Z" in free_starts(tutor)
        # The series is history, not gone.
        assert len(tutor.get(SERIES).json()) == 1

    @pytest.mark.parametrize(
        "changes",
        [
            pytest.param({"weeks": 0}, id="no lessons"),
            pytest.param({"weeks": 53}, id="more than a year"),
            pytest.param({"start": "17:00:30"}, id="seconds"),
            pytest.param({"start": "25:00"}, id="not a time"),
            pytest.param({"first_day": "2026-01-06"}, id="entirely in the past"),
            pytest.param({"student_email": "nope"}, id="bad email"),
            pytest.param({"student_name": " "}, id="blank name"),
        ],
    )
    def test_an_impossible_plan_is_rejected(
        self, tutor: TestClient, changes: dict[str, Any]
    ) -> None:
        assert self.start(tutor, **changes).status_code == 422
        assert tutor.get(SERIES).json() == []

    def test_one_tutor_cannot_see_or_end_anothers_series(
        self, client: TestClient, mailer: InMemoryMailer
    ) -> None:
        sign_in(client, mailer)
        series_id = str(uuid4())
        self.start(client, series_id)

        sign_in(client, mailer, "ewa@example.com")

        assert client.get(SERIES).json() == []
        assert client.delete(f"{SERIES}/{series_id}").status_code == 404
        assert self.start(client, series_id).status_code == 422

    @pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
    def test_series_require_a_session(self, client: TestClient, method: str) -> None:
        url = SERIES if method == "GET" else f"{SERIES}/{uuid4()}"

        response = client.request(method, url, json=TUESDAYS_AT_FIVE if method == "PUT" else None)

        assert response.status_code == 401
