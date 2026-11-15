from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from tests.factories import ANNA, FIRST_SLOT, NOW
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.application.book_lesson import BookLesson
from tutor_calendar.application.errors import (
    IdempotencyKeyReusedError,
    SlotNotOfferedError,
    SlotTakenError,
    TutorNotFoundError,
)
from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.demo import demo_tutor
from tutor_calendar.domain.scheduling import Booking, Student, TimeRange

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
BARTEK = Student("Bartek Lis", "bartek@example.com")


class Scenario:
    """The demo tutor, an empty calendar and a clock that tests can move."""

    def __init__(self) -> None:
        self.tutors = InMemoryTutorRepository([demo_tutor()])
        self.bookings = InMemoryBookingRepository()
        self.now = NOW

    @property
    def book(self) -> BookLesson:
        return BookLesson(self.tutors, self.bookings, FixedClock(self.now))

    async def free_slots(self) -> list[datetime]:
        use_case = ListAvailableSlots(self.tutors, self.bookings, FixedClock(self.now))
        return [slot.start for slot in (await use_case.execute("demo")).slots]


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


async def test_books_a_slot_the_tutor_offers(scenario: Scenario) -> None:
    result = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    assert not result.replayed
    assert result.booking.slot == TimeRange(FIRST_SLOT, FIRST_SLOT + HOUR)
    assert result.booking.student == ANNA
    assert result.booking.created_at == NOW


async def test_a_booked_slot_is_no_longer_offered(scenario: Scenario) -> None:
    assert FIRST_SLOT in await scenario.free_slots()

    await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    free = await scenario.free_slots()
    assert FIRST_SLOT not in free
    assert FIRST_SLOT + HOUR in free


async def test_a_slot_can_only_be_booked_once(scenario: Scenario) -> None:
    await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    with pytest.raises(SlotTakenError):
        await scenario.book.execute("demo", FIRST_SLOT, BARTEK, "key-2")


async def test_unknown_tutor(scenario: Scenario) -> None:
    with pytest.raises(TutorNotFoundError):
        await scenario.book.execute("nobody", FIRST_SLOT, ANNA, "key-1")


@pytest.mark.parametrize(
    "start",
    [
        pytest.param(FIRST_SLOT + timedelta(minutes=30), id="between two slots"),
        pytest.param(FIRST_SLOT - HOUR, id="before the tutor starts"),
        pytest.param(FIRST_SLOT + 4 * HOUR, id="when the tutor finishes"),
        pytest.param(FIRST_SLOT + timedelta(days=3), id="on a day the tutor does not teach"),
        pytest.param(FIRST_SLOT + timedelta(seconds=1), id="a second off the grid"),
    ],
)
async def test_only_times_on_the_tutors_grid_can_be_booked(
    scenario: Scenario, start: datetime
) -> None:
    with pytest.raises(SlotNotOfferedError):
        await scenario.book.execute("demo", start, ANNA, "key-1")


async def test_a_time_inside_the_notice_period_cannot_be_booked(scenario: Scenario) -> None:
    # Monday 15:00 Warsaw is a real slot, but only six hours away; the tutor needs twelve.
    with pytest.raises(SlotNotOfferedError):
        await scenario.book.execute("demo", FIRST_SLOT - timedelta(days=1), ANNA, "key-1")


async def test_repeating_a_request_returns_the_first_booking(scenario: Scenario) -> None:
    first = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    again = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    assert again.replayed
    assert again.booking == first.booking
    assert await scenario.bookings.busy_between(first.booking.tutor_id, _around(FIRST_SLOT)) == [
        first.booking.slot
    ]


async def test_a_repeat_still_succeeds_once_the_slot_is_inside_the_notice_period(
    scenario: Scenario,
) -> None:
    first = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")
    scenario.now = FIRST_SLOT - HOUR

    again = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    assert again.replayed
    assert again.booking == first.booking


@pytest.mark.parametrize(
    ("start", "student"),
    [
        pytest.param(FIRST_SLOT + HOUR, ANNA, id="another time"),
        pytest.param(FIRST_SLOT, BARTEK, id="another student"),
    ],
)
async def test_a_key_cannot_be_reused_for_a_different_request(
    scenario: Scenario, start: datetime, student: Student
) -> None:
    await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    with pytest.raises(IdempotencyKeyReusedError):
        await scenario.book.execute("demo", start, student, "key-1")


async def test_losing_a_race_against_the_same_key_counts_as_a_repeat(scenario: Scenario) -> None:
    class KeyAppearsOnlyOnWrite(InMemoryBookingRepository):
        """Looks as it does to a request whose twin commits between its read and its write."""

        async def get_by_idempotency_key(self, tutor_id: UUID, key: str) -> Booking | None:
            return None

    scenario.bookings = KeyAppearsOnlyOnWrite()
    first = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    twin = await scenario.book.execute("demo", FIRST_SLOT, ANNA, "key-1")

    assert twin.replayed
    assert twin.booking == first.booking


def _around(instant: datetime) -> TimeRange:
    return TimeRange(instant - 12 * HOUR, instant + 12 * HOUR)
