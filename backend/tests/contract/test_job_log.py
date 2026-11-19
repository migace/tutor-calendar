"""What any record of the background jobs must do, checked against each implementation.

See ADR 0011.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import NOW
from tutor_calendar.adapters.in_memory_jobs import InMemoryJobLog
from tutor_calendar.adapters.postgres.jobs import PostgresJobLog
from tutor_calendar.application.ports import JobLog

pytestmark = pytest.mark.anyio

MINUTE = timedelta(minutes=1)


class JobLogContract:
    async def test_a_job_that_has_never_finished_is_not_in_the_record(self, jobs: JobLog) -> None:
        assert await jobs.last_successes() == {}

        await jobs.record_success("deliver", NOW)

        assert await jobs.last_successes() == {"deliver": NOW}

    async def test_each_job_has_its_own_time(self, jobs: JobLog) -> None:
        await jobs.record_success("settle", NOW)
        await jobs.record_success("deliver", NOW + MINUTE)

        assert await jobs.last_successes() == {"settle": NOW, "deliver": NOW + MINUTE}

    async def test_a_later_finish_replaces_an_earlier_one(self, jobs: JobLog) -> None:
        await jobs.record_success("settle", NOW)
        await jobs.record_success("settle", NOW + MINUTE)

        assert await jobs.last_successes() == {"settle": NOW + MINUTE}

    async def test_a_worker_that_reports_late_does_not_put_the_time_back(
        self, jobs: JobLog
    ) -> None:
        await jobs.record_success("settle", NOW + MINUTE)
        await jobs.record_success("settle", NOW)

        assert await jobs.last_successes() == {"settle": NOW + MINUTE}

    async def test_many_workers_reporting_at_once_leave_the_latest_time(self, jobs: JobLog) -> None:
        moments = [NOW + n * MINUTE for n in range(12)]

        # In an order that is neither rising nor falling.
        await asyncio.gather(
            *(jobs.record_success("deliver", moment) for moment in moments[6:] + moments[:6])
        )

        assert await jobs.last_successes() == {"deliver": moments[-1]}


class TestInMemoryJobLog(JobLogContract):
    @pytest.fixture
    def jobs(self) -> JobLog:
        return InMemoryJobLog()


@pytest.mark.integration
class TestPostgresJobLog(JobLogContract):
    @pytest.fixture
    def jobs(self, engine: AsyncEngine) -> JobLog:
        return PostgresJobLog(engine)
