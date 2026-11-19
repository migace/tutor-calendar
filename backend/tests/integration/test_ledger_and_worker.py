"""What only a real database and a real mail connection can show."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from datetime import datetime, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from uuid import uuid4

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import FIRST_SLOT, LINKS, NOW, SECRET
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.mail import InMemoryMailer, SmtpMailer
from tutor_calendar.adapters.postgres.billing import PostgresLedger, PostgresOutbox
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.jobs import PostgresJobLog
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.book_lesson import BookLesson
from tutor_calendar.application.ports import Email
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor
from tutor_calendar.domain.billing import EntryKind, LedgerEntry
from tutor_calendar.domain.scheduling import Student
from tutor_calendar.worker import Worker, transport

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
ANNA = Student("Anna Nowak", "anna@example.com")


async def a_stored_entry(engine: AsyncEngine) -> LedgerEntry:
    tutor = demo_tutor()
    await PostgresTutorRepository(engine).add_if_absent(tutor)
    entry = LedgerEntry(
        id=uuid4(),
        tutor_id=tutor.id,
        account="anna@example.com",
        kind=EntryKind.PURCHASE,
        minutes=600,
        note="Package",
        created_at=NOW,
        effective_at=NOW,
    )
    await PostgresLedger(engine).post([entry])
    return entry


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger_entries SET minutes = 6000",
        "UPDATE ledger_entries SET note = 'tidied up'",
        "DELETE FROM ledger_entries",
    ],
)
async def test_the_database_refuses_to_change_or_remove_a_ledger_entry(
    engine: AsyncEngine, statement: str
) -> None:
    entry = await a_stored_entry(engine)

    with pytest.raises(DBAPIError, match="cannot be changed or removed"):
        async with engine.begin() as connection:
            await connection.execute(text(statement))

    assert await PostgresLedger(engine).entries(entry.tutor_id, entry.account) == [entry]


@pytest.mark.parametrize(
    "broken",
    [
        "kind = 'refund'",  # no such kind
        "minutes = 0",
        "account = 'Anna@Example.com'",
        "booking_id = gen_random_uuid()",  # a purchase naming a lesson
    ],
)
async def test_the_database_refuses_ledger_entries_that_make_no_sense(
    engine: AsyncEngine, broken: str
) -> None:
    entry = await a_stored_entry(engine)
    column, value = broken.split(" = ")
    values = {
        "id": "gen_random_uuid()",
        "tutor_id": f"'{entry.tutor_id}'",
        "account": "'anna@example.com'",
        "kind": "'purchase'",
        "minutes": "60",
        "note": "''",
        "booking_id": "NULL",
        "created_at": "now()",
        "effective_at": "now()",
    } | {column: value}

    with pytest.raises(DBAPIError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f"INSERT INTO ledger_entries ({', '.join(values)})"
                    f" VALUES ({', '.join(values.values())})"
                )
            )


class TestTheWorker:
    """One round of the worker against a real database, with a clock the test moves."""

    @pytest.fixture
    def settings(self, database_url: str) -> Settings:
        return Settings(database_url=database_url, secret_key=SECRET, public_url="https://app.test")

    async def book(self, engine: AsyncEngine, start: datetime, now: datetime) -> None:
        tutors = PostgresTutorRepository(engine)
        await tutors.add_if_absent(demo_tutor())
        use_case = BookLesson(
            tutors, PostgresBookingRepository(engine), LINKS, FixedClock(now), "https://app.test"
        )
        await use_case.execute("demo", start, ANNA, uuid4().hex)

    async def test_it_delivers_the_confirmation_then_a_reminder_then_charges_the_lesson(
        self, engine: AsyncEngine, settings: Settings
    ) -> None:
        mailbox = InMemoryMailer()
        lesson_start = FIRST_SLOT + 2 * DAY
        await self.book(engine, lesson_start, NOW)

        def worker_at(moment: datetime) -> Worker:
            return Worker(settings, engine, FixedClock(moment), mailbox)

        # Right after the booking: the confirmation goes out, nothing else is due.
        assert await worker_at(NOW).run_once() == {
            "charged": 0,
            "reminders": 0,
            "sent": 1,
            "failed": 0,
        }
        # Within a day of the lesson: a reminder is queued and sent in the same round.
        day_before = await worker_at(lesson_start - 20 * HOUR).run_once()
        assert (day_before["reminders"], day_before["sent"]) == (1, 1)
        # After the lesson: it is charged, once, however often the worker runs.
        assert (await worker_at(lesson_start + 2 * HOUR).run_once())["charged"] == 1
        assert (await worker_at(lesson_start + 3 * HOUR).run_once()) == {
            "charged": 0,
            "reminders": 0,
            "sent": 0,
            "failed": 0,
        }

        assert [email.subject for email in mailbox.sent] == [
            "Your lesson with Demo Tutor is booked",
            "Reminder: lesson with Demo Tutor tomorrow",
        ]
        assert await PostgresLedger(engine).balances(demo_tutor().id) == {"anna@example.com": -60}

    async def test_several_workers_at_once_do_each_piece_of_work_once(
        self, engine: AsyncEngine, settings: Settings
    ) -> None:
        mailbox = InMemoryMailer()
        for n in range(4):
            await self.book(engine, FIRST_SLOT + 2 * DAY + n * HOUR, NOW)
        after_everything = FIRST_SLOT + 3 * DAY
        # Late enough that all four lessons start within the next 24 hours.
        before_the_lessons = FIRST_SLOT + DAY + 4 * HOUR

        await asyncio.gather(
            *(
                Worker(settings, engine, FixedClock(before_the_lessons), mailbox).run_once()
                for _ in range(5)
            )
        )
        await asyncio.gather(
            *(
                Worker(settings, engine, FixedClock(after_everything), mailbox).run_once()
                for _ in range(5)
            )
        )

        subjects = sorted(email.subject for email in mailbox.sent)
        assert (
            subjects
            == ["Reminder: lesson with Demo Tutor tomorrow"] * 4
            + ["Your lesson with Demo Tutor is booked"] * 4
        )
        assert await PostgresLedger(engine).balances(demo_tutor().id) == {"anna@example.com": -240}

    async def test_mail_that_cannot_be_sent_stays_queued_for_the_next_round(
        self, engine: AsyncEngine, settings: Settings
    ) -> None:
        class Down:
            async def send(self, email: Email) -> None:
                raise ConnectionError("mail server is down")

        mailbox = InMemoryMailer()
        await self.book(engine, FIRST_SLOT + 2 * DAY, NOW)

        failed = await Worker(settings, engine, FixedClock(NOW), Down()).run_once()
        later = await Worker(
            settings, engine, FixedClock(NOW + timedelta(minutes=2)), mailbox
        ).run_once()

        assert (failed["sent"], failed["failed"]) == (0, 1)
        assert later["sent"] == 1
        async with engine.connect() as connection:
            row = (await connection.execute(text("SELECT attempts, last_error FROM outbox"))).one()
        assert (row.attempts, row.last_error) == (1, "ConnectionError: mail server is down")

    async def test_without_a_signing_key_it_sends_no_reminders_but_does_the_rest(
        self, engine: AsyncEngine, database_url: str
    ) -> None:
        mailbox = InMemoryMailer()
        await self.book(engine, FIRST_SLOT + 2 * DAY, NOW)
        keyless = Settings(database_url=database_url, secret_key=None)

        done = await Worker(
            keyless, engine, FixedClock(FIRST_SLOT + DAY + 2 * HOUR), mailbox
        ).run_once()

        assert (done["reminders"], done["sent"]) == (0, 1)

    async def test_it_writes_down_each_job_it_finished(
        self, engine: AsyncEngine, settings: Settings
    ) -> None:
        await self.book(engine, FIRST_SLOT + 2 * DAY, NOW)

        await Worker(settings, engine, FixedClock(NOW), InMemoryMailer()).run_once()
        later = NOW + timedelta(seconds=30)
        await Worker(settings, engine, FixedClock(later), InMemoryMailer()).run_once()

        assert await PostgresJobLog(engine).last_successes() == {
            "settle": later,
            "remind": later,
            "deliver": later,
        }

    async def test_a_job_that_failed_keeps_the_time_it_last_succeeded(
        self, engine: AsyncEngine, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        class Broken:
            async def execute(self) -> int:
                raise RuntimeError("the ledger is on fire")

        await Worker(settings, engine, FixedClock(NOW), InMemoryMailer()).run_once()
        later = NOW + timedelta(seconds=30)
        worker = Worker(settings, engine, FixedClock(later), InMemoryMailer())
        worker._settle = Broken()  # type: ignore[assignment]

        done = await worker.run_once()

        # The other jobs ran, and only they moved on.
        assert done["charged"] == 0
        assert await PostgresJobLog(engine).last_successes() == {
            "settle": NOW,
            "remind": later,
            "deliver": later,
        }
        [failure] = [record for record in caplog.records if record.levelname == "ERROR"]
        assert failure.getMessage() == "settling lessons failed"
        assert failure.__dict__["job"] == "settle"

    async def test_mail_the_server_refuses_shows_as_a_backlog_not_as_a_failed_job(
        self, engine: AsyncEngine, settings: Settings
    ) -> None:
        class Down:
            async def send(self, email: Email) -> None:
                raise ConnectionError("mail server is down")

        await self.book(engine, FIRST_SLOT + 2 * DAY, NOW)

        await Worker(settings, engine, FixedClock(NOW), Down()).run_once()

        # The job ran to its end; what it could not send is still there to be counted.
        assert (await PostgresJobLog(engine).last_successes())["deliver"] == NOW
        backlog = await PostgresOutbox(engine).backlog()
        assert (backlog.waiting, backlog.oldest_queued_at) == (1, NOW)

    async def test_a_record_that_cannot_be_written_does_not_stop_the_work(
        self, engine: AsyncEngine, settings: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        class Unwritable:
            async def record_success(self, job: str, at: datetime) -> None:
                raise ConnectionError("the table is locked")

            async def last_successes(self) -> dict[str, datetime]:
                return {}

        mailbox = InMemoryMailer()
        await self.book(engine, FIRST_SLOT + 2 * DAY, NOW)

        done = await Worker(settings, engine, FixedClock(NOW), mailbox, Unwritable()).run_once()

        assert done["sent"] == 1
        assert len(mailbox.sent) == 1
        assert [
            record.getMessage() for record in caplog.records if record.levelname == "ERROR"
        ] == [
            "recording that settling lessons finished failed",
            "recording that queueing reminders finished failed",
            "recording that delivering mail finished failed",
        ]

    async def test_without_a_signing_key_no_reminder_job_is_recorded(
        self, engine: AsyncEngine, database_url: str
    ) -> None:
        keyless = Settings(database_url=database_url, secret_key=None)

        await Worker(keyless, engine, FixedClock(NOW), InMemoryMailer()).run_once()

        assert set(await PostgresJobLog(engine).last_successes()) == {"settle", "deliver"}


class Inbox:
    """A mail server for one test: keeps what it is handed."""

    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:
        content = envelope.content
        assert isinstance(content, bytes)
        self.messages.append(message_from_bytes(content))
        return "250 Message accepted for delivery"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def mail_server() -> Iterator[tuple[Inbox, int]]:
    inbox, port = Inbox(), _free_port()
    controller = Controller(inbox, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield inbox, port
    finally:
        controller.stop()


async def test_mail_really_leaves_over_smtp(mail_server: tuple[Inbox, int]) -> None:
    inbox, port = mail_server
    mailer = SmtpMailer("127.0.0.1", port, "Tutor Calendar <no-reply@example.com>", starttls=False)

    await mailer.send(
        Email("anna@example.com", "Zażółć gęślą jaźń", "Lekcja: wtorek, 17:00.\nDo zobaczenia!")
    )

    [message] = inbox.messages
    assert message["To"] == "anna@example.com"
    assert message["From"] == "Tutor Calendar <no-reply@example.com>"
    # Non-ASCII survives the trip, in the subject and in the body.
    assert str(make_header(decode_header(message["Subject"]))) == "Zażółć gęślą jaźń"
    body = message.get_payload(decode=True)
    assert isinstance(body, bytes)
    assert "Lekcja: wtorek, 17:00." in body.decode()


async def test_a_mail_server_that_is_not_there_is_an_error_not_a_silence() -> None:
    mailer = SmtpMailer("127.0.0.1", 1, "sender@example.com", starttls=False, timeout_seconds=2)

    with pytest.raises(OSError, match=r".+"):
        await mailer.send(Email("anna@example.com", "Hello", "…"))


def test_the_worker_logs_mail_when_no_server_is_configured() -> None:
    assert type(transport(Settings(smtp_host=None))).__name__ == "LoggingMailer"
    configured = transport(Settings(smtp_host="mail.example.com", smtp_port=2525))
    assert isinstance(configured, SmtpMailer)
    assert (configured.host, configured.port) == ("mail.example.com", 2525)
