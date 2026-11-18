"""Changing stored lessons and storing weekly series, against each implementation."""

from __future__ import annotations

import asyncio
from datetime import date, time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import ANNA, FIRST_SLOT, NOW, a_booking, a_tutor
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.errors import SeriesConflictError, SlotTakenError
from tutor_calendar.application.ports import LessonStore
from tutor_calendar.domain.scheduling import (
    Actor,
    AlwaysFree,
    Booking,
    FreeUntil,
    LessonSeries,
    LessonStatus,
    TimeRange,
    Tutor,
    WeeklySeries,
)

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
WEEK = timedelta(weeks=1)
WHOLE_DAY = TimeRange(FIRST_SLOT - 12 * HOUR, FIRST_SLOT + 12 * HOUR)
EARLIER = FIRST_SLOT - timedelta(days=2)


def cancelled(lesson: Booking, by: Actor = Actor.STUDENT) -> Booking:
    return lesson.cancel(by, EARLIER, AlwaysFree())


def a_series(tutor: Tutor, weeks: int = 3) -> tuple[LessonSeries, list[Booking]]:
    """A series of weekly lessons at FIRST_SLOT's time, with its lessons."""
    series = LessonSeries(
        id=uuid4(),
        tutor_id=tutor.id,
        plan=WeeklySeries(date(2026, 11, 17), time(15, 0), weeks, ANNA),
        created_at=NOW,
    )
    lessons = [
        Booking(
            id=uuid4(),
            tutor_id=tutor.id,
            slot=TimeRange(FIRST_SLOT + n * WEEK, FIRST_SLOT + n * WEEK + HOUR),
            student=ANNA,
            created_at=NOW,
            series_id=series.id,
        )
        for n in range(weeks)
    ]
    return series, lessons


