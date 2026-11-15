from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.adapters.postgres.tables import availability_rules, days_off, tutors
from tutor_calendar.domain.scheduling import Schedule, Tutor, Weekday, WeeklyRule

_MINUTE = timedelta(minutes=1)


class PostgresTutorRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_by_slug(self, slug: str) -> Tutor | None:
        async with self._engine.connect() as connection:
            tutor = (
                await connection.execute(select(tutors).where(tutors.c.slug == slug))
            ).one_or_none()
            if tutor is None:
                return None
            rules = await connection.execute(
                select(availability_rules).where(availability_rules.c.tutor_id == tutor.id)
            )
            off = await connection.execute(
                select(days_off.c.day).where(days_off.c.tutor_id == tutor.id)
            )
            return Tutor(
                id=tutor.id,
                slug=tutor.slug,
                display_name=tutor.display_name,
                schedule=Schedule(
                    timezone=ZoneInfo(tutor.timezone),
                    lesson_duration=tutor.lesson_minutes * _MINUTE,
                    rules=tuple(
                        WeeklyRule(Weekday(rule.weekday), rule.start_time, rule.end_time)
                        for rule in rules
                    ),
                    days_off=frozenset(row.day for row in off),
                ),
                min_notice=tutor.min_notice_minutes * _MINUTE,
            )

    async def add_if_absent(self, tutor: Tutor) -> bool:
        """Store a tutor with their schedule. Returns False if the slug is taken."""
        schedule = tutor.schedule
        async with self._engine.begin() as connection:
            created = await connection.execute(
                pg_insert(tutors)
                .values(
                    id=tutor.id,
                    slug=tutor.slug,
                    display_name=tutor.display_name,
                    timezone=schedule.timezone.key,
                    lesson_minutes=schedule.lesson_duration // _MINUTE,
                    min_notice_minutes=tutor.min_notice // _MINUTE,
                )
                .on_conflict_do_nothing(index_elements=[tutors.c.slug])
                .returning(tutors.c.id)
            )
            if created.one_or_none() is None:
                return False
            if schedule.rules:
                await connection.execute(
                    insert(availability_rules),
                    [
                        {
                            "tutor_id": tutor.id,
                            "weekday": int(rule.weekday),
                            "start_time": rule.start,
                            "end_time": rule.end,
                        }
                        for rule in schedule.rules
                    ],
                )
            if schedule.days_off:
                await connection.execute(
                    insert(days_off),
                    [{"tutor_id": tutor.id, "day": day} for day in sorted(schedule.days_off)],
                )
            return True
