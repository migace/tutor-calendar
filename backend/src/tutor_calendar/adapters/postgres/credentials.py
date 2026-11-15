from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.adapters.postgres.tables import sessions, sign_in_tokens


class PostgresCredentialStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add_sign_in_token(self, digest: str, tutor_id: UUID, expires_at: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(sign_in_tokens).values(
                    digest=digest, tutor_id=tutor_id, expires_at=expires_at
                )
            )

    async def redeem_sign_in_token(self, digest: str, now: datetime) -> UUID | None:
        # One UPDATE both checks the token and uses it up. Two requests with the
        # same token cannot both match the WHERE clause: the second waits for
        # the first, then sees used_at already set.
        statement = (
            update(sign_in_tokens)
            .where(
                sign_in_tokens.c.digest == digest,
                sign_in_tokens.c.used_at.is_(None),
                sign_in_tokens.c.expires_at > now,
            )
            .values(used_at=now)
            .returning(sign_in_tokens.c.tutor_id)
        )
        async with self._engine.begin() as connection:
            tutor_id: UUID | None = (await connection.execute(statement)).scalar_one_or_none()
            return tutor_id

    async def add_session(self, digest: str, tutor_id: UUID, expires_at: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(sessions).values(digest=digest, tutor_id=tutor_id, expires_at=expires_at)
            )

    async def tutor_for_session(self, digest: str, now: datetime) -> UUID | None:
        query = select(sessions.c.tutor_id).where(
            sessions.c.digest == digest, sessions.c.expires_at > now
        )
        async with self._engine.connect() as connection:
            tutor_id: UUID | None = (await connection.execute(query)).scalar_one_or_none()
            return tutor_id

    async def remove_session(self, digest: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(delete(sessions).where(sessions.c.digest == digest))
