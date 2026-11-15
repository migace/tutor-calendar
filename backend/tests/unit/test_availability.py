from datetime import UTC, date, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tutor_calendar.domain.scheduling import Schedule, Weekday, WeeklyRule

WARSAW = ZoneInfo("Europe/Warsaw")
HOUR = timedelta(hours=1)


def test_rule_must_start_before_it_ends() -> None:
    with pytest.raises(ValueError, match="start before"):
        WeeklyRule(Weekday.MONDAY, time(18, 0), time(17, 0))


def test_rule_times_must_be_naive_wall_clock_times() -> None:
    with pytest.raises(ValueError, match="naive"):
        WeeklyRule(Weekday.MONDAY, time(17, 0, tzinfo=UTC), time(18, 0))


def test_schedule_rejects_overlapping_rules_on_the_same_day() -> None:
    with pytest.raises(ValueError, match="overlap on Monday"):
        Schedule(
            WARSAW,
            HOUR,
            (
                WeeklyRule(Weekday.MONDAY, time(15, 0), time(18, 0)),
                WeeklyRule(Weekday.MONDAY, time(17, 0), time(19, 0)),
            ),
        )


def test_schedule_allows_back_to_back_rules_and_same_hours_on_other_days() -> None:
    schedule = Schedule(
        WARSAW,
        HOUR,
        (
            WeeklyRule(Weekday.TUESDAY, time(15, 0), time(18, 0)),
            WeeklyRule(Weekday.MONDAY, time(17, 0), time(19, 0)),
            WeeklyRule(Weekday.MONDAY, time(15, 0), time(17, 0)),
        ),
    )
    assert [(rule.weekday, rule.start) for rule in schedule.rules] == [
        (Weekday.MONDAY, time(15, 0)),
        (Weekday.MONDAY, time(17, 0)),
        (Weekday.TUESDAY, time(15, 0)),
    ]


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(minutes=-30), timedelta(seconds=90)])
def test_schedule_rejects_unusable_lesson_durations(duration: timedelta) -> None:
    with pytest.raises(ValueError, match="lesson duration"):
        Schedule(WARSAW, duration, ())


def test_rules_on_respects_weekday_and_days_off() -> None:
    monday = date(2026, 11, 16)
    schedule = Schedule(
        WARSAW,
        HOUR,
        (WeeklyRule(Weekday.MONDAY, time(15, 0), time(17, 0)),),
        days_off=frozenset({monday + timedelta(days=7)}),
    )
    assert len(list(schedule.rules_on(monday))) == 1
    assert list(schedule.rules_on(monday + timedelta(days=1))) == []
    assert list(schedule.rules_on(monday + timedelta(days=7))) == []
