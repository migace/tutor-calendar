from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.factories import NOW
from tutor_calendar.adapters.in_memory_billing import InMemoryLedger
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.application.billing import ListAccounts
from tutor_calendar.demo import demo_tutor
from tutor_calendar.demo_activity import ANNA, BARTEK, OLEK, ZOFIA, populate
from tutor_calendar.domain.billing import account_key, charge_for, is_settled
from tutor_calendar.domain.scheduling import Booking, LessonStatus, TimeRange

TUTOR = demo_tutor()
A_YEAR = timedelta(days=366)


async def seeded(now: datetime) -> tuple[InMemoryBookingRepository, InMemoryLedger]:
    bookings, ledger = InMemoryBookingRepository(), InMemoryLedger()
    assert await populate(TUTOR, bookings, ledger, now)
    return bookings, ledger


async def all_lessons(bookings: InMemoryBookingRepository, now: datetime) -> list[Booking]:
    return await bookings.starting_between(TUTOR.id, TimeRange(now - A_YEAR, now + A_YEAR))


@pytest.mark.anyio
async def test_the_demo_shows_every_kind_of_student() -> None:
    bookings, ledger = await seeded(NOW)

    accounts = {a.name: a.balance for a in await ListAccounts(ledger, bookings).execute(TUTOR)}

    # NOW is a Monday morning: three of Anna's Tuesdays and two of Bartek's
    # Thursdays are behind us.
    assert accounts == {
        "Anna Nowak": 600 - 3 * 60,
        "Bartek Lis": 120 - 2 * 60,  # used up: the next lesson will put him in debt
        "Olek Wójcik": 300,  # cancelled in time, so nothing was taken
        "Zofia Maj": -120,  # a missed lesson and a late cancellation, never paid for
    }


@pytest.mark.anyio
async def test_the_demo_has_lessons_behind_and_ahead_in_every_state() -> None:
    bookings, _ = await seeded(NOW)

    lessons = await all_lessons(bookings, NOW)

    assert {lesson.status for lesson in lessons} == set(LessonStatus)
    assert any(lesson.slot.end < NOW for lesson in lessons)
    assert sum(lesson.slot.start > NOW for lesson in lessons) >= 8
    assert sum(lesson.series_id is not None for lesson in lessons) == 8 + 6


@pytest.mark.anyio
async def test_seeding_again_adds_nothing() -> None:
    bookings, ledger = await seeded(NOW)
    before = await all_lessons(bookings, NOW)

    assert not await populate(TUTOR, bookings, ledger, NOW + timedelta(days=3))

    assert await all_lessons(bookings, NOW) == before


moments = st.datetimes(
    min_value=datetime(2026, 1, 1),  # noqa: DTZ001 - Hypothesis attaches the zone
    max_value=datetime(2028, 1, 1),  # noqa: DTZ001
    timezones=st.just(UTC),
)


@given(moments)
@settings(max_examples=150, deadline=None)
def test_whatever_day_the_demo_is_opened_on_it_is_consistent(now: datetime) -> None:
    """The demo is seeded on an arbitrary day, clock changes and all."""
    bookings, ledger = asyncio.run(seeded(now))
    lessons = asyncio.run(all_lessons(bookings, now))

    # Nothing overlaps, although the data was put together by hand.
    busy = sorted(lesson.slot for lesson in lessons if lesson.occupies_time)
    for earlier, later in pairwise(busy):
        assert earlier.end <= later.start

    # All four students are there, and every balance is exactly what was bought
    # minus the lessons that are final and charged.
    balances = asyncio.run(ledger.balances(TUTOR.id))
    bought = {ANNA.email: 600, BARTEK.email: 120, OLEK.email: 300, ZOFIA.email: 0}
    for email, paid in bought.items():
        charged = sum(
            -entry.minutes
            for lesson in lessons
            if account_key(lesson.student.email) == email and is_settled(lesson, now)
            if (entry := charge_for(lesson, now)) is not None
        )
        assert balances.get(email, 0) == paid - charged
    # There is always something to look at in the coming weeks.
    assert sum(lesson.slot.start > now for lesson in lessons) >= 6
