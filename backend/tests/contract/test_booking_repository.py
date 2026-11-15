"""What every booking repository must do, checked against each implementation.

The in-memory fake is only useful in other tests if it behaves like the real
thing. Running one set of tests against both is what keeps that true.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import ANNA, FIRST_SLOT, a_booking, a_tutor
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.application.ports import BookingRepository
from tutor_calendar.domain.scheduling import Student, TimeRange, Tutor

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
WHOLE_DAY = TimeRange(FIRST_SLOT - 12 * HOUR, FIRST_SLOT + 12 * HOUR)


class BookingRepositoryContract:
    async def test_a_stored_booking_can_be_found_by_its_key(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        booking = a_booking(tutor.id)

        stored = await repository.add(booking, "key-1")

        assert stored == booking
        assert await repository.get_by_idempotency_key(tutor.id, "key-1") == booking
        assert await repository.get_by_idempotency_key(tutor.id, "key-2") is None

    @pytest.mark.parametrize(
        ("offset_minutes", "minutes"),
        [
            (0, 60),  # the very same time
            (30, 60),  # starts halfway through
            (-30, 60),  # ends halfway through
            (15, 30),  # lies inside
            (-15, 90),  # covers it completely
        ],
    )
    async def test_an_overlapping_booking_is_refused(
        self, repository: BookingRepository, tutor: Tutor, offset_minutes: int, minutes: int
    ) -> None:
        await repository.add(a_booking(tutor.id), "key-1")
        start = FIRST_SLOT + timedelta(minutes=offset_minutes)

        with pytest.raises(SlotTakenError):
            await repository.add(a_booking(tutor.id, start, minutes), "key-2")

        assert await repository.busy_between(tutor.id, WHOLE_DAY) == [
            TimeRange(FIRST_SLOT, FIRST_SLOT + HOUR)
        ]

    async def test_back_to_back_bookings_do_not_overlap(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id, FIRST_SLOT), "key-1")

        await repository.add(a_booking(tutor.id, FIRST_SLOT + HOUR), "key-2")
        await repository.add(a_booking(tutor.id, FIRST_SLOT - HOUR), "key-3")

        assert len(await repository.busy_between(tutor.id, WHOLE_DAY)) == 3

    async def test_tutors_do_not_compete_for_time(
        self, repository: BookingRepository, tutor: Tutor, other_tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id), "key-1")

        await repository.add(a_booking(other_tutor.id), "key-1")

        assert len(await repository.busy_between(tutor.id, WHOLE_DAY)) == 1
        assert len(await repository.busy_between(other_tutor.id, WHOLE_DAY)) == 1

    async def test_a_repeated_key_returns_the_first_booking_and_stores_nothing(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        first = await repository.add(a_booking(tutor.id), "key-1")

        same_slot = await repository.add(a_booking(tutor.id), "key-1")
        other_slot = await repository.add(a_booking(tutor.id, FIRST_SLOT + 3 * HOUR), "key-1")

        assert same_slot == first
        assert other_slot == first
        assert await repository.busy_between(tutor.id, WHOLE_DAY) == [first.slot]

    async def test_a_refused_booking_does_not_use_up_its_key(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id), "key-1")
        with pytest.raises(SlotTakenError):
            await repository.add(a_booking(tutor.id), "key-2")

        later = a_booking(tutor.id, FIRST_SLOT + HOUR)

        assert await repository.add(later, "key-2") == later

    async def test_busy_times_are_those_overlapping_the_window_in_order(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        for index, hours in enumerate((4, 0, 2, 1)):
            await repository.add(a_booking(tutor.id, FIRST_SLOT + hours * HOUR), f"key-{index}")

        # From halfway through the second lesson to the exact start of the fifth.
        window = TimeRange(FIRST_SLOT + 1.5 * HOUR, FIRST_SLOT + 4 * HOUR)

        assert [slot.start for slot in await repository.busy_between(tutor.id, window)] == [
            FIRST_SLOT + HOUR,
            FIRST_SLOT + 2 * HOUR,
        ]

    async def test_of_many_simultaneous_attempts_at_one_slot_exactly_one_wins(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        attempts = [
            repository.add(
                a_booking(tutor.id, student=Student(f"Student {n}", f"s{n}@example.com")),
                f"key-{n}",
            )
            for n in range(12)
        ]

        outcomes = await asyncio.gather(*attempts, return_exceptions=True)

        refused = [outcome for outcome in outcomes if isinstance(outcome, SlotTakenError)]
        assert len(refused) == 11
        assert len(await repository.busy_between(tutor.id, WHOLE_DAY)) == 1

    async def test_simultaneous_attempts_with_one_key_store_one_booking(
        self, repository: BookingRepository, tutor: Tutor
    ) -> None:
        attempts = [repository.add(a_booking(tutor.id, student=ANNA), "key-1") for _ in range(12)]

        outcomes = await asyncio.gather(*attempts)

        assert len({booking.id for booking in outcomes}) == 1
        assert len(await repository.busy_between(tutor.id, WHOLE_DAY)) == 1


class TestInMemoryBookingRepository(BookingRepositoryContract):
    @pytest.fixture
    def repository(self) -> BookingRepository:
        return InMemoryBookingRepository()

    @pytest.fixture
    def tutor(self) -> Tutor:
        return a_tutor("ewa")

    @pytest.fixture
    def other_tutor(self) -> Tutor:
        return a_tutor("jan")


@pytest.mark.integration
class TestPostgresBookingRepository(BookingRepositoryContract):
    @pytest.fixture
    def repository(self, engine: AsyncEngine) -> BookingRepository:
        return PostgresBookingRepository(engine)

    @pytest.fixture
    async def tutor(self, engine: AsyncEngine) -> Tutor:
        return await _stored(engine, a_tutor("ewa"))

    @pytest.fixture
    async def other_tutor(self, engine: AsyncEngine) -> Tutor:
        return await _stored(engine, a_tutor("jan"))


async def _stored(engine: AsyncEngine, tutor: Tutor) -> Tutor:
    # Bookings reference tutors, so the tutor has to exist first.
    assert await PostgresTutorRepository(engine).add_if_absent(tutor)
    return tutor
