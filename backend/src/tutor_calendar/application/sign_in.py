"""Signing a tutor in with a link sent to their e-mail address. See ADR 0005."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from tutor_calendar.application.errors import InvalidSignInLinkError, NotSignedInError
from tutor_calendar.application.ports import (
    Clock,
    CredentialStore,
    Email,
    Mailer,
    TutorRepository,
)
from tutor_calendar.domain.scheduling import Tutor

LINK_LIFETIME = timedelta(minutes=15)
SESSION_LIFETIME = timedelta(days=30)


def _new_secret() -> str:
    # 256 bits from the operating system. Unlike a password it cannot be
    # guessed, which is why a plain fast hash is enough when storing it.
    return secrets.token_urlsafe(32)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class RequestSignInLink:
    """Send a sign-in link to a tutor's address.

    Returns nothing and behaves the same whether or not the address belongs to
    a tutor, so the endpoint cannot be used to find out who has an account.
    """

    def __init__(
        self,
        tutors: TutorRepository,
        credentials: CredentialStore,
        mailer: Mailer,
        clock: Clock,
        public_url: str,
    ) -> None:
        self._tutors = tutors
        self._credentials = credentials
        self._mailer = mailer
        self._clock = clock
        self._public_url = public_url.rstrip("/")

    async def execute(self, email: str) -> None:
        tutor = await self._tutors.get_by_email(email)
        if tutor is None:
            return

        token = _new_secret()
        await self._credentials.add_sign_in_token(
            _digest(token), tutor.id, self._clock.now() + LINK_LIFETIME
        )
        # The token travels in the fragment, which browsers do not send to
        # servers: it stays out of access logs and Referer headers.
        link = f"{self._public_url}/sign-in/verify#token={token}"
        minutes = LINK_LIFETIME // timedelta(minutes=1)
        await self._mailer.send(
            Email(
                # The address on file, not the one typed: they may differ in case.
                to=tutor.email,
                subject="Your sign-in link for Tutor Calendar",
                body=(
                    f"Hello {tutor.display_name},\n\n"
                    f"Open this link to sign in. It works once and expires in "
                    f"{minutes} minutes.\n\n{link}\n\n"
                    "If you did not ask for it, you can ignore this message."
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class SignedIn:
    tutor: Tutor
    # Handed to the browser as a cookie. Only its digest is stored.
    session_token: str
    expires_at: datetime


class SignIn:
    """Trade the token from a sign-in link for a session."""

    def __init__(self, tutors: TutorRepository, credentials: CredentialStore, clock: Clock) -> None:
        self._tutors = tutors
        self._credentials = credentials
        self._clock = clock

    async def execute(self, token: str) -> SignedIn:
        now = self._clock.now()
        tutor_id = await self._credentials.redeem_sign_in_token(_digest(token), now)
        tutor = None if tutor_id is None else await self._tutors.get_by_id(tutor_id)
        if tutor is None:
            raise InvalidSignInLinkError

        session_token = _new_secret()
        expires_at = now + SESSION_LIFETIME
        await self._credentials.add_session(_digest(session_token), tutor.id, expires_at)
        return SignedIn(tutor, session_token, expires_at)


class Authenticate:
    """Find the tutor a session token belongs to."""

    def __init__(self, tutors: TutorRepository, credentials: CredentialStore, clock: Clock) -> None:
        self._tutors = tutors
        self._credentials = credentials
        self._clock = clock

    async def execute(self, session_token: str | None) -> Tutor:
        if not session_token:
            raise NotSignedInError
        tutor_id = await self._credentials.tutor_for_session(
            _digest(session_token), self._clock.now()
        )
        tutor = None if tutor_id is None else await self._tutors.get_by_id(tutor_id)
        if tutor is None:
            raise NotSignedInError
        return tutor


class SignOut:
    def __init__(self, credentials: CredentialStore) -> None:
        self._credentials = credentials

    async def execute(self, session_token: str | None) -> None:
        if session_token:
            await self._credentials.remove_session(_digest(session_token))
