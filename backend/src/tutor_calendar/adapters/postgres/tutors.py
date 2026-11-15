from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tutor_calendar.adapters.postgres.tables import availability_rules, days_off, tutors
from tutor_calendar.domain.scheduling import Schedule, Tutor, Weekday, WeeklyRule

_MINUTE = timedelta(minutes=1)


class PostgresTutorRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_by_slug(self, slug: str) -> Tutor | None:
        return await self._get(tutors.c.slug == slug)

    async def get_by_id(self, tutor_id: UUID) -> Tutor | None:
        return await self._get(tutors.c.id == tutor_id)

    async def get_by_email(self, email: str) -> Tutor | None:
        return await self._get(func.lower(tutors.c.email) == email.strip().lower())

    async def _get(self, condition: ColumnElement[bool]) -> Tutor | None:
        async with self._engine.connect() as connection:
            tutor = (await connection.execute(select(tutors).where(condition))).one_or_none()
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
                email=tutor.email,
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

    async def replace_weekly_hours(self, tutor_id: UUID, rules: tuple[WeeklyRule, ...]) -> None:
        async with self._engine.begin() as connection:
            # The same row lock that booking writers take (ADR 0003), so two
            # saves at once cannot interleave their deletes and inserts and
            # leave a mixture of both sets of hours.
            await connection.execute(
                select(tutors.c.id).where(tutors.c.id == tutor_id).with_for_update(key_share=True)
            )
            await connection.execute(
                delete(availability_rules).where(availability_rules.c.tutor_id == tutor_id)
            )
            await _insert_rules(connection, tutor_id, rules)

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
                    email=tutor.email,
                    timezone=schedule.timezone.key,
                    lesson_minutes=schedule.lesson_duration // _MINUTE,
                    min_notice_minutes=tutor.min_notice // _MINUTE,
                )
                .on_conflict_do_nothing(index_elements=[tutors.c.slug])
                .returning(tutors.c.id)
            )
            if created.one_or_none() is None:
                return False
            await _insert_rules(connection, tutor.id, schedule.rules)
            if schedule.days_off:
                await connection.execute(
                    insert(days_off),
                    [{"tutor_id": tutor.id, "day": day} for day in sorted(schedule.days_off)],
                )
            return True


async def _insert_rules(
    connection: AsyncConnection, tutor_id: UUID, rules: Sequence[WeeklyRule]
) -> None:
    if not rules:
        return
    rows: list[dict[str, Any]] = [
        {
            "tutor_id": tutor_id,
            "weekday": int(rule.weekday),
            "start_time": rule.start,
            "end_time": rule.end,
        }
        for rule in rules
    ]
    await connection.execute(insert(availability_rules), rows)
