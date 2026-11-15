from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from tests.factories import ANNA, FIRST_SLOT, NOW
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.application.book_lesson import BookLesson
from tutor_calendar.application.errors import InvalidAvailabilityError
from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.application.tutor_panel import ChangeWeeklyHours, ShowWeek
from tutor_calendar.demo import demo_tutor
from tutor_calendar.domain.scheduling import Weekday, WeeklyRule

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
FRIDAY_MORNING = WeeklyRule(Weekday.FRIDAY, time(8, 0), time(10, 0))


class Scenario:
    def __init__(self) -> None:
        self.tutor = demo_tutor()
        self.tutors = InMemoryTutorRepository([self.tutor])
        self.bookings = InMemoryBookingRepository()
        self.now = NOW

    @property
    def clock(self) -> FixedClock:
        return FixedClock(self.now)

    async def book(self, start: datetime, key: str) -> None:
        await BookLesson(self.tutors, self.bookings, self.clock).execute("demo", start, ANNA, key)

    async def free_slots(self) -> list[datetime]:
        use_case = ListAvailableSlots(self.tutors, self.bookings, self.clock)
        return [slot.start for slot in (await use_case.execute("demo")).slots]


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


async def test_shows_the_current_week_with_its_lessons(scenario: Scenario) -> None:
    await scenario.book(FIRST_SLOT + HOUR, "key-1")
    await scenario.book(FIRST_SLOT, "key-2")
    await scenario.book(FIRST_SLOT + timedelta(days=7), "key-3")  # next week

    view = await ShowWeek(scenario.bookings, scenario.clock).execute(scenario.tutor)

    assert view.today == date(2026, 11, 16)
    assert view.week.start == date(2026, 11, 16)
    tuesday = view.week.days[1]
    assert [lesson.slot.start for lesson in tuesday.lessons] == [FIRST_SLOT, FIRST_SLOT + HOUR]
    assert sum(len(day.lessons) for day in view.week.days) == 2


async def test_today_is_the_tutors_day_not_the_servers(scenario: Scenario) -> None:
    # 23:30 UTC on Sunday is already Monday in Warsaw, and so a new week.
    scenario.now = datetime(2026, 11, 22, 23, 30, tzinfo=UTC)

    view = await ShowWeek(scenario.bookings, scenario.clock).execute(scenario.tutor)

    assert view.today == date(2026, 11, 23)
    assert view.week.start == date(2026, 11, 23)


async def test_shows_the_week_containing_any_requested_day(scenario: Scenario) -> None:
    await scenario.book(FIRST_SLOT + timedelta(days=7), "key-1")

    view = await ShowWeek(scenario.bookings, scenario.clock).execute(
        scenario.tutor, date(2026, 11, 29)
    )

    assert (view.week.previous, view.week.start, view.week.next) == (
        date(2026, 11, 16),
        date(2026, 11, 23),
        date(2026, 11, 30),
    )
    assert len(view.week.days[1].lessons) == 1
    assert view.today == date(2026, 11, 16)


async def test_new_hours_change_what_visitors_are_offered(scenario: Scenario) -> None:
    changed = await ChangeWeeklyHours(scenario.tutors).execute(scenario.tutor, [FRIDAY_MORNING])

    assert changed.schedule.rules == (FRIDAY_MORNING,)
    assert await scenario.tutors.get_by_slug("demo") == changed
    # Friday 08:00 and 09:00 in Warsaw, this week and next.
    assert await scenario.free_slots() == [
        datetime(2026, 11, 20, 7, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 8, 0, tzinfo=UTC),
        datetime(2026, 11, 27, 7, 0, tzinfo=UTC),
        datetime(2026, 11, 27, 8, 0, tzinfo=UTC),
    ]


async def test_lessons_already_booked_survive_a_change_of_hours(scenario: Scenario) -> None:
    await scenario.book(FIRST_SLOT, "key-1")

    changed = await ChangeWeeklyHours(scenario.tutors).execute(scenario.tutor, [FRIDAY_MORNING])

    view = await ShowWeek(scenario.bookings, scenario.clock).execute(changed)
    assert [lesson.slot.start for lesson in view.week.days[1].lessons] == [FIRST_SLOT]


async def test_a_tutor_may_stop_offering_lessons_altogether(scenario: Scenario) -> None:
    await ChangeWeeklyHours(scenario.tutors).execute(scenario.tutor, [])

    assert await scenario.free_slots() == []


@pytest.mark.parametrize(
    "rules",
    [
        pytest.param(
            [
                WeeklyRule(Weekday.MONDAY, time(9, 0), time(12, 0)),
                WeeklyRule(Weekday.MONDAY, time(11, 0), time(13, 0)),
            ],
            id="overlapping on one day",
        ),
        pytest.param(
            [
                WeeklyRule(Weekday.MONDAY, time(9, 0), time(12, 0)),
                WeeklyRule(Weekday.MONDAY, time(9, 0), time(12, 0)),
            ],
            id="the same hours twice",
        ),
    ],
)
async def test_contradictory_hours_are_refused_and_nothing_changes(
    scenario: Scenario, rules: list[WeeklyRule]
) -> None:
    with pytest.raises(InvalidAvailabilityError, match="overlap on Monday"):
        await ChangeWeeklyHours(scenario.tutors).execute(scenario.tutor, rules)

    assert await scenario.tutors.get_by_slug("demo") == scenario.tutor


async def test_hours_that_touch_do_not_overlap(scenario: Scenario) -> None:
    morning = WeeklyRule(Weekday.MONDAY, time(9, 0), time(12, 0))
    afternoon = WeeklyRule(Weekday.MONDAY, time(12, 0), time(15, 0))

    changed = await ChangeWeeklyHours(scenario.tutors).execute(scenario.tutor, [afternoon, morning])

    assert changed.schedule.rules == (morning, afternoon)
