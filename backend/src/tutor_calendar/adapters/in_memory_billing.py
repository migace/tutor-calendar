"""In-memory ledger and outbox: the fakes that fast tests use instead of PostgreSQL."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tutor_calendar.application.background import retry_pause
from tutor_calendar.application.ports import Delivery, Email
from tutor_calendar.domain.billing import LedgerEntry


class InMemoryLedger:
    def __init__(self) -> None:
        self._entries: dict[UUID, LedgerEntry] = {}

    async def post(self, entries: Sequence[LedgerEntry]) -> int:
        added = 0
        for entry in entries:
            charged = {each.booking_id for each in self._entries.values() if each.booking_id}
            if entry.id in self._entries or entry.booking_id in charged:
                continue
            self._entries[entry.id] = entry
            added += 1
        return added

    async def entries(self, tutor_id: UUID, account: str) -> list[LedgerEntry]:
        return sorted(
            (
                entry
                for entry in self._entries.values()
                if entry.tutor_id == tutor_id and entry.account == account
            ),
            key=lambda entry: (entry.effective_at, entry.created_at),
        )

    async def balances(self, tutor_id: UUID) -> dict[str, int]:
        totals: dict[str, int] = {}
        for entry in self._entries.values():
            if entry.tutor_id == tutor_id:
                totals[entry.account] = totals.get(entry.account, 0) + entry.minutes
        return totals


@dataclass(slots=True)
class _Queued:
    email: Email
    available_at: datetime
    attempts: int = 0
    sent: bool = False
    # Taken by a delivery that has not finished. Stands in for the row lock
    # the real outbox holds while a message is being sent.
    claimed: bool = False


class InMemoryOutbox:
    def __init__(self) -> None:
        self._queue: list[_Queued] = []

    @property
    def waiting(self) -> list[Email]:
        """Messages not sent yet, oldest first."""
        return [queued.email for queued in self._queue if not queued.sent]

    def put(self, email: Email, now: datetime) -> None:
        self._queue.append(_Queued(email, now))

    async def add(self, email: Email, now: datetime) -> None:
        self.put(email, now)

    async def deliver_due(
        self, now: datetime, send: Callable[[Email], Awaitable[None]], limit: int
    ) -> Delivery:
        due = [
            queued
            for queued in self._queue
            if not queued.sent and not queued.claimed and queued.available_at <= now
        ][:limit]
        # Claimed before the first ``await``, so a delivery running alongside
        # this one cannot pick the same messages.
        for queued in due:
            queued.claimed = True
        sent = failed = 0
        for queued in due:
            try:
                await send(queued.email)
            except Exception:
                queued.attempts += 1
                queued.available_at = now + retry_pause(queued.attempts)
                failed += 1
            else:
                queued.sent = True
                sent += 1
            finally:
                queued.claimed = False
        return Delivery(sent, failed)
