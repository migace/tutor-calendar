from __future__ import annotations

import re
from datetime import timedelta

import pytest

from tests.factories import NOW, a_tutor
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_credentials import InMemoryCredentialStore
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.application.errors import InvalidSignInLinkError, NotSignedInError
from tutor_calendar.application.sign_in import (
    Authenticate,
    RequestSignInLink,
    SignedIn,
    SignIn,
    SignOut,
)
from tutor_calendar.domain.scheduling import Tutor

pytestmark = pytest.mark.anyio


class Scenario:
    """Two tutors, an empty mailbox and a clock that tests can move."""

    def __init__(self) -> None:
        self.ewa = a_tutor("ewa")
        self.jan = a_tutor("jan")
        self.tutors = InMemoryTutorRepository([self.ewa, self.jan])
        self.credentials = InMemoryCredentialStore()
        self.mailer = InMemoryMailer()
        self.now = NOW

    @property
    def clock(self) -> FixedClock:
        return FixedClock(self.now)

    async def request_link(self, email: str) -> None:
        use_case = RequestSignInLink(
            self.tutors, self.credentials, self.mailer, self.clock, "https://app.test/"
        )
        await use_case.execute(email)

    def token_from_last_email(self) -> str:
        match = re.search(
            r"https://app\.test/sign-in/verify#token=(\S+)", self.mailer.sent[-1].body
        )
        assert match, self.mailer.sent[-1].body
        return match.group(1)

    async def sign_in(self, token: str) -> SignedIn:
        return await SignIn(self.tutors, self.credentials, self.clock).execute(token)

    async def who_is(self, session_token: str | None) -> Tutor:
        return await Authenticate(self.tutors, self.credentials, self.clock).execute(session_token)

    async def signed_in_as_ewa(self) -> SignedIn:
        await self.request_link("ewa@example.com")
        return await self.sign_in(self.token_from_last_email())


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


async def test_a_tutor_is_sent_a_link_that_signs_them_in(scenario: Scenario) -> None:
    await scenario.request_link("ewa@example.com")

    [email] = scenario.mailer.sent
    assert email.to == "ewa@example.com"
    assert "expires in 15 minutes" in email.body

    signed_in = await scenario.sign_in(scenario.token_from_last_email())

    assert signed_in.tutor == scenario.ewa
    assert signed_in.expires_at == NOW + timedelta(days=30)
    assert await scenario.who_is(signed_in.session_token) == scenario.ewa


async def test_the_address_is_matched_without_regard_to_case(scenario: Scenario) -> None:
    await scenario.request_link("  EWA@Example.COM ")

    # Sent to the address on file, not to whatever was typed.
    assert [email.to for email in scenario.mailer.sent] == ["ewa@example.com"]


async def test_an_unknown_address_gets_no_mail_and_no_error(scenario: Scenario) -> None:
    await scenario.request_link("stranger@example.com")

    assert scenario.mailer.sent == []


async def test_a_link_works_only_once(scenario: Scenario) -> None:
    await scenario.request_link("ewa@example.com")
    token = scenario.token_from_last_email()
    await scenario.sign_in(token)

    with pytest.raises(InvalidSignInLinkError):
        await scenario.sign_in(token)


async def test_a_link_expires_after_fifteen_minutes(scenario: Scenario) -> None:
    await scenario.request_link("ewa@example.com")
    token = scenario.token_from_last_email()

    scenario.now = NOW + timedelta(minutes=15)

    with pytest.raises(InvalidSignInLinkError):
        await scenario.sign_in(token)


async def test_a_link_still_works_just_before_it_expires(scenario: Scenario) -> None:
    await scenario.request_link("ewa@example.com")
    scenario.now = NOW + timedelta(minutes=14, seconds=59)

    assert (await scenario.sign_in(scenario.token_from_last_email())).tutor == scenario.ewa


@pytest.mark.parametrize("token", ["", "made-up", "x" * 43])
async def test_a_made_up_token_is_refused(scenario: Scenario, token: str) -> None:
    await scenario.request_link("ewa@example.com")

    with pytest.raises(InvalidSignInLinkError):
        await scenario.sign_in(token)


async def test_each_request_gets_its_own_link_and_earlier_ones_keep_working(
    scenario: Scenario,
) -> None:
    await scenario.request_link("ewa@example.com")
    first = scenario.token_from_last_email()
    await scenario.request_link("ewa@example.com")
    second = scenario.token_from_last_email()

    assert first != second
    assert (await scenario.sign_in(first)).tutor == scenario.ewa
    assert (await scenario.sign_in(second)).tutor == scenario.ewa


async def test_a_link_signs_in_only_the_tutor_it_was_sent_to(scenario: Scenario) -> None:
    await scenario.request_link("jan@example.com")

    signed_in = await scenario.sign_in(scenario.token_from_last_email())

    assert signed_in.tutor == scenario.jan


async def test_a_session_ends_after_thirty_days(scenario: Scenario) -> None:
    signed_in = await scenario.signed_in_as_ewa()

    scenario.now = NOW + timedelta(days=29, hours=23)
    assert await scenario.who_is(signed_in.session_token) == scenario.ewa

    scenario.now = NOW + timedelta(days=30)
    with pytest.raises(NotSignedInError):
        await scenario.who_is(signed_in.session_token)


async def test_signing_out_ends_that_session_only(scenario: Scenario) -> None:
    laptop = await scenario.signed_in_as_ewa()
    phone = await scenario.signed_in_as_ewa()

    await SignOut(scenario.credentials).execute(laptop.session_token)

    with pytest.raises(NotSignedInError):
        await scenario.who_is(laptop.session_token)
    assert await scenario.who_is(phone.session_token) == scenario.ewa


@pytest.mark.parametrize("session_token", [None, "", "made-up"])
async def test_no_session_means_not_signed_in(
    scenario: Scenario, session_token: str | None
) -> None:
    await scenario.signed_in_as_ewa()

    with pytest.raises(NotSignedInError):
        await scenario.who_is(session_token)


async def test_a_sign_in_token_cannot_be_used_as_a_session(scenario: Scenario) -> None:
    await scenario.request_link("ewa@example.com")

    with pytest.raises(NotSignedInError):
        await scenario.who_is(scenario.token_from_last_email())


async def test_only_digests_of_the_secrets_are_stored(scenario: Scenario) -> None:
    class Recording(InMemoryCredentialStore):
        def __init__(self) -> None:
            super().__init__()
            self.stored: list[str] = []

        async def add_sign_in_token(self, digest, tutor_id, expires_at):  # type: ignore[no-untyped-def]
            self.stored.append(digest)
            await super().add_sign_in_token(digest, tutor_id, expires_at)

        async def add_session(self, digest, tutor_id, expires_at):  # type: ignore[no-untyped-def]
            self.stored.append(digest)
            await super().add_session(digest, tutor_id, expires_at)

    recording = Recording()
    scenario.credentials = recording
    signed_in = await scenario.signed_in_as_ewa()
    link_token = scenario.token_from_last_email()

    assert len(recording.stored) == 2
    assert link_token not in recording.stored
    assert signed_in.session_token not in recording.stored
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in recording.stored)
