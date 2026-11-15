"""In-memory credential store: the fake that fast tests use instead of PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class _Grant:
    tutor_id: UUID
    expires_at: datetime
    used: bool = False


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._sign_in_tokens: dict[str, _Grant] = {}
        self._sessions: dict[str, _Grant] = {}

    async def add_sign_in_token(self, digest: str, tutor_id: UUID, expires_at: datetime) -> None:
        self._sign_in_tokens[digest] = _Grant(tutor_id, expires_at)

    async def redeem_sign_in_token(self, digest: str, now: datetime) -> UUID | None:
        grant = self._sign_in_tokens.get(digest)
        if grant is None or grant.used or grant.expires_at <= now:
            return None
        grant.used = True
        return grant.tutor_id

    async def add_session(self, digest: str, tutor_id: UUID, expires_at: datetime) -> None:
        self._sessions[digest] = _Grant(tutor_id, expires_at)

    async def tutor_for_session(self, digest: str, now: datetime) -> UUID | None:
        grant = self._sessions.get(digest)
        if grant is None or grant.expires_at <= now:
            return None
        return grant.tutor_id

    async def remove_session(self, digest: str) -> None:
        self._sessions.pop(digest, None)
