from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from tests.factories import ANNA, FIRST_SLOT
from tutor_calendar.domain.scheduling import (
    Booking,
    Schedule,
    Student,
    TimeRange,
    Weekday,
    WeeklyRule,
    slot_starting_at,
)

WARSAW = ZoneInfo("Europe/Warsaw")


def test_student_details_are_tidied() -> None:
    student = Student("  Anna   Nowak ", " Anna.Nowak@Example.COM ")

    assert student.name == "Anna Nowak"
    # Only the part after the @ is case-insensitive.
    assert student.email == "Anna.Nowak@example.com"


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_student_name_must_be_present_and_reasonable(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        Student(name, "anna@example.com")


@pytest.mark.parametrize(
    "email", ["", "anna", "@example.com", "anna@", "an na@example.com", "a" * 250 + "@x.pl"]
)
def test_student_email_must_look_like_an_address(email: str) -> None:
    with pytest.raises(ValueError, match="email"):
        Student("Anna", email)


def test_booking_needs_an_aware_creation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Booking(
            id=uuid4(),
            tutor_id=uuid4(),
            slot=TimeRange(FIRST_SLOT, FIRST_SLOT + timedelta(hours=1)),
            student=ANNA,
            created_at=datetime(2026, 11, 16, 8, 0),  # noqa: DTZ001 - the point of the test
        )


class TestSlotStartingAt:
    schedule = Schedule(
        timezone=WARSAW,
        lesson_duration=timedelta(minutes=45),
        rules=(WeeklyRule(Weekday.SUNDAY, time(1, 0), time(5, 0)),),
    )

    def test_finds_a_slot_by_its_start_in_any_offset(self) -> None:
        # Sunday 22 November 2026, 01:45 in Warsaw, written as New York time.
        start = datetime(2026, 11, 21, 19, 45, tzinfo=ZoneInfo("America/New_York"))

        slot = slot_starting_at(self.schedule, start)

        assert slot == TimeRange(
            datetime(2026, 11, 22, 0, 45, tzinfo=UTC), datetime(2026, 11, 22, 1, 30, tzinfo=UTC)
        )

    def test_a_time_between_grid_positions_is_not_a_slot(self) -> None:
        assert slot_starting_at(self.schedule, datetime(2026, 11, 22, 1, 0, tzinfo=UTC)) is None

    def test_the_last_position_that_would_overrun_the_rule_is_not_a_slot(self) -> None:
        # 04:45 Warsaw would end at 05:30, after the tutor has finished.
        assert slot_starting_at(self.schedule, datetime(2026, 11, 22, 3, 45, tzinfo=UTC)) is None

    def test_agrees_with_the_grid_on_the_night_the_clocks_go_forward(self) -> None:
        # On 29 March 2026 Warsaw skips from 02:00 to 03:00. The 01:45 position
        # would end at 03:30 on the wall clock and collide with the next one, so
        # the grid keeps 01:45 and drops the positions inside and just after the gap.
        at_0145 = datetime(2026, 3, 29, 0, 45, tzinfo=UTC)
        at_0315 = datetime(2026, 3, 29, 1, 15, tzinfo=UTC)
        at_0400 = datetime(2026, 3, 29, 2, 0, tzinfo=UTC)

        assert slot_starting_at(self.schedule, at_0145) is not None
        assert slot_starting_at(self.schedule, at_0315) is None
        assert slot_starting_at(self.schedule, at_0400) is not None
