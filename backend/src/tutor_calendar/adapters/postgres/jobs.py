from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.adapters.postgres.tables import background_jobs


class PostgresJobLog:
    """When each background job last finished, one row per job. See ADR 0011."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record_success(self, job: str, at: datetime) -> None:
        record = pg_insert(background_jobs).values(name=job, last_succeeded_at=at)
        # Decided by the database, so two workers reporting at once cannot
        # leave the earlier of their two times behind.
        record = record.on_conflict_do_update(
            index_elements=[background_jobs.c.name],
            set_={
                "last_succeeded_at": func.greatest(
                    background_jobs.c.last_succeeded_at, record.excluded.last_succeeded_at
                )
            },
        )
        async with self._engine.begin() as connection:
            await connection.execute(record)

    async def last_successes(self) -> dict[str, datetime]:
        async with self._engine.connect() as connection:
            rows = await connection.execute(select(background_jobs))
            return {row.name: row.last_succeeded_at for row in rows}
