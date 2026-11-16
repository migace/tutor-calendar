"""Links that carry their own proof of who may use them.

A token is a small payload followed by an HMAC of it under a server secret.
Nothing is stored: any server holding the secret can check a token, and the
token for a given thing is always the same, so a repeated booking request gets
the link the first attempt got.

Each kind of link is signed for its own purpose, so a token for managing a
booking is worthless as a token for reading a statement, and the other way
round.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from uuid import UUID


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes | None:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError:
        return None


class _Signer:
    def __init__(self, secret: str, purpose: str) -> None:
        if len(secret) < 32:
            raise ValueError("the signing secret must be at least 32 characters")
        self._key = secret.encode()
        self._purpose = purpose.encode()

    def sign(self, payload: bytes) -> str:
        digest = hmac.new(self._key, self._purpose + b"\0" + payload, hashlib.sha256).digest()
        return _b64(digest)

    def verifies(self, payload: bytes, signature: str) -> bool:
        # Constant-time comparison, so response times say nothing about how
        # much of a guessed signature was right.
        return hmac.compare_digest(signature, self.sign(payload))


class HmacManageLinks:
    """Tokens that let a student view and cancel one booking."""

    def __init__(self, secret: str) -> None:
        self._signer = _Signer(secret, "manage-booking")

    @classmethod
    def with_random_secret(cls) -> HmacManageLinks:
        """For when no secret is configured: links work until the process restarts."""
        return cls(secrets.token_urlsafe(32))

    def token_for(self, booking_id: UUID) -> str:
        return f"{booking_id.hex}.{self._signer.sign(booking_id.bytes)}"

    def booking_id_in(self, token: str) -> UUID | None:
        hex_id, dot, signature = token.partition(".")
        try:
            booking_id = UUID(hex=hex_id)
        except ValueError:
            return None
        if not dot or not self._signer.verifies(booking_id.bytes, signature):
            return None
        return booking_id


class HmacStatementLinks:
    """Tokens that let a parent read one student's statement with one tutor."""

    def __init__(self, secret: str) -> None:
        self._signer = _Signer(secret, "read-statement")

    def token_for(self, tutor_id: UUID, account: str) -> str:
        payload = tutor_id.bytes + account.encode()
        return f"{_b64(payload)}.{self._signer.sign(payload)}"

    def account_in(self, token: str) -> tuple[UUID, str] | None:
        encoded, dot, signature = token.partition(".")
        payload = _unb64(encoded)
        if not dot or payload is None or len(payload) <= 16:
            return None
        if not self._signer.verifies(payload, signature):
            return None
        try:
            return UUID(bytes=payload[:16]), payload[16:].decode()
        except ValueError:
            return None
