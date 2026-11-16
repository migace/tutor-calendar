"""A few weeks of believable activity for the demo tutor.

Everything is dated relative to today, so the demo looks lived-in whenever it
is opened: lessons that have taken place and been charged, lessons to come, a
student who is running out of prepaid time, one who owes for a missed lesson.

It goes through the same use cases as real traffic, with the clock set back to
when each thing "happened". Nothing here writes a table directly, so the demo
data obeys every rule the application enforces.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid5

from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.application.background import SettleLessons
from tutor_calendar.application.billing import RecordEntry
from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.application.ports import BookingRepository, Ledger
from tutor_calendar.application.series import StartSeries
from tutor_calendar.domain.billing import EntryKind
from tutor_calendar.domain.scheduling import (
    Actor,
    Booking,
    Student,
    Tutor,
    WeeklySeries,
    local_day,
)

ANNA = Student("Anna Nowak", "anna.nowak@example.com")
BARTEK = Student("Bartek Lis", "bartek.lis@example.com")
ZOFIA = Student("Zofia Maj", "zofia.maj@example.com")
OLEK = Student("Olek Wójcik", "olek.wojcik@example.com")

_WEEK = timedelta(weeks=1)
_DAY = timedelta(days=1)


class _Seeder:
    def __init__(
        self, tutor: Tutor, bookings: BookingRepository, ledger: Ledger, now: datetime
    ) -> None:
        self.tutor = tutor
        self.bookings = bookings
        self.ledger = ledger
        self.now = now
        today = local_day(now, tutor.schedule.timezone)
        self.this_monday = today - today.weekday() * _DAY

    def _id(self, name: str) -> UUID:
        # Derived from the tutor, so seeding twice cannot create anything twice.
        return uuid5(self.tutor.id, name)

    async def weekly(
        self, student: Student, *, weeks_ago: int, weekday: int, start: time, weeks: int
    ) -> None:
        first_day = self.this_monday - weeks_ago * _WEEK + weekday * _DAY
        plan = WeeklySeries(first_day=first_day, start=start, weeks=weeks, student=student)
        # Set up, as it would have been, a few days before the first lesson.
        set_up = FixedClock(self.now - weeks_ago * _WEEK - 4 * _DAY)
        await StartSeries(self.bookings, set_up).execute(
            self.tutor, self._id(f"series-{student.email}"), plan, skip_conflicts=True
        )

    async def single(self, student: Student, day: date, start: time) -> Booking | None:
        """One lesson on a day at a wall-clock time, booked five days ahead."""
        plan = WeeklySeries(first_day=day, start=start, weeks=1, student=student)
        lessons, _ = plan.lay_out(self.tutor.schedule)
        if not lessons:
            return None  # the clocks skipped that time on that day
        lesson = Booking(
            id=self._id(f"lesson-{day}-{start}"),
            tutor_id=self.tutor.id,
            slot=lessons[0].slot,
            student=student,
            created_at=lessons[0].slot.start - 5 * _DAY,
        )
        try:
            return await self.bookings.add(lesson, f"demo-{lesson.id}")
        except SlotTakenError:
            # The time went to a weekly lesson: the demo has one lesson fewer.
            return None

    async def package(self, student: Student, minutes: int, days_ago: int, note: str) -> None:
        bought = FixedClock(self.now - days_ago * _DAY)
        await RecordEntry(self.ledger, bought).execute(
            self.tutor,
            self._id(f"package-{student.email}-{days_ago}"),
            student.email,
            EntryKind.PURCHASE,
            minutes,
            note,
        )


async def populate(
    tutor: Tutor, bookings: BookingRepository, ledger: Ledger, now: datetime
) -> bool:
    """Fill the tutor's calendar and accounts. Returns False if there was activity already."""
    if await bookings.students(tutor.id):
        return False

    seed = _Seeder(tutor, bookings, ledger, now)
    last_week = seed.this_monday - _WEEK
    policy = tutor.cancellation_policy

    # Two regulars. Anna prepaid generously; Bartek's package is about to run out.
    await seed.weekly(ANNA, weeks_ago=3, weekday=1, start=time(17, 0), weeks=8)
    await seed.weekly(BARTEK, weeks_ago=2, weekday=3, start=time(16, 0), weeks=6)
    await seed.package(ANNA, 600, days_ago=24, note="Package of 10 lessons")
    await seed.package(BARTEK, 120, days_ago=16, note="Two trial lessons")

    # Zofia missed one lesson and cancelled another too late: both are charged,
    # and she has paid for neither. She has one more booked.
    missed = await seed.single(ZOFIA, last_week + 2 * _DAY, time(15, 0))
    if missed is not None:
        after_start = missed.slot.start + timedelta(minutes=15)
        await bookings.apply([(missed, missed.mark_no_show(after_start))])
    too_late = await seed.single(ZOFIA, last_week, time(18, 0))
    if too_late is not None:
        two_hours_before = too_late.slot.start - timedelta(hours=2)
        await bookings.apply([(too_late, too_late.cancel(Actor.STUDENT, two_hours_before, policy))])
    await seed.single(ZOFIA, seed.this_monday + _WEEK + 5 * _DAY, time(10, 0))

    # Olek cancelled in good time, so his package is untouched.
    in_time = await seed.single(OLEK, last_week + 5 * _DAY, time(9, 0))
    if in_time is not None:
        three_days_before = in_time.slot.start - 3 * _DAY
        await bookings.apply([(in_time, in_time.cancel(Actor.STUDENT, three_days_before, policy))])
    await seed.package(OLEK, 300, days_ago=10, note="Package of 5 lessons")

    # Charge everything that has already happened, exactly as the worker would.
    await SettleLessons(bookings, ledger, FixedClock(now)).execute()
    return True
