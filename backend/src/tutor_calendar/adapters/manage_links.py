"""Manage tokens as signed booking ids.

A token is the booking's id followed by an HMAC of it under a server secret.
Nothing is stored: any server holding the secret can check a token, and the
token for a booking is always the same, so a repeated booking request gets the
link the first attempt got.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from uuid import UUID


class HmacManageLinks:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("the signing secret must be at least 32 characters")
        self._key = secret.encode()

    @classmethod
    def with_random_secret(cls) -> HmacManageLinks:
        """For when no secret is configured: links work until the process restarts."""
        return cls(secrets.token_urlsafe(32))

    def token_for(self, booking_id: UUID) -> str:
        return f"{booking_id.hex}.{self._signature(booking_id)}"

    def booking_id_in(self, token: str) -> UUID | None:
        hex_id, dot, signature = token.partition(".")
        try:
            booking_id = UUID(hex=hex_id)
        except ValueError:
            return None
        # Constant-time comparison, so response times say nothing about how
        # much of a guessed signature was right.
        if not dot or not hmac.compare_digest(signature, self._signature(booking_id)):
            return None
        return booking_id

    def _signature(self, booking_id: UUID) -> str:
        digest = hmac.new(self._key, booking_id.bytes, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
