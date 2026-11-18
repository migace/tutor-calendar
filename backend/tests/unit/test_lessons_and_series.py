"""Cancelling lessons and running weekly series, with fakes behind the use cases."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest

from tests.factories import ANNA, FIRST_SLOT, LINKS, NOW, a_tutor
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.application.book_lesson import BookingResult, BookLesson
from tutor_calendar.application.errors import (
    InvalidSeriesError,
    LessonChangeRefusedError,
    LessonNotFoundError,
    SeriesConflictError,
    SeriesNotFoundError,
    SlotTakenError,
)
from tutor_calendar.application.lessons import ChangeOwnLesson, ManageBooking
from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.application.series import EndSeries, ListSeries, StartSeries
from tutor_calendar.demo import demo_tutor
from tutor_calendar.domain.scheduling import (
    Actor,
    Booking,
    LessonStatus,
    Student,
    WeeklySeries,
)

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
BARTEK = Student("Bartek Lis", "bartek@example.com")
# Tuesdays at 17:00 Warsaw time, starting with the first Tuesday after NOW.
TUESDAYS_AT_FIVE = WeeklySeries(
    first_day=date(2026, 11, 17), start=time(17, 0), weeks=4, student=ANNA
)
FIVE_ON_THE_17TH = FIRST_SLOT + 2 * HOUR


class Scenario:
    def __init__(self) -> None:
        self.tutor = demo_tutor()  # free cancellation until 24 hours before
        self.other_tutor = a_tutor("ewa")
        self.tutors = InMemoryTutorRepository([self.tutor, self.other_tutor])
        self.bookings = InMemoryBookingRepository()
        self.now = NOW

    @property
    def clock(self) -> FixedClock:
        return FixedClock(self.now)

    async def book(self, start: datetime = FIRST_SLOT, student: Student = ANNA) -> BookingResult:
        use_case = BookLesson(self.tutors, self.bookings, LINKS, self.clock)
        return await use_case.execute("demo", start, student, f"key-{uuid4()}")

    @property
    def manage(self) -> ManageBooking:
        return ManageBooking(self.bookings, self.tutors, LINKS, self.clock)

    @property
    def own(self) -> ChangeOwnLesson:
        return ChangeOwnLesson(self.bookings, self.clock)

    @property
    def start_series(self) -> StartSeries:
        return StartSeries(self.bookings, self.clock)

    async def free_slots(self) -> list[datetime]:
        use_case = ListAvailableSlots(self.tutors, self.bookings, self.clock)
        return [slot.start for slot in (await use_case.execute("demo")).slots]


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


class TestAStudentManagingTheirBooking:
    async def test_the_link_shows_the_lesson_and_the_cancellation_terms(
        self, scenario: Scenario
    ) -> None:
        booked = await scenario.book()

        managed = await scenario.manage.view(booked.manage_token)

        assert managed.lesson == booked.booking
        assert managed.tutor == scenario.tutor
        assert managed.free_until == FIRST_SLOT - timedelta(hours=24)
        assert managed.can_cancel
        assert not managed.late_now

    async def test_cancelling_in_time_is_free_and_gives_the_slot_back(
        self, scenario: Scenario
    ) -> None:
        booked = await scenario.book()
        assert FIRST_SLOT not in await scenario.free_slots()

        managed = await scenario.manage.cancel(booked.manage_token)

        assert managed.lesson.status is LessonStatus.CANCELLED
        assert not managed.lesson.is_charged
        assert not managed.can_cancel
        assert FIRST_SLOT in await scenario.free_slots()
        # And someone else can take it.
        assert (await scenario.book(FIRST_SLOT, BARTEK)).booking.student == BARTEK

    async def test_cancelling_late_is_allowed_but_charged(self, scenario: Scenario) -> None:
        booked = await scenario.book()
        scenario.now = FIRST_SLOT - 3 * HOUR

        before = await scenario.manage.view(booked.manage_token)
        after = await scenario.manage.cancel(booked.manage_token)

        assert before.can_cancel
        assert before.late_now
        assert after.lesson.cancellation is not None
        assert after.lesson.cancellation.late
        assert after.lesson.is_charged

    async def test_a_lesson_that_has_started_cannot_be_cancelled(self, scenario: Scenario) -> None:
        booked = await scenario.book()
        scenario.now = FIRST_SLOT + timedelta(minutes=1)

        assert not (await scenario.manage.view(booked.manage_token)).can_cancel
        with pytest.raises(LessonChangeRefusedError, match="has started"):
            await scenario.manage.cancel(booked.manage_token)

    async def test_cancelling_twice_is_refused(self, scenario: Scenario) -> None:
        booked = await scenario.book()
        await scenario.manage.cancel(booked.manage_token)

        with pytest.raises(LessonChangeRefusedError):
            await scenario.manage.cancel(booked.manage_token)

    @pytest.mark.parametrize("token", ["", "made-up", f"{uuid4().hex}.signature"])
    async def test_a_forged_link_shows_nothing(self, scenario: Scenario, token: str) -> None:
        await scenario.book()

        with pytest.raises(LessonNotFoundError):
            await scenario.manage.view(token)
        with pytest.raises(LessonNotFoundError):
            await scenario.manage.cancel(token)

    async def test_a_valid_link_for_a_booking_that_is_not_there_shows_nothing(
        self, scenario: Scenario
    ) -> None:
        with pytest.raises(LessonNotFoundError):
            await scenario.manage.view(LINKS.token_for(uuid4()))

    async def test_a_repeated_booking_request_gets_the_same_link(self, scenario: Scenario) -> None:
        use_case = BookLesson(scenario.tutors, scenario.bookings, LINKS, scenario.clock)
        first = await use_case.execute("demo", FIRST_SLOT, ANNA, "key-1")

        again = await use_case.execute("demo", FIRST_SLOT, ANNA, "key-1")

        assert again.replayed
        assert again.manage_token == first.manage_token


class TestATutorChangingTheirLessons:
    async def test_a_tutor_cancels_without_charging_however_late(self, scenario: Scenario) -> None:
        booked = await scenario.book()
        scenario.now = FIRST_SLOT - timedelta(minutes=5)

        cancelled = await scenario.own.cancel(scenario.tutor, booked.booking.id)

        assert cancelled.cancellation is not None
        assert cancelled.cancellation.by is Actor.TUTOR
        assert not cancelled.is_charged

    async def test_a_no_show_can_be_recorded_once_the_lesson_has_begun(
        self, scenario: Scenario
    ) -> None:
        booked = await scenario.book()

        with pytest.raises(LessonChangeRefusedError, match="has not started"):
            await scenario.own.mark_no_show(scenario.tutor, booked.booking.id)

        scenario.now = FIRST_SLOT + timedelta(minutes=20)
        missed = await scenario.own.mark_no_show(scenario.tutor, booked.booking.id)

        assert missed.status is LessonStatus.NO_SHOW
        assert await scenario.bookings.get(missed.id) == missed

    async def test_another_tutors_lesson_looks_like_it_does_not_exist(
        self, scenario: Scenario
    ) -> None:
        booked = await scenario.book()

        with pytest.raises(LessonNotFoundError):
            await scenario.own.cancel(scenario.other_tutor, booked.booking.id)
        with pytest.raises(LessonNotFoundError):
            await scenario.own.cancel(scenario.tutor, uuid4())
        assert (await scenario.bookings.get(booked.booking.id)) == booked.booking

    async def test_losing_a_race_to_change_a_lesson_is_a_refusal(self, scenario: Scenario) -> None:
        class SomeoneElseGotThereFirst(InMemoryBookingRepository):
            async def apply(self, changes: Sequence[tuple[Booking, Booking]]) -> int:
                return 0

        scenario.bookings = SomeoneElseGotThereFirst()
        booked = await scenario.book()

        with pytest.raises(LessonChangeRefusedError, match="changed by someone else"):
            await scenario.own.cancel(scenario.tutor, booked.booking.id)


class TestWeeklySeries:
    async def test_a_series_books_one_lesson_a_week(self, scenario: Scenario) -> None:
        series_id = uuid4()

        overview = await scenario.start_series.execute(scenario.tutor, series_id, TUESDAYS_AT_FIVE)

        assert [lesson.slot.start for lesson in overview.lessons] == [
            FIVE_ON_THE_17TH + timedelta(weeks=n) for n in range(4)
        ]
        assert all(lesson.series_id == series_id for lesson in overview.lessons)
        assert all(lesson.student == ANNA for lesson in overview.lessons)
        assert overview.days_without_lesson == []
        # Its lessons are ordinary bookings: visitors are no longer offered those times.
        assert FIVE_ON_THE_17TH not in await scenario.free_slots()

    async def test_a_tutor_may_schedule_a_regular_outside_their_public_hours(
        self, scenario: Scenario
    ) -> None:
        fridays = WeeklySeries(date(2026, 11, 20), time(7, 30), 2, ANNA)  # the tutor's day off

        overview = await scenario.start_series.execute(scenario.tutor, uuid4(), fridays)

        assert len(overview.lessons) == 2

    async def test_asking_again_with_the_same_id_creates_nothing_new(
        self, scenario: Scenario
    ) -> None:
        series_id = uuid4()
        first = await scenario.start_series.execute(scenario.tutor, series_id, TUESDAYS_AT_FIVE)

        again = await scenario.start_series.execute(scenario.tutor, series_id, TUESDAYS_AT_FIVE)

        assert again == first
        assert len(await ListSeries(scenario.bookings).execute(scenario.tutor)) == 1

    async def test_an_id_cannot_be_reused_for_a_different_plan(self, scenario: Scenario) -> None:
        series_id = uuid4()
        await scenario.start_series.execute(scenario.tutor, series_id, TUESDAYS_AT_FIVE)
        other_plan = WeeklySeries(date(2026, 11, 18), time(17, 0), 4, ANNA)

        with pytest.raises(InvalidSeriesError, match="different series"):
            await scenario.start_series.execute(scenario.tutor, series_id, other_plan)
        with pytest.raises(InvalidSeriesError, match="different series"):
            await scenario.start_series.execute(scenario.other_tutor, series_id, TUESDAYS_AT_FIVE)

    async def test_a_clash_stops_the_whole_series_and_names_the_lessons_in_the_way(
        self, scenario: Scenario
    ) -> None:
        await scenario.book(FIVE_ON_THE_17TH + timedelta(weeks=1), BARTEK)

        with pytest.raises(SeriesConflictError) as refused:
            await scenario.start_series.execute(scenario.tutor, uuid4(), TUESDAYS_AT_FIVE)

        assert [slot.start for slot in refused.value.slots] == [
            FIVE_ON_THE_17TH + timedelta(weeks=1)
        ]
        assert await ListSeries(scenario.bookings).execute(scenario.tutor) == []
        assert FIVE_ON_THE_17TH in await scenario.free_slots()

    async def test_the_tutor_can_choose_to_leave_the_clashing_weeks_out(
        self, scenario: Scenario
    ) -> None:
        await scenario.book(FIVE_ON_THE_17TH + timedelta(weeks=1), BARTEK)

        overview = await scenario.start_series.execute(
            scenario.tutor, uuid4(), TUESDAYS_AT_FIVE, skip_conflicts=True
        )

        assert len(overview.lessons) == 3
        assert overview.days_without_lesson == [date(2026, 11, 24)]

    async def test_a_cancelled_lesson_is_not_in_the_way(self, scenario: Scenario) -> None:
        booked = await scenario.book(FIVE_ON_THE_17TH + timedelta(weeks=1), BARTEK)
        await scenario.manage.cancel(booked.manage_token)

        overview = await scenario.start_series.execute(scenario.tutor, uuid4(), TUESDAYS_AT_FIVE)

        assert len(overview.lessons) == 4

    async def test_only_lessons_still_to_come_are_booked(self, scenario: Scenario) -> None:
        started_last_week = WeeklySeries(date(2026, 11, 10), time(17, 0), 3, ANNA)

        overview = await scenario.start_series.execute(scenario.tutor, uuid4(), started_last_week)

        assert [lesson.slot.start for lesson in overview.lessons] == [
            FIVE_ON_THE_17TH,
            FIVE_ON_THE_17TH + timedelta(weeks=1),
        ]
        assert overview.days_without_lesson == [date(2026, 11, 10)]

    async def test_a_series_entirely_in_the_past_is_refused(self, scenario: Scenario) -> None:
        long_ago = WeeklySeries(date(2026, 1, 6), time(17, 0), 4, ANNA)

        with pytest.raises(InvalidSeriesError, match="in the future"):
            await scenario.start_series.execute(scenario.tutor, uuid4(), long_ago)

    async def test_a_single_lesson_of_a_series_can_be_cancelled_on_its_own(
        self, scenario: Scenario
    ) -> None:
        overview = await scenario.start_series.execute(scenario.tutor, uuid4(), TUESDAYS_AT_FIVE)

        await scenario.own.cancel(scenario.tutor, overview.lessons[1].id)

        [listed] = await ListSeries(scenario.bookings).execute(scenario.tutor)
        assert [lesson.status for lesson in listed.lessons] == [
            LessonStatus.CONFIRMED,
            LessonStatus.CANCELLED,
            LessonStatus.CONFIRMED,
            LessonStatus.CONFIRMED,
        ]
        assert FIVE_ON_THE_17TH + timedelta(weeks=1) in await scenario.free_slots()

    async def test_ending_a_series_cancels_what_is_left_and_keeps_the_past(
        self, scenario: Scenario
    ) -> None:
        series_id = uuid4()
        await scenario.start_series.execute(scenario.tutor, series_id, TUESDAYS_AT_FIVE)
        # A week and a half later: one lesson has taken place.
        scenario.now = FIVE_ON_THE_17TH + timedelta(days=3)

        ended = await EndSeries(scenario.bookings, scenario.bookings, scenario.clock).execute(
            scenario.tutor, series_id
        )

        assert [lesson.status for lesson in ended.lessons] == [
            LessonStatus.CONFIRMED,
            LessonStatus.CANCELLED,
            LessonStatus.CANCELLED,
            LessonStatus.CANCELLED,
        ]
        assert not any(lesson.is_charged for lesson in ended.lessons[1:])

    async def test_only_the_tutor_who_owns_a_series_can_end_it(self, scenario: Scenario) -> None:
        series_id = uuid4()
        await scenario.start_series.execute(scenario.tutor, series_id, TUESDAYS_AT_FIVE)
        end = EndSeries(scenario.bookings, scenario.bookings, scenario.clock)

        with pytest.raises(SeriesNotFoundError):
            await end.execute(scenario.other_tutor, series_id)
        with pytest.raises(SeriesNotFoundError):
            await end.execute(scenario.tutor, uuid4())

    async def test_a_visitor_cannot_book_over_a_series_lesson(self, scenario: Scenario) -> None:
        await scenario.start_series.execute(scenario.tutor, uuid4(), TUESDAYS_AT_FIVE)

        with pytest.raises(SlotTakenError):
            await scenario.book(FIVE_ON_THE_17TH, BARTEK)
