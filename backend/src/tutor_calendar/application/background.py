"""Work that happens on a timer instead of in answer to a request.

Each job is safe to run at any moment, any number of times, and from several
workers at once: every one of them finds its own work in the database and
records having done it in a way that cannot be recorded twice. See ADR 0007.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tutor_calendar.application.emails import lesson_reminder
from tutor_calendar.application.ports import (
    Clock,
    Delivery,
    JobLog,
    Ledger,
    Mailer,
    ManageLinks,
    Outbox,
    ReminderQueue,
    SettlementQueue,
    TutorRepository,
)
from tutor_calendar.domain.billing import charge_for

BATCH = 100
REMINDER_LEAD = timedelta(hours=24)

# The names the jobs are recorded under in the ``JobLog``.
SETTLE = "settle"
REMIND = "remind"
DELIVER = "deliver"


class SettleLessons:
    """Charge lessons whose cost has become final.

    That is a lesson that took place, a no-show, or a late cancellation. The
    ledger keeps at most one charge per lesson, so if this stops halfway, or two
    workers pick the same lessons, running it again finishes the job without
    charging anyone twice.
    """

    def __init__(self, lessons: SettlementQueue, ledger: Ledger, clock: Clock) -> None:
        self._lessons = lessons
        self._ledger = ledger
        self._clock = clock

    async def execute(self) -> int:
        now = self._clock.now()
        lessons = await self._lessons.awaiting_settlement(now, BATCH)
        charges = [charge for lesson in lessons if (charge := charge_for(lesson, now))]
        charged = await self._ledger.post(charges)
        # Marked only after the charges are in. A crash in between leaves the
        # lessons to be found again, and posting them again is harmless.
        await self._lessons.mark_settled([lesson.id for lesson in lessons], now)
        return charged


class SendReminders:
    """Queue a reminder for each lesson that starts within a day."""

    def __init__(
        self,
        lessons: ReminderQueue,
        tutors: TutorRepository,
        links: ManageLinks,
        clock: Clock,
        public_url: str,
    ) -> None:
        self._lessons = lessons
        self._tutors = tutors
        self._links = links
        self._clock = clock
        self._public_url = public_url

    async def execute(self) -> int:
        now = self._clock.now()
        reminders = []
        for lesson in await self._lessons.due_for_reminder(now, REMINDER_LEAD, BATCH):
            tutor = await self._tutors.get_by_id(lesson.tutor_id)
            if tutor is not None:
                token = self._links.token_for(lesson.id)
                reminders.append((lesson, lesson_reminder(tutor, lesson, token, self._public_url)))
        return await self._lessons.record_reminders(reminders, now)


def retry_pause(attempts: int) -> timedelta:
    """How long to wait before trying a message again: 1, 2, 4 ... minutes, at most an hour.

    Every outbox, real or fake, waits by this rule, so it lives here and not in
    one of them.
    """
    return min(timedelta(minutes=2 ** (attempts - 1)), timedelta(hours=1))


class DeliverOutbox:
    """Send the e-mail that is waiting."""

    def __init__(self, outbox: Outbox, mailer: Mailer, clock: Clock) -> None:
        self._outbox = outbox
        self._mailer = mailer
        self._clock = clock

    async def execute(self) -> Delivery:
        return await self._outbox.deliver_due(self._clock.now(), self._mailer.send, BATCH)


@dataclass(frozen=True, slots=True)
class BackgroundWork:
    """How far behind the background jobs are, at one moment."""

    unsent_messages: int
    # Zero when nothing is waiting.
    oldest_unsent_age: timedelta
    lessons_awaiting_settlement: int
    # Job name to the last time it finished without an error.
    last_success: dict[str, datetime]


class MeasureBackgroundWork:
    """Look at the queues the jobs above empty, without touching them.

    Plain numbers come back. Turning them into metrics is the business of
    whoever asked. See ADR 0011.
    """

    def __init__(
        self, outbox: Outbox, lessons: SettlementQueue, jobs: JobLog, clock: Clock
    ) -> None:
        self._outbox = outbox
        self._lessons = lessons
        self._jobs = jobs
        self._clock = clock

    async def execute(self) -> BackgroundWork:
        now = self._clock.now()
        backlog = await self._outbox.backlog()
        oldest = backlog.oldest_queued_at
        return BackgroundWork(
            unsent_messages=backlog.waiting,
            # Never negative, whatever the clocks of two machines say.
            oldest_unsent_age=max(now - oldest, timedelta(0)) if oldest else timedelta(0),
            lessons_awaiting_settlement=await self._lessons.count_awaiting_settlement(now),
            last_success=await self._jobs.last_successes(),
        )
