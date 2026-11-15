"""Small builders for the objects most tests need."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from tutor_calendar.domain.scheduling import (
    Booking,
    Schedule,
    Student,
    TimeRange,
    Tutor,
    Weekday,
    WeeklyRule,
)

# A Monday morning. The demo tutor teaches Mon-Thu 15:00-19:00 and Sat 09:00-13:00
# Warsaw time (UTC+1 in November) and needs 12 hours' notice.
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
# Tuesday 15:00 in Warsaw: the first slot that can be booked at NOW.
FIRST_SLOT = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)

ANNA = Student("Anna Nowak", "anna@example.com")


def a_tutor(slug: str = "ewa") -> Tutor:
    return Tutor(
        id=uuid4(),
        slug=slug,
        display_name="Ewa Kowalska",
        email=f"{slug}@example.com",
        schedule=Schedule(
            timezone=ZoneInfo("Europe/Warsaw"),
            lesson_duration=timedelta(minutes=45),
            rules=(
                WeeklyRule(Weekday.MONDAY, time(8, 0), time(12, 0)),
                WeeklyRule(Weekday.FRIDAY, time(16, 30), time(20, 0)),
            ),
            days_off=frozenset({NOW.date() + timedelta(days=11)}),
        ),
        min_notice=timedelta(hours=24),
    )


def a_booking(
    tutor_id: UUID,
    start: datetime = FIRST_SLOT,
    minutes: int = 60,
    student: Student = ANNA,
) -> Booking:
    return Booking(
        id=uuid4(),
        tutor_id=tutor_id,
        slot=TimeRange(start, start + timedelta(minutes=minutes)),
        student=student,
        created_at=NOW,
    )
