"""The background worker: charges finished lessons, queues reminders, sends e-mail.

    python -m tutor_calendar.worker          run until stopped
    python -m tutor_calendar.worker --once   do one round and exit

Any number of workers can run at the same time. See ADR 0007.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_calendar.adapters.clock import SystemClock
from tutor_calendar.adapters.mail import LoggingMailer, SmtpMailer
from tutor_calendar.adapters.manage_links import HmacManageLinks
from tutor_calendar.adapters.postgres.billing import PostgresLedger, PostgresOutbox
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.jobs import PostgresJobLog
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.background import (
    DELIVER,
    REMIND,
    SETTLE,
    DeliverOutbox,
    SendReminders,
    SettleLessons,
)
from tutor_calendar.application.ports import Clock, JobLog, Mailer
from tutor_calendar.config import Settings
from tutor_calendar.logs import configure_logging

logger = logging.getLogger("tutor_calendar.worker")


def transport(settings: Settings) -> Mailer:
    """How mail actually leaves: a mail server if one is configured, else the log."""
    if settings.smtp_host is None:
        return LoggingMailer()
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.mail_from,
        username=settings.smtp_username,
        password=settings.smtp_password,
        starttls=settings.smtp_starttls,
    )


class Worker:
    def __init__(
        self,
        settings: Settings,
        engine: AsyncEngine,
        clock: Clock,
        mailer: Mailer,
        jobs: JobLog | None = None,
    ) -> None:
        bookings = PostgresBookingRepository(engine)
        self._clock = clock
        # Where each job's last success is written, for the web process to
        # report. This process serves no metrics of its own. See ADR 0011.
        self._jobs = jobs or PostgresJobLog(engine)
        if settings.secret_key is None:
            # The API would sign with a different random key, so links made
            # here could never be opened. Better no reminders than broken ones.
            logger.warning("TC_SECRET_KEY is not set: reminders will not be sent.")
            self._reminders = None
        else:
            self._reminders = SendReminders(
                bookings,
                PostgresTutorRepository(engine),
                HmacManageLinks(settings.secret_key),
                clock,
                settings.public_url,
            )
        self._settle = SettleLessons(bookings, PostgresLedger(engine), clock)
        self._deliver = DeliverOutbox(PostgresOutbox(engine), mailer, clock)

    async def run_once(self) -> dict[str, int]:
        """One round of every job. A job that fails is logged and does not stop the others."""
        done = {"charged": 0, "reminders": 0, "sent": 0, "failed": 0}

        async def settle() -> None:
            done["charged"] = await self._settle.execute()

        async def remind(reminders: SendReminders) -> None:
            done["reminders"] = await reminders.execute()

        async def deliver() -> None:
            delivery = await self._deliver.execute()
            done["sent"], done["failed"] = delivery.sent, delivery.failed

        await self._run(SETTLE, "settling lessons", settle)
        if self._reminders is not None:
            reminders = self._reminders
            await self._run(REMIND, "queueing reminders", lambda: remind(reminders))
        await self._run(DELIVER, "delivering mail", deliver)
        return done

    async def _run(self, job: str, doing: str, work: Callable[[], Awaitable[None]]) -> None:
        """Do one job, and write down that it finished.

        A message the mail server refused is not a failed job: the job ran,
        and the message stays queued and shows up as a backlog that ages.
        """
        try:
            await work()
        except Exception:
            logger.exception("%s failed", doing, extra={"job": job})
            return
        try:
            await self._jobs.record_success(job, self._clock.now())
        except Exception:
            # The work was done. Only the note that it was done is missing,
            # and the metrics will show the job as overdue until one gets through.
            logger.exception("recording that %s finished failed", doing, extra={"job": job})

    async def run_forever(self, interval_seconds: float) -> None:
        while True:
            done = await self.run_once()
            if any(done.values()):
                logger.info("round finished: %s", done, extra=done)
            await asyncio.sleep(interval_seconds)


async def main(once: bool) -> None:
    settings = Settings()
    configure_logging("worker", settings.log_format)
    # As in the API: a failed statement is logged without its values.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    worker = Worker(settings, engine, SystemClock(), transport(settings))
    try:
        if once:
            done = await worker.run_once()
            logger.info("round finished: %s", done, extra=done)
        else:
            await worker.run_forever(settings.worker_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(once="--once" in sys.argv[1:]))
