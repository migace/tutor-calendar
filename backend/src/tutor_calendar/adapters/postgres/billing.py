from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.adapters.postgres.tables import ledger_entries, outbox
from tutor_calendar.application.background import retry_pause
from tutor_calendar.application.ports import Delivery, Email, OutboxBacklog
from tutor_calendar.domain.billing import EntryKind, LedgerEntry


class PostgresLedger:
    """The ledger in PostgreSQL.

    That entries are permanent and that a lesson is charged once are both
    enforced by the database (a trigger and a unique constraint), not by this
    class, which could not stop other code from writing to the table.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def post(self, entries: Sequence[LedgerEntry]) -> int:
        if not entries:
            return 0
        rows = [
            {
                "id": entry.id,
                "tutor_id": entry.tutor_id,
                "account": entry.account,
                "kind": entry.kind.value,
                "minutes": entry.minutes,
                "note": entry.note,
                "booking_id": entry.booking_id,
                "created_at": entry.created_at,
                "effective_at": entry.effective_at,
            }
            for entry in entries
        ]
        # No conflict target: an entry is skipped whether it repeats an id or
        # charges a lesson that already has a charge.
        statement = (
            pg_insert(ledger_entries)
            .values(rows)
            .on_conflict_do_nothing()
            .returning(ledger_entries.c.id)
        )
        async with self._engine.begin() as connection:
            return len((await connection.execute(statement)).all())

    async def entries(self, tutor_id: UUID, account: str) -> list[LedgerEntry]:
        query = (
            select(ledger_entries)
            .where(ledger_entries.c.tutor_id == tutor_id, ledger_entries.c.account == account)
            .order_by(ledger_entries.c.effective_at, ledger_entries.c.created_at)
        )
        async with self._engine.connect() as connection:
            return [_entry(row) for row in await connection.execute(query)]

    async def balances(self, tutor_id: UUID) -> dict[str, int]:
        query = (
            select(ledger_entries.c.account, func.sum(ledger_entries.c.minutes))
            .where(ledger_entries.c.tutor_id == tutor_id)
            .group_by(ledger_entries.c.account)
        )
        async with self._engine.connect() as connection:
            return {account: int(total) for account, total in await connection.execute(query)}


def _entry(row: Row[Any]) -> LedgerEntry:
    return LedgerEntry(
        id=row.id,
        tutor_id=row.tutor_id,
        account=row.account,
        kind=EntryKind(row.kind),
        minutes=row.minutes,
        note=row.note,
        created_at=row.created_at,
        effective_at=row.effective_at,
        booking_id=row.booking_id,
    )


class PostgresOutbox:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add(self, email: Email, now: datetime) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(insert(outbox).values(outbox_row(email, now)))

    async def deliver_due(
        self, now: datetime, send: Callable[[Email], Awaitable[None]], limit: int
    ) -> Delivery:
        sent = failed = 0
        for _ in range(limit):
            outcome = await self._deliver_one(now, send)
            if outcome is None:
                break
            sent += outcome
            failed += not outcome
        return Delivery(sent, failed)

    async def backlog(self) -> OutboxBacklog:
        unsent = outbox.c.sent_at.is_(None)
        query = select(func.count(), func.min(outbox.c.created_at)).where(unsent)
        async with self._engine.connect() as connection:
            waiting, oldest = (await connection.execute(query)).one()
        return OutboxBacklog(waiting, oldest)

    async def _deliver_one(
        self, now: datetime, send: Callable[[Email], Awaitable[None]]
    ) -> bool | None:
        """Send the oldest waiting message. None when nothing is waiting."""
        claim = (
            select(outbox)
            .where(outbox.c.sent_at.is_(None), outbox.c.available_at <= now)
            .order_by(outbox.c.available_at)
            .limit(1)
            # The row stays locked until this transaction ends, and a second
            # worker skips it instead of waiting, so no message is sent by two
            # workers at once and no worker is held up by another.
            .with_for_update(skip_locked=True)
        )
        async with self._engine.begin() as connection:
            row = (await connection.execute(claim)).one_or_none()
            if row is None:
                return None
            this_row = outbox.c.id == row.id
            try:
                await send(Email(to=row.recipient, subject=row.subject, body=row.body))
            except Exception as error:
                attempts = row.attempts + 1
                await connection.execute(
                    update(outbox)
                    .where(this_row)
                    .values(
                        attempts=attempts,
                        available_at=now + retry_pause(attempts),
                        last_error=f"{type(error).__name__}: {error}"[:500],
                    )
                )
                return False
            # If the process dies between the send above and this commit, the
            # message is sent again later. That is the "at least once" in ADR 0007.
            await connection.execute(update(outbox).where(this_row).values(sent_at=now))
            return True


def outbox_row(email: Email, now: datetime) -> dict[str, Any]:
    return {
        "recipient": email.to,
        "subject": email.subject,
        "body": email.body,
        "created_at": now,
        "available_at": now,
    }
