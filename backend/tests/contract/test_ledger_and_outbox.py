"""The ledger, the outbox and the parts of bookings that feed them, against each implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import FIRST_SLOT, NOW, a_booking, a_tutor
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger, InMemoryOutbox
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.postgres.billing import PostgresLedger, PostgresOutbox
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.application.ports import (
    Email,
    Ledger,
    LessonStore,
    Outbox,
    OutboxBacklog,
)
from tutor_calendar.domain.billing import EntryKind, LedgerEntry, charge_for
from tutor_calendar.domain.scheduling import Actor, AlwaysFree, Student, Tutor

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
AFTER = FIRST_SLOT + 2 * HOUR
HELLO = Email("anna@example.com", "Hello", "A message")


@dataclass
class Stores:
    bookings: LessonStore
    ledger: Ledger
    outbox: Outbox
    tutor: Tutor
    other_tutor: Tutor


class Mailbox:
    """A transport that records what it was given, and can be told to fail."""

    def __init__(self, *, fail: bool = False, delay: float = 0) -> None:
        self.received: list[Email] = []
        self.fail = fail
        self.delay = delay

    async def send(self, email: Email) -> None:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("mail server is down")
        self.received.append(email)


def purchase(tutor: Tutor, minutes: int = 600, at: datetime = NOW) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        tutor_id=tutor.id,
        account="anna@example.com",
        kind=EntryKind.PURCHASE,
        minutes=minutes,
        note="Package",
        created_at=at,
        effective_at=at,
    )


class LedgerAndOutboxContract:
    # --- the ledger ---

    async def test_entries_come_back_as_stored_in_the_order_they_took_effect(
        self, stores: Stores
    ) -> None:
        later = purchase(stores.tutor, 120, NOW + DAY)
        earlier = purchase(stores.tutor, 600, NOW)

        assert await stores.ledger.post([later, earlier]) == 2

        assert await stores.ledger.entries(stores.tutor.id, "anna@example.com") == [earlier, later]
        assert await stores.ledger.entries(stores.tutor.id, "bartek@example.com") == []
        assert await stores.ledger.entries(stores.other_tutor.id, "anna@example.com") == []

    async def test_posting_an_entry_again_adds_nothing(self, stores: Stores) -> None:
        entry = purchase(stores.tutor)
        await stores.ledger.post([entry])

        assert await stores.ledger.post([entry, purchase(stores.tutor, 60)]) == 1

        assert await stores.ledger.balances(stores.tutor.id) == {"anna@example.com": 660}

    async def test_a_lesson_is_charged_at_most_once(self, stores: Stores) -> None:
        lesson = await stores.bookings.add(a_booking(stores.tutor.id), "key-1")
        charge = charge_for(lesson, AFTER)
        assert charge is not None
        # A second charge for the same lesson under a different id, as a bug might produce.
        impostor = LedgerEntry(
            id=uuid4(),
            tutor_id=charge.tutor_id,
            account=charge.account,
            kind=EntryKind.LESSON,
            minutes=-60,
            note="Lesson",
            created_at=AFTER,
            effective_at=FIRST_SLOT,
            booking_id=lesson.id,
        )

        assert await stores.ledger.post([charge]) == 1
        assert await stores.ledger.post([impostor]) == 0

        assert await stores.ledger.balances(stores.tutor.id) == {"anna@example.com": -60}

    async def test_many_workers_charging_the_same_lesson_charge_it_once(
        self, stores: Stores
    ) -> None:
        lesson = await stores.bookings.add(a_booking(stores.tutor.id), "key-1")
        charge = charge_for(lesson, AFTER)
        assert charge is not None

        added = await asyncio.gather(*(stores.ledger.post([charge]) for _ in range(12)))

        assert sum(added) == 1
        assert await stores.ledger.balances(stores.tutor.id) == {"anna@example.com": -60}

    async def test_balances_are_kept_per_tutor_and_per_student(self, stores: Stores) -> None:
        await stores.ledger.post([purchase(stores.tutor, 600), purchase(stores.other_tutor, 90)])

        assert await stores.ledger.balances(stores.tutor.id) == {"anna@example.com": 600}
        assert await stores.ledger.balances(stores.other_tutor.id) == {"anna@example.com": 90}

    # --- the outbox ---

    async def test_a_queued_message_is_delivered_once(self, stores: Stores) -> None:
        mailbox = Mailbox()
        await stores.outbox.add(HELLO, NOW)

        first = await stores.outbox.deliver_due(NOW, mailbox.send, 10)
        again = await stores.outbox.deliver_due(NOW + HOUR, mailbox.send, 10)

        assert (first.sent, first.failed, again.sent) == (1, 0, 0)
        assert mailbox.received == [HELLO]

    async def test_a_message_that_fails_is_kept_and_retried_after_a_pause(
        self, stores: Stores
    ) -> None:
        await stores.outbox.add(HELLO, NOW)
        down, up = Mailbox(fail=True), Mailbox()

        failed = await stores.outbox.deliver_due(NOW, down.send, 10)
        too_soon = await stores.outbox.deliver_due(NOW + timedelta(seconds=30), up.send, 10)
        later = await stores.outbox.deliver_due(NOW + timedelta(minutes=1), up.send, 10)

        assert (failed.sent, failed.failed) == (0, 1)
        assert (too_soon.sent, too_soon.failed) == (0, 0)
        assert later.sent == 1
        assert up.received == [HELLO]

    async def test_one_bad_message_does_not_hold_up_the_rest(self, stores: Stores) -> None:
        class Picky(Mailbox):
            async def send(self, email: Email) -> None:
                if email.subject == "Bad":
                    raise ValueError("refused by the server")
                await super().send(email)

        await stores.outbox.add(Email("a@example.com", "Bad", "…"), NOW)
        await stores.outbox.add(HELLO, NOW + timedelta(seconds=1))
        mailbox = Picky()

        delivery = await stores.outbox.deliver_due(NOW + HOUR, mailbox.send, 10)

        assert (delivery.sent, delivery.failed) == (1, 1)
        assert mailbox.received == [HELLO]

    async def test_workers_running_together_never_send_a_message_twice(
        self, stores: Stores
    ) -> None:
        for n in range(6):
            await stores.outbox.add(Email(f"s{n}@example.com", f"Message {n}", "…"), NOW)
        # Slow enough that the workers are certainly inside a send at the same time.
        mailbox = Mailbox(delay=0.05)

        deliveries = await asyncio.gather(
            *(stores.outbox.deliver_due(NOW, mailbox.send, 10) for _ in range(4))
        )

        assert sum(delivery.sent for delivery in deliveries) == 6
        assert sorted(email.subject for email in mailbox.received) == [
            f"Message {n}" for n in range(6)
        ]

    # --- bookings that feed them ---

    async def test_a_confirmation_is_queued_only_with_a_booking_that_is_stored(
        self, stores: Stores
    ) -> None:
        mailbox = Mailbox()
        await stores.bookings.add(a_booking(stores.tutor.id), "key-1", HELLO)

        # A repeat of the same request, and a rival for the same slot.
        await stores.bookings.add(a_booking(stores.tutor.id), "key-1", HELLO)
        with pytest.raises(SlotTakenError):
            await stores.bookings.add(a_booking(stores.tutor.id), "key-2", HELLO)

        await stores.outbox.deliver_due(NOW + HOUR, mailbox.send, 10)
        assert mailbox.received == [HELLO]

    async def test_of_many_rivals_for_a_slot_only_the_winner_is_sent_a_confirmation(
        self, stores: Stores
    ) -> None:
        mailbox = Mailbox()
        attempts = [
            stores.bookings.add(
                a_booking(stores.tutor.id, student=Student(f"S{n}", f"s{n}@example.com")),
                f"key-{n}",
                Email(f"s{n}@example.com", "Booked", "…"),
            )
            for n in range(10)
        ]

        outcomes = await asyncio.gather(*attempts, return_exceptions=True)

        await stores.outbox.deliver_due(NOW + HOUR, mailbox.send, 20)
        [winner] = [o for o in outcomes if not isinstance(o, BaseException)]
        assert [email.to for email in mailbox.received] == [winner.student.email]

    async def test_lessons_await_settlement_once_their_cost_is_final(self, stores: Stores) -> None:
        over = await stores.bookings.add(a_booking(stores.tutor.id, FIRST_SLOT - 3 * HOUR), "k1")
        running = await stores.bookings.add(a_booking(stores.tutor.id, FIRST_SLOT), "k2")
        upcoming = await stores.bookings.add(a_booking(stores.tutor.id, FIRST_SLOT + DAY), "k3")
        called_off = await stores.bookings.add(
            a_booking(stores.tutor.id, FIRST_SLOT + 2 * DAY), "k4"
        )
        cancelled = called_off.cancel(Actor.STUDENT, NOW, AlwaysFree())
        await stores.bookings.apply([(called_off, cancelled)])
        during_the_second = FIRST_SLOT + timedelta(minutes=30)

        waiting = await stores.bookings.awaiting_settlement(during_the_second, 10)

        assert waiting == [over, cancelled]
        assert running not in waiting
        assert upcoming not in waiting

        await stores.bookings.mark_settled([over.id], during_the_second)
        assert await stores.bookings.awaiting_settlement(during_the_second, 10) == [cancelled]
        assert len(await stores.bookings.awaiting_settlement(FIRST_SLOT + 5 * DAY, 1)) == 1

    async def test_reminders_are_due_a_day_ahead_for_lessons_booked_earlier(
        self, stores: Stores
    ) -> None:
        tomorrow = await stores.bookings.add(a_booking(stores.tutor.id, NOW + 20 * HOUR), "k1")
        await stores.bookings.add(a_booking(stores.tutor.id, NOW + 3 * DAY), "k2")
        soon = a_booking(stores.tutor.id, NOW + 26 * HOUR)
        await stores.bookings.add(soon, "k3")

        # ``tomorrow`` was booked 20 hours ahead: less than the lead, so no reminder.
        assert await stores.bookings.due_for_reminder(NOW, DAY, 10) == []
        assert tomorrow.created_at == NOW
        # Three hours later ``soon`` is within a day, and was booked 26 hours ahead.
        assert await stores.bookings.due_for_reminder(NOW + 3 * HOUR, DAY, 10) == [soon]

    async def test_simultaneous_workers_queue_one_reminder_per_lesson(self, stores: Stores) -> None:
        lesson = await stores.bookings.add(a_booking(stores.tutor.id, NOW + 26 * HOUR), "k1")
        mailbox = Mailbox()
        reminder = Email("anna@example.com", "Reminder", "…")
        when = NOW + 3 * HOUR

        queued = await asyncio.gather(
            *(stores.bookings.record_reminders([(lesson, reminder)], when) for _ in range(8))
        )

        assert sum(queued) == 1
        assert await stores.bookings.due_for_reminder(when, DAY, 10) == []
        await stores.outbox.deliver_due(when, mailbox.send, 10)
        assert mailbox.received == [reminder]

    async def test_a_lesson_cancelled_in_the_meantime_is_not_reminded(self, stores: Stores) -> None:
        lesson = await stores.bookings.add(a_booking(stores.tutor.id, NOW + 26 * HOUR), "k1")
        await stores.bookings.apply([(lesson, lesson.cancel(Actor.TUTOR, NOW, AlwaysFree()))])

        queued = await stores.bookings.record_reminders(
            [(lesson, Email("anna@example.com", "Reminder", "…"))], NOW + 3 * HOUR
        )

        assert queued == 0

    # --- what is still waiting, for the metrics. See ADR 0011. ---

    async def test_an_outbox_with_nothing_waiting_has_no_backlog(self, stores: Stores) -> None:
        assert await stores.outbox.backlog() == OutboxBacklog(0, None)

        await stores.outbox.add(HELLO, NOW)
        await stores.outbox.deliver_due(NOW, Mailbox().send, 10)

        # A sent message is still stored, and is not a backlog.
        assert await stores.outbox.backlog() == OutboxBacklog(0, None)

    async def test_the_backlog_counts_what_is_unsent_and_dates_the_oldest(
        self, stores: Stores
    ) -> None:
        await stores.outbox.add(HELLO, NOW + HOUR)
        await stores.outbox.add(Email("b@example.com", "Earlier", "…"), NOW)
        await stores.outbox.add(Email("c@example.com", "Latest", "…"), NOW + 2 * HOUR)

        assert await stores.outbox.backlog() == OutboxBacklog(3, NOW)

        # The oldest goes out; the next oldest is the one that has waited longest.
        await stores.outbox.deliver_due(NOW, Mailbox().send, 10)
        assert await stores.outbox.backlog() == OutboxBacklog(2, NOW + HOUR)

    async def test_a_message_that_keeps_failing_keeps_its_place_in_the_backlog(
        self, stores: Stores
    ) -> None:
        await stores.outbox.add(HELLO, NOW)

        await stores.outbox.deliver_due(NOW, Mailbox(fail=True).send, 10)

        # It is pausing before its next try and would not be picked up now, but
        # it has not been sent, and it has been waiting since it was queued.
        assert (await stores.outbox.deliver_due(NOW, Mailbox().send, 10)).sent == 0
        assert await stores.outbox.backlog() == OutboxBacklog(1, NOW)

    async def test_a_confirmation_queued_with_a_booking_is_in_the_backlog(
        self, stores: Stores
    ) -> None:
        await stores.bookings.add(a_booking(stores.tutor.id), "key-1", HELLO)

        assert await stores.outbox.backlog() == OutboxBacklog(1, NOW)

    async def test_lessons_awaiting_settlement_are_counted_without_a_limit(
        self, stores: Stores
    ) -> None:
        for n in range(3):
            await stores.bookings.add(a_booking(stores.tutor.id, FIRST_SLOT + n * HOUR), f"k{n}")
        upcoming = await stores.bookings.add(a_booking(stores.tutor.id, FIRST_SLOT + DAY), "k9")
        after_three = FIRST_SLOT + 5 * HOUR

        assert await stores.bookings.count_awaiting_settlement(NOW) == 0
        assert await stores.bookings.count_awaiting_settlement(after_three) == 3
        # The count is of everything waiting, not of one batch of it.
        waiting = await stores.bookings.awaiting_settlement(after_three, 2)
        assert len(waiting) == 2

        await stores.bookings.mark_settled([lesson.id for lesson in waiting], after_three)
        assert await stores.bookings.count_awaiting_settlement(after_three) == 1

        # A cancelled lesson's cost is final at once, long before its time.
        await stores.bookings.apply([(upcoming, upcoming.cancel(Actor.TUTOR, NOW, AlwaysFree()))])
        assert await stores.bookings.count_awaiting_settlement(NOW) == 1


class TestInMemory(LedgerAndOutboxContract):
    @pytest.fixture
    def stores(self) -> Stores:
        outbox = InMemoryOutbox()
        return Stores(
            InMemoryBookingRepository(outbox),
            InMemoryLedger(),
            outbox,
            a_tutor("ewa"),
            a_tutor("jan"),
        )


@pytest.mark.integration
class TestPostgres(LedgerAndOutboxContract):
    @pytest.fixture
    async def stores(self, engine: AsyncEngine) -> Stores:
        tutors = PostgresTutorRepository(engine)
        ewa, jan = a_tutor("ewa"), a_tutor("jan")
        assert await tutors.add_if_absent(ewa)
        assert await tutors.add_if_absent(jan)
        return Stores(
            PostgresBookingRepository(engine),
            PostgresLedger(engine),
            PostgresOutbox(engine),
            ewa,
            jan,
        )
