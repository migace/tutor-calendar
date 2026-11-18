"""What every student directory must do, checked against each implementation.

The directory gives each student an id that stands for their address
(ADR 0010). The rule that matters is that nobody can have a lesson without
one, and that an address never ends up with two.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.contract.test_lesson_changes_and_series import a_series
from tests.factories import ANNA, FIRST_SLOT, NOW, a_booking, a_tutor
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.errors import SlotTakenError
from tutor_calendar.application.ports import LessonStore
from tutor_calendar.domain.scheduling import Student, Tutor

pytestmark = pytest.mark.anyio

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
BARTEK = Student("Bartek Lis", "bartek@example.com")


class StudentDirectoryContract:
    async def test_a_booking_enrols_its_student(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id), "k1")

        [student] = await repository.students(tutor.id)

        assert (student.tutor_id, student.account, student.name) == (
            tutor.id,
            "anna@example.com",
            "Anna Nowak",
        )
        assert await repository.get_student(student.id) == student
        assert await repository.find_student(tutor.id, "anna@example.com") == student

    async def test_one_address_is_one_student_however_it_is_written(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        first = a_booking(tutor.id, FIRST_SLOT, student=Student("Ania", "Anna@Example.com"))
        await repository.add(first, "k1")
        [before] = await repository.students(tutor.id)

        later = a_booking(tutor.id, FIRST_SLOT + DAY, student=ANNA)
        await repository.add(replace(later, created_at=NOW + HOUR), "k2")

        [after] = await repository.students(tutor.id)
        # Still the same student, now under the name on the latest booking.
        assert after.id == before.id
        assert (before.name, after.name) == ("Ania", "Anna Nowak")

    async def test_a_series_enrols_its_student(self, repository: LessonStore, tutor: Tutor) -> None:
        series, lessons = a_series(tutor)

        await repository.add_series(series, lessons, skip_conflicts=False)

        [student] = await repository.students(tutor.id)
        assert (student.account, student.name) == ("anna@example.com", "Anna Nowak")

    async def test_a_booking_that_is_refused_enrols_nobody(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id), "k1")

        with pytest.raises(SlotTakenError):
            await repository.add(a_booking(tutor.id, student=BARTEK), "k2")

        assert [student.account for student in await repository.students(tutor.id)] == [
            "anna@example.com"
        ]

    async def test_an_address_can_be_enrolled_before_any_lesson(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        student = await repository.enrol(tutor.id, "anna@example.com", NOW)

        # Nothing is known about them but the address.
        assert (student.tutor_id, student.account, student.name) == (
            tutor.id,
            "anna@example.com",
            None,
        )
        assert await repository.students(tutor.id) == [student]

    async def test_enrolling_again_returns_the_same_student(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        first = await repository.enrol(tutor.id, "anna@example.com", NOW)

        again = await repository.enrol(tutor.id, "anna@example.com", NOW + DAY)
        await repository.add(a_booking(tutor.id), "k1")

        assert again == first
        # The booking finds them enrolled and keeps the id.
        [booked] = await repository.students(tutor.id)
        assert (booked.id, booked.name) == (first.id, "Anna Nowak")

    async def test_enrolling_one_address_many_times_at_once_leaves_one_student(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        attempts = [repository.enrol(tutor.id, "anna@example.com", NOW) for _ in range(10)]

        outcomes = await asyncio.gather(*attempts)

        assert len({student.id for student in outcomes}) == 1
        assert len(await repository.students(tutor.id)) == 1

    async def test_each_tutor_has_students_of_their_own(
        self, repository: LessonStore, tutor: Tutor, other_tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id), "k1")
        theirs = await repository.enrol(other_tutor.id, "anna@example.com", NOW)

        [mine] = await repository.students(tutor.id)

        # The same address with another tutor is another student.
        assert mine.id != theirs.id
        assert await repository.students(other_tutor.id) == [theirs]
        assert await repository.find_student(other_tutor.id, "bartek@example.com") is None

    async def test_an_id_nobody_has_finds_nobody(
        self, repository: LessonStore, tutor: Tutor
    ) -> None:
        await repository.add(a_booking(tutor.id), "k1")

        assert await repository.get_student(uuid4()) is None
        assert await repository.find_student(tutor.id, "nobody@example.com") is None


class TestInMemoryStudentDirectory(StudentDirectoryContract):
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
class TestPostgresStudentDirectory(StudentDirectoryContract):
    @pytest.fixture
    def repository(self, engine: AsyncEngine) -> LessonStore:
        return PostgresBookingRepository(engine)

    @pytest.fixture
    async def tutor(self, engine: AsyncEngine) -> Tutor:
        return await _stored(engine, a_tutor("ewa"))

    @pytest.fixture
    async def other_tutor(self, engine: AsyncEngine) -> Tutor:
        return await _stored(engine, a_tutor("jan"))


async def _stored(engine: AsyncEngine, tutor: Tutor) -> Tutor:
    # Students reference tutors, so the tutor has to exist first.
    assert await PostgresTutorRepository(engine).add_if_absent(tutor)
    return tutor
