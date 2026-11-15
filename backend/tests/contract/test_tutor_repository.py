"""What every tutor repository must do, checked against each implementation."""

from __future__ import annotations

import asyncio
from datetime import time
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import a_tutor
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.ports import TutorRepository
from tutor_calendar.domain.scheduling import Tutor, Weekday, WeeklyRule

pytestmark = pytest.mark.anyio

EWA = a_tutor("ewa")
JAN = a_tutor("jan")


class TutorRepositoryContract:
    """Each implementation starts with EWA and JAN stored."""

    async def test_finds_a_tutor_by_slug_id_and_email(self, repository: TutorRepository) -> None:
        assert await repository.get_by_slug("ewa") == EWA
        assert await repository.get_by_id(JAN.id) == JAN
        assert await repository.get_by_email("jan@example.com") == JAN

    async def test_unknown_tutors_are_not_found(self, repository: TutorRepository) -> None:
        assert await repository.get_by_slug("nobody") is None
        assert await repository.get_by_id(uuid4()) is None
        assert await repository.get_by_email("nobody@example.com") is None

    @pytest.mark.parametrize("typed", ["EWA@EXAMPLE.COM", "Ewa@Example.com", " ewa@example.com "])
    async def test_email_lookup_ignores_case_and_stray_spaces(
        self, repository: TutorRepository, typed: str
    ) -> None:
        assert await repository.get_by_email(typed) == EWA

    async def test_email_lookup_is_exact_not_a_pattern(self, repository: TutorRepository) -> None:
        assert await repository.get_by_email("%@example.com") is None
        assert await repository.get_by_email("ewa_example.com") is None

    async def test_replacing_weekly_hours_swaps_the_whole_set(
        self, repository: TutorRepository
    ) -> None:
        new_hours = (
            WeeklyRule(Weekday.TUESDAY, time(9, 0), time(11, 0)),
            WeeklyRule(Weekday.TUESDAY, time(14, 0), time(16, 30)),
        )

        await repository.replace_weekly_hours(EWA.id, new_hours)

        assert await repository.get_by_slug("ewa") == EWA.with_weekly_hours(new_hours)
        assert await repository.get_by_slug("jan") == JAN

    async def test_weekly_hours_can_be_cleared(self, repository: TutorRepository) -> None:
        await repository.replace_weekly_hours(EWA.id, ())

        changed = await repository.get_by_slug("ewa")
        assert changed is not None
        assert changed.schedule.rules == ()
        # Days off are not weekly hours and are left alone.
        assert changed.schedule.days_off == EWA.schedule.days_off

    async def test_simultaneous_replacements_leave_one_complete_set(
        self, repository: TutorRepository
    ) -> None:
        candidates = [
            tuple(
                WeeklyRule(Weekday(day), time(8 + n, 0), time(9 + n, 0)) for day in range(n % 5 + 1)
            )
            for n in range(8)
        ]

        await asyncio.gather(*(repository.replace_weekly_hours(EWA.id, c) for c in candidates))

        stored = await repository.get_by_slug("ewa")
        assert stored is not None
        # Never a mixture of two sets, which interleaved deletes and inserts would give.
        assert stored.schedule.rules in candidates


class TestInMemoryTutorRepository(TutorRepositoryContract):
    @pytest.fixture
    def repository(self) -> TutorRepository:
        return InMemoryTutorRepository([EWA, JAN])


@pytest.mark.integration
class TestPostgresTutorRepository(TutorRepositoryContract):
    @pytest.fixture
    async def repository(self, engine: AsyncEngine) -> TutorRepository:
        repository = PostgresTutorRepository(engine)
        for tutor in (EWA, JAN):
            assert await repository.add_if_absent(tutor)
        return repository

    async def test_two_tutors_cannot_share_an_address_in_any_case(
        self, repository: PostgresTutorRepository
    ) -> None:
        impostor = Tutor(
            id=uuid4(),
            slug="ewa-two",
            display_name="Another Ewa",
            email="EWA@example.com",
            schedule=EWA.schedule,
        )

        with pytest.raises(IntegrityError):
            await repository.add_if_absent(impostor)
