"""Accounts, statements and the background jobs, with fakes behind the use cases."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from tests.factories import ANNA, FIRST_SLOT, LINKS, NOW, STATEMENT_LINKS, a_tutor
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger, InMemoryOutbox
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.application.background import DeliverOutbox, SendReminders, SettleLessons
from tutor_calendar.application.billing import (
    ListAccounts,
    RecordEntry,
    ShareStatement,
    ShowStatement,
)
from tutor_calendar.application.book_lesson import BookingResult, BookLesson
from tutor_calendar.application.errors import InvalidEntryError, StatementNotFoundError
from tutor_calendar.application.lessons import ChangeOwnLesson, ManageBooking
from tutor_calendar.application.ports import Email
from tutor_calendar.demo import demo_tutor
from tutor_calendar.domain.billing import EntryKind
from tutor_calendar.domain.scheduling import Student

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
BARTEK = Student("Bartek Lis", "Bartek@Example.com")
PUBLIC_URL = "https://app.test"


class Scenario:
    def __init__(self) -> None:
        self.tutor = demo_tutor()
        self.other_tutor = a_tutor("ewa")
        self.tutors = InMemoryTutorRepository([self.tutor, self.other_tutor])
        self.outbox = InMemoryOutbox()
        self.bookings = InMemoryBookingRepository(self.outbox)
        self.ledger = InMemoryLedger()
        self.mailer = InMemoryMailer()
        self.now = NOW

    @property
    def clock(self) -> FixedClock:
        return FixedClock(self.now)

    async def book(self, start: datetime = FIRST_SLOT, student: Student = ANNA) -> BookingResult:
        use_case = BookLesson(self.tutors, self.bookings, LINKS, self.clock, PUBLIC_URL)
        return await use_case.execute("demo", start, student, f"key-{uuid4()}")

    async def buy(self, email: str, minutes: int, note: str = "Package of 10") -> None:
        record = RecordEntry(self.ledger, self.clock)
        await record.execute(self.tutor, uuid4(), email, EntryKind.PURCHASE, minutes, note)

    async def settle(self) -> int:
        return await SettleLessons(self.bookings, self.ledger, self.clock).execute()

    async def remind(self) -> int:
        job = SendReminders(self.bookings, self.tutors, LINKS, self.clock, PUBLIC_URL)
        return await job.execute()

    async def balance_of(self, email: str) -> int:
        accounts = await ListAccounts(self.ledger, self.bookings).execute(self.tutor)
        return next(account.balance for account in accounts if account.email == email)

    @property
    def statements(self) -> ShowStatement:
        return ShowStatement(self.ledger, self.bookings, self.clock)


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


class TestRecordingTime:
    async def test_a_package_adds_to_the_balance(self, scenario: Scenario) -> None:
        await scenario.buy("Anna@Example.com", 600)

        [account] = await ListAccounts(scenario.ledger, scenario.bookings).execute(scenario.tutor)
        # No lesson yet, so the name is not known.
        assert (account.email, account.name, account.balance) == ("anna@example.com", None, 600)

    async def test_recording_the_same_entry_again_changes_nothing(self, scenario: Scenario) -> None:
        record = RecordEntry(scenario.ledger, scenario.clock)
        entry_id = uuid4()
        package = ("anna@example.com", EntryKind.PURCHASE, 600, "Package of 10")
        first = await record.execute(scenario.tutor, entry_id, *package)

        again = await record.execute(scenario.tutor, entry_id, *package)

        assert again == first
        assert await scenario.balance_of("anna@example.com") == 600

    async def test_an_id_cannot_be_reused_for_a_different_entry(self, scenario: Scenario) -> None:
        record = RecordEntry(scenario.ledger, scenario.clock)
        entry_id = uuid4()
        await record.execute(
            scenario.tutor, entry_id, "anna@example.com", EntryKind.PURCHASE, 600, ""
        )

        with pytest.raises(InvalidEntryError, match="different entry"):
            await record.execute(
                scenario.tutor, entry_id, "anna@example.com", EntryKind.PURCHASE, 300, ""
            )
        assert await scenario.balance_of("anna@example.com") == 600

    async def test_a_mistake_is_corrected_by_another_entry(self, scenario: Scenario) -> None:
        record = RecordEntry(scenario.ledger, scenario.clock)
        await scenario.buy("anna@example.com", 600)

        await record.execute(
            scenario.tutor,
            uuid4(),
            "anna@example.com",
            EntryKind.ADJUSTMENT,
            -300,
            "Recorded 10 hours, it was 5",
        )

        assert await scenario.balance_of("anna@example.com") == 300
        assert len(await scenario.ledger.entries(scenario.tutor.id, "anna@example.com")) == 2

    @pytest.mark.parametrize(
        ("kind", "minutes", "note"),
        [
            (EntryKind.PURCHASE, 0, ""),
            (EntryKind.PURCHASE, -60, ""),
            (EntryKind.ADJUSTMENT, -60, ""),
            (EntryKind.LESSON, -60, "by hand"),
        ],
        ids=["nothing", "negative purchase", "unexplained correction", "a charge by hand"],
    )
    async def test_entries_that_make_no_sense_are_refused(
        self, scenario: Scenario, kind: EntryKind, minutes: int, note: str
    ) -> None:
        record = RecordEntry(scenario.ledger, scenario.clock)

        with pytest.raises(InvalidEntryError):
            await record.execute(scenario.tutor, uuid4(), "anna@example.com", kind, minutes, note)

    async def test_accounts_list_everyone_with_a_lesson_or_a_package(
        self, scenario: Scenario
    ) -> None:
        await scenario.book(FIRST_SLOT, BARTEK)
        await scenario.buy("zofia@example.com", 120)
        await scenario.buy("bartek@example.com", 60)

        accounts = await ListAccounts(scenario.ledger, scenario.bookings).execute(scenario.tutor)

        assert [(a.email, a.name, a.balance) for a in accounts] == [
            ("bartek@example.com", "Bartek Lis", 60),
            ("zofia@example.com", None, 120),
        ]
        assert (
            await ListAccounts(scenario.ledger, scenario.bookings).execute(scenario.other_tutor)
            == []
        )


class TestSettlingLessons:
    async def test_a_lesson_is_charged_once_it_is_over(self, scenario: Scenario) -> None:
        await scenario.buy("anna@example.com", 600)
        await scenario.book()

        assert await scenario.settle() == 0  # still to come
        scenario.now = FIRST_SLOT + HOUR
        assert await scenario.settle() == 1

        assert await scenario.balance_of("anna@example.com") == 540

    async def test_running_it_again_never_charges_twice(self, scenario: Scenario) -> None:
        await scenario.book()
        scenario.now = FIRST_SLOT + HOUR
        await scenario.settle()

        assert await scenario.settle() == 0
        scenario.bookings._settled.clear()  # as if the worker died before marking them
        assert await scenario.settle() == 0

        assert await scenario.balance_of("anna@example.com") == -60

    async def test_a_no_show_and_a_late_cancellation_are_charged_a_timely_one_is_not(
        self, scenario: Scenario
    ) -> None:
        missed = await scenario.book(FIRST_SLOT)
        late = await scenario.book(FIRST_SLOT + HOUR, BARTEK)
        timely = await scenario.book(FIRST_SLOT + 2 * DAY, Student("Zofia", "zofia@example.com"))
        manage = ManageBooking(scenario.bookings, scenario.tutors, LINKS, scenario.clock)
        await manage.cancel(timely.manage_token)

        scenario.now = FIRST_SLOT - HOUR
        manage = ManageBooking(scenario.bookings, scenario.tutors, LINKS, scenario.clock)
        await manage.cancel(late.manage_token)
        # Charged at once: a late cancellation cannot change any more.
        assert await scenario.settle() == 1

        scenario.now = FIRST_SLOT + timedelta(minutes=15)
        own = ChangeOwnLesson(scenario.bookings, scenario.clock)
        await own.mark_no_show(scenario.tutor, missed.booking.id)
        assert await scenario.settle() == 1

        assert await scenario.balance_of("anna@example.com") == -60
        assert await scenario.balance_of("bartek@example.com") == -60
        assert await scenario.balance_of("zofia@example.com") == 0


class TestStatements:
    async def test_a_month_runs_on_the_tutors_calendar(self, scenario: Scenario) -> None:
        await scenario.buy("anna@example.com", 600)
        # 23:30 UTC on 30 November is already 1 December in Warsaw.
        scenario.now = datetime(2026, 11, 30, 23, 30, tzinfo=UTC)
        await scenario.buy("anna@example.com", 120, "Two extra hours")

        november = await scenario.statements.execute(
            scenario.tutor, "anna@example.com", date(2026, 11, 20)
        )
        december = await scenario.statements.execute(scenario.tutor, "anna@example.com", None)

        assert (november.month, november.previous, november.next) == (
            date(2026, 11, 1),
            date(2026, 10, 1),
            date(2026, 12, 1),
        )
        assert (november.statement.opening, november.statement.closing) == (0, 600)
        assert december.month == date(2026, 12, 1)
        assert [entry.note for entry in december.statement.entries] == ["Two extra hours"]
        assert (december.statement.opening, december.statement.closing) == (600, 720)
        assert november.balance_now == december.balance_now == 720

    async def test_a_lesson_is_on_the_statement_of_the_month_it_was_held_in(
        self, scenario: Scenario
    ) -> None:
        await scenario.book(datetime(2026, 11, 30, 14, 0, tzinfo=UTC))
        scenario.now = datetime(2026, 12, 3, 9, 0, tzinfo=UTC)  # the worker was down for days
        await scenario.settle()

        november = await scenario.statements.execute(
            scenario.tutor, "anna@example.com", date(2026, 11, 1)
        )

        assert [(e.kind, e.minutes) for e in november.statement.entries] == [
            (EntryKind.LESSON, -60)
        ]
        assert november.student_name == "Anna Nowak"

    async def test_an_unknown_student_has_no_statement(self, scenario: Scenario) -> None:
        await scenario.buy("anna@example.com", 600)

        with pytest.raises(StatementNotFoundError):
            await scenario.statements.execute(scenario.tutor, "nobody@example.com", None)
        with pytest.raises(StatementNotFoundError):
            await scenario.statements.execute(scenario.other_tutor, "anna@example.com", None)

    async def test_a_parent_reads_one_students_statement_with_a_link(
        self, scenario: Scenario
    ) -> None:
        await scenario.buy("anna@example.com", 600)
        share = ShareStatement(scenario.tutors, scenario.statements, STATEMENT_LINKS)

        token = share.token_for(scenario.tutor, "Anna@Example.com")
        view = await share.view(token, None)

        assert (view.account, view.balance_now, view.tutor) == (
            "anna@example.com",
            600,
            scenario.tutor,
        )

    async def test_other_tokens_do_not_open_statements(self, scenario: Scenario) -> None:
        booked = await scenario.book()
        await scenario.buy("anna@example.com", 600)
        share = ShareStatement(scenario.tutors, scenario.statements, STATEMENT_LINKS)
        of_a_stranger = STATEMENT_LINKS.token_for(scenario.tutor.id, "stranger@example.com")
        of_no_tutor = STATEMENT_LINKS.token_for(uuid4(), "anna@example.com")

        for token in ("", "made-up", booked.manage_token, of_a_stranger, of_no_tutor):
            with pytest.raises(StatementNotFoundError):
                await share.view(token, None)


class TestMail:
    async def test_a_booking_queues_its_confirmation(self, scenario: Scenario) -> None:
        booked = await scenario.book()

        [email] = scenario.outbox.waiting
        assert email.to == "anna@example.com"
        assert "Tuesday 17 November 2026, 15:00 (Europe/Warsaw time)" in email.body
        assert f"{PUBLIC_URL}/booking#token={booked.manage_token}" in email.body

    async def test_a_repeated_or_refused_booking_queues_nothing_more(
        self, scenario: Scenario
    ) -> None:
        use_case = BookLesson(scenario.tutors, scenario.bookings, LINKS, scenario.clock)
        await use_case.execute("demo", FIRST_SLOT, ANNA, "key-1")

        await use_case.execute("demo", FIRST_SLOT, ANNA, "key-1")
        with pytest.raises(Exception, match="just been booked"):
            await use_case.execute("demo", FIRST_SLOT, BARTEK, "key-2")

        assert len(scenario.outbox.waiting) == 1

    async def test_delivery_sends_what_is_waiting_once(self, scenario: Scenario) -> None:
        await scenario.book()
        deliver = DeliverOutbox(scenario.outbox, scenario.mailer, scenario.clock)

        first = await deliver.execute()
        again = await deliver.execute()

        assert (first.sent, first.failed, again.sent) == (1, 0, 0)
        assert len(scenario.mailer.sent) == 1

    async def test_a_message_that_cannot_be_sent_is_tried_again_later(
        self, scenario: Scenario
    ) -> None:
        class Down:
            def __init__(self) -> None:
                self.attempts = 0

            async def send(self, email: Email) -> None:
                self.attempts += 1
                raise ConnectionError("mail server is down")

        await scenario.book()
        down = Down()

        failed = await DeliverOutbox(scenario.outbox, down, scenario.clock).execute()
        at_once = await DeliverOutbox(scenario.outbox, down, scenario.clock).execute()
        scenario.now = NOW + timedelta(minutes=1)
        recovered = await DeliverOutbox(scenario.outbox, scenario.mailer, scenario.clock).execute()

        assert (failed.sent, failed.failed) == (0, 1)
        # Not hammered: nothing is due again until the pause has passed.
        assert (at_once.sent, at_once.failed, down.attempts) == (0, 0, 1)
        assert recovered.sent == 1
        assert len(scenario.mailer.sent) == 1


class TestReminders:
    async def test_a_lesson_is_reminded_of_once_a_day_ahead(self, scenario: Scenario) -> None:
        booked = await scenario.book(FIRST_SLOT + 2 * DAY)
        scenario.outbox.waiting.clear()

        assert await scenario.remind() == 0  # two days away
        scenario.now = FIRST_SLOT + DAY + HOUR
        assert await scenario.remind() == 1
        assert await scenario.remind() == 0

        reminder = scenario.outbox.waiting[-1]
        assert reminder.subject == "Reminder: lesson with Demo Tutor tomorrow"
        assert booked.manage_token in reminder.body

    async def test_a_lesson_booked_at_the_last_minute_gets_no_reminder(
        self, scenario: Scenario
    ) -> None:
        scenario.now = FIRST_SLOT - 13 * HOUR
        await scenario.book()  # 13 hours ahead: the confirmation is reminder enough

        assert await scenario.remind() == 0

    async def test_a_cancelled_lesson_gets_no_reminder(self, scenario: Scenario) -> None:
        booked = await scenario.book(FIRST_SLOT + 2 * DAY)
        await ManageBooking(scenario.bookings, scenario.tutors, LINKS, scenario.clock).cancel(
            booked.manage_token
        )
        scenario.now = FIRST_SLOT + DAY + HOUR

        assert await scenario.remind() == 0

    async def test_two_workers_finding_the_same_lesson_queue_one_reminder(
        self, scenario: Scenario
    ) -> None:
        await scenario.book(FIRST_SLOT + 2 * DAY)
        scenario.now = FIRST_SLOT + DAY + HOUR
        [lesson] = await scenario.bookings.due_for_reminder(scenario.now, DAY, 10)
        reminder = Email("anna@example.com", "Reminder", "…")

        # Both read the lesson as due before either recorded anything.
        first = await scenario.bookings.record_reminders([(lesson, reminder)], scenario.now)
        second = await scenario.bookings.record_reminders([(lesson, reminder)], scenario.now)

        assert (first, second) == (1, 0)