class LessonChangesContract:
    async def test_a_lesson_is_found_by_its_id(self, repository: LessonStore, tutor: Tutor) -> None:
        lesson = await repository.add(a_booking(tutor.id), "key-1")

        assert await repository.get(lesson.id) == lesson
        assert await repository.get(uuid4()) is None

    async def test_a_cancellation_is_stored_with_all_its_details(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        lesson = await repository.add(a_booking(tutor.id), "key-1")
        late = lesson.cancel(Actor.STUDENT, FIRST_SLOT - HOUR, FreeUntil(timedelta(hours=24)))

        assert await repository.apply([(lesson, late)]) == 1

        stored = await repository.get(lesson.id)
        assert stored == late
        assert stored is not None
        assert stored.is_charged

    async def test_a_cancelled_lesson_gives_its_time_back(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        lesson = await repository.add(a_booking(tutor.id), "key-1")
        await repository.apply([(lesson, cancelled(lesson))])

        assert await repository.busy_between(tutor.id, WHOLE_DAY) == []
        replacement = await repository.add(a_booking(tutor.id), "key-2")

        # Both are kept: the tutor still sees what was called off.
        assert await repository.starting_between(tutor.id, WHOLE_DAY) in (
            [cancelled(lesson), replacement],
            [replacement, cancelled(lesson)],
        )

    async def test_a_no_show_keeps_its_time(self, repository: LessonStore, tutor: Tutor) -> None:
        lesson = await repository.add(a_booking(tutor.id), "key-1")
        await repository.apply([(lesson, lesson.mark_no_show(FIRST_SLOT + HOUR))])

        with pytest.raises(SlotTakenError):
            await repository.add(a_booking(tutor.id), "key-2")

    async def test_a_change_based_on_a_stale_read_is_not_applied(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        lesson = await repository.add(a_booking(tutor.id), "key-1")
        by_student = cancelled(lesson, Actor.STUDENT)
        await repository.apply([(lesson, by_student)])

        # The tutor read the lesson before the student cancelled, and acts on that.
        assert await repository.apply([(lesson, cancelled(lesson, Actor.TUTOR))]) == 0
        assert await repository.get(lesson.id) == by_student

    async def test_of_simultaneous_changes_to_one_lesson_exactly_one_is_applied(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        lesson = await repository.add(a_booking(tutor.id), "key-1")
        attempts = [
            repository.apply([(lesson, cancelled(lesson, actor))])
            for actor in (Actor.STUDENT, Actor.TUTOR) * 6
        ]

        assert sorted(await asyncio.gather(*attempts)) == [0] * 11 + [1]

    async def test_several_changes_are_counted_one_by_one(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        first = await repository.add(a_booking(tutor.id, FIRST_SLOT), "key-1")
        second = await repository.add(a_booking(tutor.id, FIRST_SLOT + HOUR), "key-2")
        await repository.apply([(second, cancelled(second))])

        applied = await repository.apply(
            [(first, cancelled(first)), (second, cancelled(second, Actor.TUTOR))]
        )

        assert applied == 1


class SeriesContract:
    async def test_a_series_is_stored_with_its_lessons(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        series, lessons = a_series(tutor)

        stored = await repository.add_series(series, lessons, skip_conflicts=False)

        assert stored == lessons
        assert await repository.get_series(series.id) == series
        assert await repository.series(tutor.id) == [series]
        assert await repository.lessons_of_series(series.id) == lessons
        assert await repository.get_series(uuid4()) is None

    async def test_series_lessons_block_their_times_like_any_other(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        series, lessons = a_series(tutor)
        await repository.add_series(series, lessons, skip_conflicts=False)

        with pytest.raises(SlotTakenError):
            await repository.add(a_booking(tutor.id, FIRST_SLOT + WEEK), "key-1")

    async def test_a_clash_stores_nothing_at_all(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        in_the_way = await repository.add(a_booking(tutor.id, FIRST_SLOT + WEEK), "key-1")
        series, lessons = a_series(tutor)

        with pytest.raises(SeriesConflictError) as refused:
            await repository.add_series(series, lessons, skip_conflicts=False)

        assert refused.value.slots == [lessons[1].slot]
        assert await repository.get_series(series.id) is None
        assert await repository.series(tutor.id) == []
        assert await repository.starting_between(
            tutor.id, TimeRange(FIRST_SLOT - HOUR, FIRST_SLOT + 4 * WEEK)
        ) == [in_the_way]

    async def test_clashing_lessons_can_be_left_out(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        # Overlaps the second lesson without starting at the same time.
        await repository.add(a_booking(tutor.id, FIRST_SLOT + WEEK + 0.5 * HOUR), "key-1")
        series, lessons = a_series(tutor)

        stored = await repository.add_series(series, lessons, skip_conflicts=True)

        assert stored == [lessons[0], lessons[2]]
        assert await repository.lessons_of_series(series.id) == stored

    async def test_a_series_with_every_lesson_in_the_way_is_not_stored(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id, FIRST_SLOT), "key-1")
        series, lessons = a_series(tutor, weeks=1)

        assert await repository.add_series(series, lessons, skip_conflicts=True) == []
        assert await repository.get_series(series.id) is None

    async def test_a_cancelled_lesson_is_not_in_the_way_of_a_series(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        old = await repository.add(a_booking(tutor.id, FIRST_SLOT + WEEK), "key-1")
        await repository.apply([(old, cancelled(old))])
        series, lessons = a_series(tutor)

        assert await repository.add_series(series, lessons, skip_conflicts=False) == lessons

    async def test_each_tutor_has_their_own_series(
        self, repository: LessonStore, tutor: Tutor, other_tutor: Tutor
    ) -> None:
        mine, my_lessons = a_series(tutor)
        theirs, their_lessons = a_series(other_tutor)
        await repository.add_series(mine, my_lessons, skip_conflicts=False)
        await repository.add_series(theirs, their_lessons, skip_conflicts=False)

        assert await repository.series(tutor.id) == [mine]
        assert await repository.series(other_tutor.id) == [theirs]

    async def test_a_series_and_single_bookings_racing_for_the_same_times_never_overlap(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        series, lessons = a_series(tutor, weeks=6)
        rivals = [
            repository.add(a_booking(tutor.id, FIRST_SLOT + n * WEEK), f"rival-{n}")
            for n in range(6)
        ]

        outcomes = await asyncio.gather(
            repository.add_series(series, lessons, skip_conflicts=True),
            *rivals,
            return_exceptions=True,
        )

        unexpected = [
            o for o in outcomes if isinstance(o, Exception) and not isinstance(o, SlotTakenError)
        ]
        assert unexpected == []
        everything = await repository.starting_between(
            tutor.id, TimeRange(FIRST_SLOT - HOUR, FIRST_SLOT + 7 * WEEK)
        )
        # Six times, each taken exactly once, by the series or by a rival.
        assert sorted(lesson.slot.start for lesson in everything) == [
            FIRST_SLOT + n * WEEK for n in range(6)
        ]
        assert all(lesson.status is LessonStatus.CONFIRMED for lesson in everything)


class TestInMemory(LessonChangesContract, SeriesContract):
    @pytest.fixture
    def repository(self) -> LessonStore:
        return InMemoryBookingRepository()

    @pytest.fixture
    def tutor(self) -> Tutor:
        return a_tutor("ewa")

    @pytest.fixture
    def other_tutor(self) -> Tutor:
        return a_tutor("jan")


@pytest.mark.integration
class TestPostgres(LessonChangesContract, SeriesContract):
    @pytest.fixture
    def repository(self, engine: AsyncEngine) -> LessonStore:
        return PostgresBookingRepository(engine)

    @pytest.fixture
    async def tutor(self, engine: AsyncEngine) -> Tutor:
        tutor = a_tutor("ewa")
        assert await PostgresTutorRepository(engine).add_if_absent(tutor)
        return tutor

    @pytest.fixture
    async def other_tutor(self, engine: AsyncEngine) -> Tutor:
        tutor = a_tutor("jan")
        assert await PostgresTutorRepository(engine).add_if_absent(tutor)
        return tutor
