from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.factories import a_booking
from tutor_calendar.domain.scheduling import lay_out_week, local_day, start_of_day, week_range

WARSAW = ZoneInfo("Europe/Warsaw")
HAVANA = ZoneInfo("America/Havana")
DAY = timedelta(days=1)

dates = st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31))
zones = st.timezones().filter(lambda tz: isinstance(tz, ZoneInfo))


def test_a_day_normally_starts_at_local_midnight() -> None:
    assert start_of_day(date(2026, 11, 16), WARSAW) == datetime(2026, 11, 15, 23, 0, tzinfo=UTC)


def test_a_day_whose_midnight_is_skipped_starts_when_the_clocks_jump() -> None:
    # Cuba moves its clocks forward at midnight: on 8 March 2026 the time goes
    # from 23:59 straight to 01:00.
    start = start_of_day(date(2026, 3, 8), HAVANA)

    assert start.astimezone(HAVANA).strftime("%Y-%m-%d %H:%M") == "2026-03-08 01:00"
    assert local_day(start - timedelta(seconds=1), HAVANA) == date(2026, 3, 7)


@given(dates, zones)
@settings(max_examples=500, deadline=None)
def test_the_start_of_a_day_is_its_first_instant_in_every_zone(day: date, tz: ZoneInfo) -> None:
    start = start_of_day(day, tz)

    assert local_day(start, tz) == day
    assert local_day(start - timedelta(microseconds=1), tz) == day - DAY


@given(dates, zones)
@settings(max_examples=300, deadline=None)
def test_weeks_run_monday_to_monday_and_leave_no_gaps(day: date, tz: ZoneInfo) -> None:
    week = week_range(day, tz)

    assert local_day(week.start, tz).weekday() == 0
    assert week.start <= start_of_day(day, tz) < week.end
    assert week_range(day + 7 * DAY, tz).start == week.end


def test_a_week_with_a_clock_change_is_not_168_hours_long() -> None:
    # The last week of March 2026 loses an hour in Warsaw.
    assert week_range(date(2026, 3, 25), WARSAW).duration == timedelta(hours=167)


def test_lessons_land_on_the_local_day_they_start_on() -> None:
    tutor_id = uuid4()
    # 23:30 UTC on Sunday 15 November is already 00:30 on Monday in Warsaw.
    just_after_midnight = a_booking(tutor_id, datetime(2026, 11, 15, 23, 30, tzinfo=UTC))
    wednesday_late = a_booking(tutor_id, datetime(2026, 11, 18, 17, 0, tzinfo=UTC))
    wednesday_early = a_booking(tutor_id, datetime(2026, 11, 18, 8, 0, tzinfo=UTC))
    previous_week = a_booking(tutor_id, datetime(2026, 11, 15, 12, 0, tzinfo=UTC))

    week = lay_out_week(
        date(2026, 11, 19),
        WARSAW,
        [wednesday_late, previous_week, just_after_midnight, wednesday_early],
    )

    assert [day.day for day in week.days] == [date(2026, 11, 16) + n * DAY for n in range(7)]
    assert week.days[0].lessons == (just_after_midnight,)
    assert week.days[2].lessons == (wednesday_early, wednesday_late)
    assert sum(len(day.lessons) for day in week.days) == 3
    assert (week.start, week.previous, week.next) == (
        date(2026, 11, 16),
        date(2026, 11, 9),
        date(2026, 11, 23),
    )
