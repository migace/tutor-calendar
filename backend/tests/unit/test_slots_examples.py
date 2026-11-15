"""Hand-picked cases, mostly around the two nights a year when the clocks change.

In 2026 Europe/Warsaw springs forward on Sunday 29 March (02:00 -> 03:00) and
falls back on Sunday 25 October (03:00 -> 02:00).
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tutor_calendar.domain.scheduling import (
    Schedule,
    TimeRange,
    Weekday,
    WeeklyRule,
    generate_slots,
)

WARSAW = ZoneInfo("Europe/Warsaw")


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def schedule(
    *rules: WeeklyRule, minutes: int = 60, days_off: frozenset[date] = frozenset()
) -> Schedule:
    return Schedule(WARSAW, timedelta(minutes=minutes), rules, days_off)


def starts(slots: list[TimeRange]) -> list[datetime]:
    return [slot.start for slot in slots]


def test_plain_week_produces_back_to_back_slots() -> None:
    tuesday_evening = WeeklyRule(Weekday.TUESDAY, time(17, 0), time(19, 0))
    window = TimeRange(utc(2026, 11, 16), utc(2026, 11, 23))

    slots = generate_slots(schedule(tuesday_evening), window)

    # 17:00 and 18:00 in Warsaw (UTC+1 in November).
    assert slots == [
        TimeRange(utc(2026, 11, 17, 16), utc(2026, 11, 17, 17)),
        TimeRange(utc(2026, 11, 17, 17), utc(2026, 11, 17, 18)),
    ]


def test_leftover_time_shorter_than_a_lesson_is_not_offered() -> None:
    rule = WeeklyRule(Weekday.TUESDAY, time(17, 0), time(18, 30))
    window = TimeRange(utc(2026, 11, 16), utc(2026, 11, 23))

    assert starts(generate_slots(schedule(rule), window)) == [utc(2026, 11, 17, 16)]


def test_lesson_stays_at_the_same_wall_clock_time_across_a_dst_change() -> None:
    rule = WeeklyRule(Weekday.TUESDAY, time(17, 0), time(18, 0))
    window = TimeRange(utc(2026, 3, 23), utc(2026, 4, 6))

    slots = generate_slots(schedule(rule), window)

    # Same 17:00 on the tutor's clock, an hour earlier in UTC once summer time starts.
    assert starts(slots) == [utc(2026, 3, 24, 16), utc(2026, 3, 31, 15)]
    assert {slot.start.astimezone(WARSAW).time() for slot in slots} == {time(17, 0)}


def test_slot_that_would_start_in_the_spring_gap_is_skipped() -> None:
    rule = WeeklyRule(Weekday.SUNDAY, time(1, 0), time(4, 0))
    window = TimeRange(utc(2026, 3, 28), utc(2026, 3, 30))

    slots = generate_slots(schedule(rule), window)

    # 01:00 CET and 03:00 CEST exist; 02:00 never happens that night.
    assert starts(slots) == [utc(2026, 3, 29, 0), utc(2026, 3, 29, 1)]
    assert [slot.start.astimezone(WARSAW).time() for slot in slots] == [time(1, 0), time(3, 0)]


def test_slot_straddling_the_spring_gap_does_not_overlap_the_next_one() -> None:
    # 01:00 + 2h of real time ends at 04:00 on the wall clock, so the grid
    # position at 03:00 is already taken.
    rule = WeeklyRule(Weekday.SUNDAY, time(1, 0), time(5, 0))
    window = TimeRange(utc(2026, 3, 28), utc(2026, 3, 30))

    slots = generate_slots(schedule(rule, minutes=120), window)

    assert slots == [TimeRange(utc(2026, 3, 29, 0), utc(2026, 3, 29, 2))]


def test_missing_start_is_dropped_rather_than_moved_to_after_the_gap() -> None:
    # 45-minute grid: 01:00, 01:45, 02:30 (does not exist), 03:15, 04:00.
    rule = WeeklyRule(Weekday.SUNDAY, time(1, 0), time(5, 0))
    window = TimeRange(utc(2026, 3, 28), utc(2026, 3, 30))

    slots = generate_slots(schedule(rule, minutes=45), window)

    # 01:45 CET runs until 03:30 CEST, which also rules out 03:15. Shifting the
    # missing 02:30 forward to 03:30 would put a lesson off the tutor's grid.
    assert [slot.start.astimezone(WARSAW).time() for slot in slots] == [
        time(1, 0),
        time(1, 45),
        time(4, 0),
    ]


def test_slot_straddling_the_spring_gap_must_still_end_inside_the_rule() -> None:
    rule = WeeklyRule(Weekday.SUNDAY, time(1, 0), time(3, 0))
    window = TimeRange(utc(2026, 3, 28), utc(2026, 3, 30))

    # 01:00 + 2h ends at 04:00 local, an hour after the tutor stops working.
    assert generate_slots(schedule(rule, minutes=120), window) == []


def test_ambiguous_hour_in_autumn_is_offered_once() -> None:
    rule = WeeklyRule(Weekday.SUNDAY, time(1, 0), time(4, 0))
    window = TimeRange(utc(2026, 10, 24), utc(2026, 10, 26))

    slots = generate_slots(schedule(rule), window)

    # 01:00 CEST, the first 02:00 (CEST) and 03:00 CET. The repeated hour stays free.
    assert starts(slots) == [
        utc(2026, 10, 24, 23),
        utc(2026, 10, 25, 0),
        utc(2026, 10, 25, 2),
    ]
    assert all(slot.duration == timedelta(hours=1) for slot in slots)


def test_days_off_remove_a_whole_local_day() -> None:
    rule = WeeklyRule(Weekday.TUESDAY, time(17, 0), time(18, 0))
    window = TimeRange(utc(2026, 11, 16), utc(2026, 11, 30))

    slots = generate_slots(schedule(rule, days_off=frozenset({date(2026, 11, 17)})), window)

    assert starts(slots) == [utc(2026, 11, 24, 16)]


def test_busy_ranges_remove_only_the_slots_they_touch() -> None:
    rule = WeeklyRule(Weekday.TUESDAY, time(15, 0), time(19, 0))
    window = TimeRange(utc(2026, 11, 16), utc(2026, 11, 23))
    lesson_already_booked = TimeRange(utc(2026, 11, 17, 15, 30), utc(2026, 11, 17, 16, 30))

    slots = generate_slots(schedule(rule), window, busy=[lesson_already_booked])

    assert starts(slots) == [utc(2026, 11, 17, 14), utc(2026, 11, 17, 17)]


def test_slots_partly_outside_the_window_are_left_out() -> None:
    rule = WeeklyRule(Weekday.TUESDAY, time(15, 0), time(19, 0))
    window = TimeRange(utc(2026, 11, 17, 14, 30), utc(2026, 11, 17, 16, 30))

    assert starts(generate_slots(schedule(rule), window)) == [utc(2026, 11, 17, 15)]
