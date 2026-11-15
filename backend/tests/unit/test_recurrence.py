from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.factories import ANNA
from tutor_calendar.domain.scheduling import Schedule, WeeklySeries

WARSAW = ZoneInfo("Europe/Warsaw")


def schedule(
    tz: ZoneInfo = WARSAW, minutes: int = 60, days_off: set[date] | None = None
) -> Schedule:
    return Schedule(
        timezone=tz,
        lesson_duration=timedelta(minutes=minutes),
        rules=(),
        days_off=frozenset(days_off or ()),
    )


def series(first_day: date, start: time, weeks: int) -> WeeklySeries:
    return WeeklySeries(first_day=first_day, start=start, weeks=weeks, student=ANNA)


def test_a_series_is_one_lesson_a_week() -> None:
    lessons, skipped = series(date(2026, 11, 17), time(17, 0), 3).lay_out(schedule())

    assert skipped == []
    assert [lesson.day for lesson in lessons] == [
        date(2026, 11, 17),
        date(2026, 11, 24),
        date(2026, 12, 1),
    ]
    assert lessons[0].slot.start == datetime(2026, 11, 17, 16, 0, tzinfo=UTC)
    assert all(lesson.slot.duration == timedelta(hours=1) for lesson in lessons)


def test_lessons_stay_at_the_same_hour_on_the_clock_when_the_clocks_change() -> None:
    # Warsaw moves to summer time on 29 March 2026.
    lessons, _ = series(date(2026, 3, 24), time(17, 0), 2).lay_out(schedule())

    assert [lesson.slot.start for lesson in lessons] == [
        datetime(2026, 3, 24, 16, 0, tzinfo=UTC),  # 17:00 at UTC+1
        datetime(2026, 3, 31, 15, 0, tzinfo=UTC),  # 17:00 at UTC+2
    ]


def test_a_day_on_which_the_start_does_not_exist_gets_no_lesson() -> None:
    # Sundays at 02:30: on 29 March the clocks jump from 02:00 to 03:00.
    lessons, skipped = series(date(2026, 3, 22), time(2, 30), 3).lay_out(schedule())

    assert [lesson.day for lesson in lessons] == [date(2026, 3, 22), date(2026, 4, 5)]
    assert skipped == [date(2026, 3, 29)]


def test_a_start_that_happens_twice_means_the_first_time() -> None:
    # 25 October 2026: 02:30 happens at UTC+2 and again at UTC+1.
    [lesson], _ = series(date(2026, 10, 25), time(2, 30), 1).lay_out(schedule())

    assert lesson.slot.start == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_the_tutors_days_off_get_no_lesson() -> None:
    off = {date(2026, 12, 24)}

    lessons, skipped = series(date(2026, 12, 17), time(10, 0), 3).lay_out(schedule(days_off=off))

    assert [lesson.day for lesson in lessons] == [date(2026, 12, 17), date(2026, 12, 31)]
    assert skipped == [date(2026, 12, 24)]


def test_lessons_last_as_long_as_the_tutors_lessons_do() -> None:
    [lesson], _ = series(date(2026, 11, 17), time(17, 0), 1).lay_out(schedule(minutes=45))

    assert lesson.slot.duration == timedelta(minutes=45)


@pytest.mark.parametrize("weeks", [0, -1, 53])
def test_a_series_has_a_sensible_number_of_lessons(weeks: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 52"):
        series(date(2026, 11, 17), time(17, 0), weeks)


@pytest.mark.parametrize(
    "start", [time(17, 0, 30), time(17, 0, tzinfo=UTC)], ids=["with seconds", "with an offset"]
)
def test_a_series_starts_at_a_wall_clock_minute(start: time) -> None:
    with pytest.raises(ValueError, match=r"minute|naive"):
        series(date(2026, 11, 17), start, 4)


zones = st.timezones().filter(lambda tz: isinstance(tz, ZoneInfo))
minutes_of_day = st.integers(0, 24 * 60 - 1).map(lambda m: time(m // 60, m % 60))


@given(
    zones,
    st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 1, 1)),
    minutes_of_day,
    st.integers(1, 52),
)
@settings(max_examples=300, deadline=None)
def test_in_every_zone_each_lesson_starts_at_the_planned_time_on_the_tutors_clock(
    tz: ZoneInfo, first_day: date, start: time, weeks: int
) -> None:
    plan = series(first_day, start, weeks)

    lessons, skipped = plan.lay_out(schedule(tz))

    # Every planned day is accounted for, once.
    assert sorted([lesson.day for lesson in lessons] + skipped) == plan.days()
    for lesson in lessons:
        local = lesson.slot.start.astimezone(tz)
        assert (local.date(), local.time()) == (lesson.day, start)
    # Lessons a week apart never overlap, however the clocks moved in between.
    for earlier, later in pairwise(lessons):
        assert earlier.slot.end <= later.slot.start
