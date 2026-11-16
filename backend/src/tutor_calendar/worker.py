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

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_calendar.adapters.clock import SystemClock
from tutor_calendar.adapters.mail import LoggingMailer, SmtpMailer
from tutor_calendar.adapters.manage_links import HmacManageLinks
from tutor_calendar.adapters.postgres.billing import PostgresLedger, PostgresOutbox
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.background import DeliverOutbox, SendReminders, SettleLessons
from tutor_calendar.application.ports import Clock, Mailer
from tutor_calendar.config import Settings

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
        self, settings: Settings, engine: AsyncEngine, clock: Clock, mailer: Mailer
    ) -> None:
        bookings = PostgresBookingRepository(engine)
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
        try:
            done["charged"] = await self._settle.execute()
        except Exception:
            logger.exception("settling lessons failed")
        try:
            if self._reminders is not None:
                done["reminders"] = await self._reminders.execute()
        except Exception:
            logger.exception("queueing reminders failed")
        try:
            delivery = await self._deliver.execute()
            done["sent"], done["failed"] = delivery.sent, delivery.failed
        except Exception:
            logger.exception("delivering mail failed")
        return done

    async def run_forever(self, interval_seconds: float) -> None:
        while True:
            done = await self.run_once()
            if any(done.values()):
                logger.info("round finished: %s", done)
            await asyncio.sleep(interval_seconds)


async def main(once: bool) -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    worker = Worker(settings, engine, SystemClock(), transport(settings))
    try:
        if once:
            print(await worker.run_once())
        else:
            await worker.run_forever(settings.worker_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(once="--once" in sys.argv[1:]))
