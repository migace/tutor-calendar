from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from tests.api.conftest import sign_in
from tutor_calendar.adapters.mail import InMemoryMailer

STUDENTS = "/api/v1/me/students"
SHARED = "/api/v1/statement"
ANNA = "anna@example.com"
FIRST_SLOT = "2026-11-17T14:00:00Z"


@pytest.fixture
def tutor(client: TestClient, mailer: InMemoryMailer) -> TestClient:
    sign_in(client, mailer)
    return client


def record(
    client: TestClient,
    minutes: int = 600,
    kind: str = "purchase",
    note: str = "Package of 10",
    entry_id: str | None = None,
    email: str = ANNA,
) -> Response:
    return client.put(
        f"{STUDENTS}/{email}/entries/{entry_id or uuid4()}",
        json={"kind": kind, "minutes": minutes, "note": note},
    )


def statement(client: TestClient, email: str = ANNA, **params: str) -> dict[str, Any]:
    response = client.get(f"{STUDENTS}/{email}/statement", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_package_shows_on_the_account_and_on_the_statement(tutor: TestClient) -> None:
    response = record(tutor)

    assert response.status_code == 200
    entry = response.json()
    assert (entry["kind"], entry["minutes"], entry["note"], entry["lesson_id"]) == (
        "purchase",
        600,
        "Package of 10",
        None,
    )
    assert tutor.get(STUDENTS).json() == [{"email": ANNA, "name": None, "balance_minutes": 600}]

    november = statement(tutor)
    assert (november["month"], november["previous"], november["next"]) == (
        "2026-11-01",
        "2026-10-01",
        "2026-12-01",
    )
    assert (november["opening_minutes"], november["closing_minutes"]) == (0, 600)
    assert november["balance_minutes"] == 600
    assert november["entries"] == [entry]
    assert (november["tutor_name"], november["timezone"]) == ("Demo Tutor", "Europe/Warsaw")


def test_recording_the_same_entry_twice_credits_it_once(tutor: TestClient) -> None:
    entry_id = str(uuid4())

    first = record(tutor, entry_id=entry_id)
    again = record(tutor, entry_id=entry_id)

    assert again.status_code == 200
    assert again.json() == first.json()
    assert tutor.get(STUDENTS).json()[0]["balance_minutes"] == 600


def test_an_entry_id_cannot_be_reused_for_something_else(tutor: TestClient) -> None:
    entry_id = str(uuid4())
    record(tutor, entry_id=entry_id)

    response = record(tutor, minutes=6000, entry_id=entry_id)

    assert response.status_code == 422
    assert tutor.get(STUDENTS).json()[0]["balance_minutes"] == 600


def test_a_correction_is_a_new_entry_and_the_old_one_stays(tutor: TestClient) -> None:
    record(tutor)

    correction = record(tutor, minutes=-300, kind="adjustment", note="It was 5 hours, not 10")

    assert correction.status_code == 200
    november = statement(tutor)
    assert [entry["minutes"] for entry in november["entries"]] == [600, -300]
    assert november["closing_minutes"] == 300


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"kind": "purchase", "minutes": 0}, id="nothing"),
        pytest.param({"kind": "purchase", "minutes": -60}, id="a negative purchase"),
        pytest.param({"kind": "adjustment", "minutes": -60, "note": " "}, id="no reason given"),
        pytest.param({"kind": "lesson", "minutes": -60, "note": "x"}, id="a charge by hand"),
        pytest.param({"kind": "purchase", "minutes": 60_001}, id="an absurd amount"),
        pytest.param({"kind": "purchase", "minutes": 60, "note": "x" * 201}, id="a long note"),
        pytest.param({"kind": "purchase", "minutes": 1.5}, id="a fraction of a minute"),
    ],
)
def test_entries_that_make_no_sense_are_rejected(tutor: TestClient, body: dict[str, Any]) -> None:
    response = tutor.put(f"{STUDENTS}/{ANNA}/entries/{uuid4()}", json=body)

    assert response.status_code == 422
    assert tutor.get(STUDENTS).json() == []


def test_a_student_with_a_lesson_is_listed_by_name_before_they_buy_anything(
    tutor: TestClient,
) -> None:
    tutor.post(
        "/api/v1/tutors/demo/bookings",
        json={
            "start": FIRST_SLOT,
            "student_name": "Anna Nowak",
            "student_email": "Anna@Example.com",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )

    assert tutor.get(STUDENTS).json() == [
        {"email": ANNA, "name": "Anna Nowak", "balance_minutes": 0}
    ]
    assert statement(tutor)["student_name"] == "Anna Nowak"


def test_any_day_selects_its_month(tutor: TestClient) -> None:
    record(tutor)

    october = statement(tutor, month="2026-10-17")
    december = statement(tutor, month="2026-12-31")

    assert (october["month"], october["entries"], october["closing_minutes"]) == (
        "2026-10-01",
        [],
        0,
    )
    assert (december["month"], december["opening_minutes"]) == ("2026-12-01", 600)
    assert tutor.get(f"{STUDENTS}/{ANNA}/statement", params={"month": "soon"}).status_code == 422


def test_a_parent_reads_the_statement_with_the_shared_link(
    client: TestClient, mailer: InMemoryMailer
) -> None:
    sign_in(client, mailer)
    record(client)
    for_the_tutor = statement(client)
    token = for_the_tutor["share_token"]
    client.cookies.clear()  # the parent has no session

    response = client.get(SHARED, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    # The same statement, minus the token: a parent cannot mint further links.
    assert response.json() == for_the_tutor | {"share_token": None}
    december = client.get(
        SHARED, params={"month": "2026-12-01"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert december.json()["opening_minutes"] == 600


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer made-up"}, {"Authorization": "Bearer YWJj.signature"}],
    ids=["no token", "garbage", "forged"],
)
def test_without_a_genuine_token_there_is_no_statement(
    tutor: TestClient, headers: dict[str, str]
) -> None:
    record(tutor)
    tutor.cookies.clear()

    assert tutor.get(SHARED, headers=headers).status_code == 401


def test_a_link_for_managing_a_booking_does_not_open_a_statement(tutor: TestClient) -> None:
    booked = tutor.post(
        "/api/v1/tutors/demo/bookings",
        json={"start": FIRST_SLOT, "student_name": "Anna", "student_email": ANNA},
        headers={"Idempotency-Key": uuid4().hex},
    ).json()

    response = tutor.get(SHARED, headers={"Authorization": f"Bearer {booked['manage_token']}"})

    assert response.status_code == 401


def test_tutors_do_not_see_each_others_accounts(client: TestClient, mailer: InMemoryMailer) -> None:
    sign_in(client, mailer)
    record(client)
    token = statement(client)["share_token"]

    sign_in(client, mailer, "ewa@example.com")

    assert client.get(STUDENTS).json() == []
    assert client.get(f"{STUDENTS}/{ANNA}/statement").status_code == 404
    # Ewa's own account for the same address is a different account.
    record(client, minutes=90)
    assert statement(client)["balance_minutes"] == 90
    assert statement(client)["share_token"] != token


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", STUDENTS),
        ("GET", f"{STUDENTS}/{ANNA}/statement"),
        ("PUT", f"{STUDENTS}/{ANNA}/entries/{uuid4()}"),
    ],
)
def test_accounts_require_a_session(client: TestClient, method: str, path: str) -> None:
    body = {"kind": "purchase", "minutes": 60} if method == "PUT" else None

    assert client.request(method, path, json=body).status_code == 401
