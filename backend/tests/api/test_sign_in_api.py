from __future__ import annotations

from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import sign_in, token_in
from tutor_calendar.adapters.mail import InMemoryMailer

LINKS = "/api/v1/auth/links"
SESSION = "/api/v1/auth/session"
ME = "/api/v1/me"


def test_a_tutor_signs_in_with_the_link_from_their_email(
    client: TestClient, mailer: InMemoryMailer
) -> None:
    assert client.get(ME).status_code == 401

    requested = client.post(LINKS, json={"email": "demo@example.com"})
    assert requested.status_code == 202
    assert [email.to for email in mailer.sent] == ["demo@example.com"]
    assert "http://localhost:5173/sign-in/verify#token=" in mailer.sent[0].body

    signed_in = client.post(SESSION, json={"token": token_in(mailer)})

    assert signed_in.status_code == 200
    profile = {
        "slug": "demo",
        "display_name": "Demo Tutor",
        "email": "demo@example.com",
        "timezone": "Europe/Warsaw",
        "lesson_minutes": 60,
    }
    assert signed_in.json() == profile
    assert client.get(ME).json() == profile


def test_the_session_cookie_is_locked_down(client: TestClient, mailer: InMemoryMailer) -> None:
    client.post(LINKS, json={"email": "demo@example.com"})

    response = client.post(SESSION, json={"token": token_in(mailer)})

    cookie = SimpleCookie(response.headers["set-cookie"])["tc_session"]
    assert cookie["httponly"]  # scripts cannot read it
    assert cookie["secure"]  # never sent over plain HTTP
    assert cookie["samesite"] == "lax"  # not sent on requests made by other sites
    assert cookie["path"] == "/"
    assert cookie["max-age"] == str(30 * 24 * 60 * 60)
    # The session token never appears in a response body.
    assert cookie.value not in response.text


def test_asking_for_a_link_does_not_reveal_who_has_an_account(
    client: TestClient, mailer: InMemoryMailer
) -> None:
    known = client.post(LINKS, json={"email": "demo@example.com"})
    unknown = client.post(LINKS, json={"email": "stranger@example.com"})

    assert (known.status_code, known.content) == (unknown.status_code, unknown.content)
    assert len(mailer.sent) == 1


def test_a_link_cannot_be_used_twice(client: TestClient, mailer: InMemoryMailer) -> None:
    client.post(LINKS, json={"email": "demo@example.com"})
    token = token_in(mailer)
    client.post(SESSION, json={"token": token})
    client.cookies.clear()

    again = client.post(SESSION, json={"token": token})

    assert again.status_code == 401
    assert "set-cookie" not in again.headers
    assert client.get(ME).status_code == 401


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"token": "a-token-that-was-never-issued-by-anyone"}, 401),
        ({"token": "short"}, 422),
        ({"token": "x" * 201}, 422),
        ({}, 422),
    ],
)
def test_a_bad_token_does_not_sign_anyone_in(
    client: TestClient, body: dict[str, str], status: int
) -> None:
    response = client.post(SESSION, json=body)

    assert response.status_code == status
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("email", ["not-an-address", "", "a@b"])
def test_a_link_request_needs_a_real_address(
    client: TestClient, mailer: InMemoryMailer, email: str
) -> None:
    assert client.post(LINKS, json={"email": email}).status_code == 422
    assert mailer.sent == []


def test_signing_out_ends_the_session(client: TestClient, mailer: InMemoryMailer) -> None:
    sign_in(client, mailer)
    stolen = client.cookies["tc_session"]

    response = client.delete(SESSION)

    assert response.status_code == 204
    assert "tc_session" not in client.cookies
    assert client.get(ME).status_code == 401
    # Gone on the server too, not only forgotten by this browser.
    assert client.get(ME, headers={"Cookie": f"tc_session={stolen}"}).status_code == 401


def test_signing_out_when_not_signed_in_is_harmless(client: TestClient) -> None:
    assert client.delete(SESSION).status_code == 204


def test_a_made_up_session_cookie_is_not_a_session(client: TestClient) -> None:
    client.cookies.set("tc_session", "made-up")

    assert client.get(ME).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/me/week"),
        ("GET", "/api/v1/me/availability"),
        ("PUT", "/api/v1/me/availability"),
    ],
)
def test_every_panel_endpoint_requires_a_session(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={"rules": []} if method == "PUT" else None)

    assert response.status_code == 401
    assert response.json() == {"detail": "sign in to continue"}


def test_the_public_booking_page_needs_no_session(client: TestClient) -> None:
    assert client.get("/api/v1/tutors/demo/slots").status_code == 200


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded"])
def test_only_json_is_accepted_which_other_sites_cannot_send_unasked(
    client: TestClient, mailer: InMemoryMailer, content_type: str
) -> None:
    # A page on another site can post these two types without a CORS preflight.
    # If the API parsed them as JSON, that page could act for a signed-in tutor.
    response = client.post(
        LINKS, content='{"email": "demo@example.com"}', headers={"Content-Type": content_type}
    )

    assert response.status_code == 422
    assert mailer.sent == []


def test_other_origins_are_not_allowed_to_send_the_session_cookie(client: TestClient) -> None:
    preflight = {"Access-Control-Request-Method": "PUT"}

    stranger = client.options(ME, headers={"Origin": "https://evil.example", **preflight})
    own = client.options(ME, headers={"Origin": "http://localhost:5173", **preflight})

    assert "access-control-allow-origin" not in stranger.headers
    assert own.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert own.headers["access-control-allow-credentials"] == "true"
