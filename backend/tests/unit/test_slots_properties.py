"""Invariants of slot generation, checked against random schedules in every IANA zone.

Example tests cover the DST cases we thought of. These cover the ones we did
not: half-hour offsets, zones that change clocks at midnight, 30-minute DST
(Lord Howe), two-hour DST (Troll), lesson lengths that do not divide the hour.

Clock changes happen on two nights a year, so uniformly random windows almost
never see one. The strategies below are deliberately biased: half of the
windows are placed on top of an offset change, and rules often span the night.
"""

from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from tutor_calendar.domain.scheduling import (
    Schedule,
    TimeRange,
    Weekday,
    WeeklyRule,
    generate_slots,
    slot_starting_at,
)

Case = tuple[Schedule, TimeRange]

FIRST_YEAR, LAST_YEAR = 2024, 2030
ZONES_WITH_UNUSUAL_CLOCK_CHANGES = [
    "Europe/Warsaw",
    "America/New_York",
    "America/St_Johns",  # UTC-3:30
    "America/Havana",  # changes at midnight
    "America/Santiago",  # southern hemisphere, changes at midnight
    "Africa/Casablanca",  # "negative" DST around Ramadan
    "Antarctica/Troll",  # two-hour jump
    "Australia/Lord_Howe",  # half-hour jump
    "Pacific/Chatham",  # UTC+12:45
]

zones = st.one_of(
    st.sampled_from(ZONES_WITH_UNUSUAL_CLOCK_CHANGES).map(ZoneInfo),
    st.timezones().filter(lambda tz: isinstance(tz, ZoneInfo)),
)
lesson_durations = st.sampled_from([15, 20, 30, 45, 50, 60, 90, 120]).map(
    lambda minutes: timedelta(minutes=minutes)
)
five_minute_marks = st.integers(min_value=0, max_value=287).map(lambda step: step * 5)
# Start and end minutes of the rules on one weekday. Each shape exists to make a
# particular clock-change bug reachable; a schedule uses one shape all week, so
# the night of the change is always covered by it.
RULE_SHAPES = {
    # Zero to two arbitrary rules.
    "anything": st.lists(five_minute_marks, max_size=4, unique=True).map(sorted),
    # Starts in the small hours and runs all day: a lesson straddling the spring
    # gap is followed by more grid positions it could collide with.
    "from_night_on": st.integers(0, 35).map(lambda step: [step * 5, 23 * 60 + 55]),
    # Starts before 02:00 and ends before 05:00: the rule stops right after the
    # usual gap, where a lesson straddling it would overrun the rule.
    "night_only": st.tuples(st.integers(0, 23), st.integers(24, 60)).map(
        lambda marks: [marks[0] * 5, marks[1] * 5]
    ),
}


def _minute_of_day(minute: int) -> time:
    return time(minute // 60, minute % 60)


def _offset_changes(tz: ZoneInfo, year: int) -> list[datetime]:
    """UTC midnights in ``year`` that follow a day on which the zone's offset changed."""
    changes = []
    day = datetime(year, 1, 1, tzinfo=UTC)
    previous = day.astimezone(tz).utcoffset()
    for _ in range(366):
        day += timedelta(days=1)
        offset = day.astimezone(tz).utcoffset()
        if offset != previous:
            changes.append(day)
        previous = offset
    return changes


@st.composite
def schedules(draw: st.DrawFn, tz: ZoneInfo) -> Schedule:
    rule_boundaries = RULE_SHAPES[draw(st.sampled_from(sorted(RULE_SHAPES)))]
    rules: list[WeeklyRule] = []
    for weekday in Weekday:
        marks = draw(rule_boundaries)
        rules.extend(
            WeeklyRule(weekday, _minute_of_day(start), _minute_of_day(end))
            for start, end in zip(marks[::2], marks[1::2], strict=False)
        )
    days_off = draw(
        st.frozensets(st.dates(date(FIRST_YEAR, 1, 1), date(LAST_YEAR, 12, 31)), max_size=3)
    )
    return Schedule(tz, draw(lesson_durations), tuple(rules), days_off)


@st.composite
def windows(draw: st.DrawFn, tz: ZoneInfo) -> TimeRange:
    year = draw(st.integers(FIRST_YEAR, LAST_YEAR))
    changes = _offset_changes(tz, year)
    on_a_clock_change = draw(st.booleans())
    if changes and on_a_clock_change:
        # Start up to three days before a clock change and run past it.
        change = draw(st.sampled_from(changes))
        lead = draw(st.timedeltas(min_value=timedelta(hours=25), max_value=timedelta(days=3)))
        extra = draw(st.timedeltas(min_value=timedelta(hours=1), max_value=timedelta(days=4)))
        return TimeRange(change - lead, change + extra)
    start = datetime(year, 1, 1, tzinfo=UTC) + draw(
        st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=364))
    )
    length = draw(st.timedeltas(min_value=timedelta(hours=1), max_value=timedelta(days=21)))
    return TimeRange(start, start + length)


@st.composite
def cases(draw: st.DrawFn) -> Case:
    tz = draw(zones)
    return draw(schedules(tz)), draw(windows(tz))


def _wall_clock(instant: datetime, schedule: Schedule) -> datetime:
    return instant.astimezone(schedule.timezone).replace(tzinfo=None)


def _sits_inside(slot: TimeRange, rule: WeeklyRule, schedule: Schedule) -> bool:
    start = _wall_clock(slot.start, schedule)
    end = _wall_clock(slot.end, schedule)
    rule_start = datetime.combine(start.date(), rule.start)
    rule_end = datetime.combine(start.date(), rule.end)
    on_grid = (start - rule_start) % schedule.lesson_duration == timedelta(0)
    return rule_start <= start and end <= rule_end and on_grid


thorough = settings(deadline=None, max_examples=400)


@given(cases())
@thorough
def test_slots_are_ordered_and_never_overlap(case: Case) -> None:
    schedule, window = case

    for earlier, later in pairwise(generate_slots(schedule, window)):
        assert earlier.end <= later.start


@given(cases())
@thorough
def test_every_slot_lasts_exactly_one_lesson_and_fits_the_window(case: Case) -> None:
    schedule, window = case

    for slot in generate_slots(schedule, window):
        assert slot.duration == schedule.lesson_duration
        assert window.contains(slot)


@given(cases())
@thorough
def test_every_slot_sits_inside_a_rule_on_the_tutors_clock(case: Case) -> None:
    schedule, window = case

    for slot in generate_slots(schedule, window):
        day = _wall_clock(slot.start, schedule).date()
        assert any(_sits_inside(slot, rule, schedule) for rule in schedule.rules_on(day)), slot


@given(cases(), st.data())
@thorough
def test_busy_ranges_only_ever_remove_slots(case: Case, data: st.DataObject) -> None:
    schedule, window = case
    free = generate_slots(schedule, window)
    busy = data.draw(st.lists(st.sampled_from(free), max_size=5, unique=True)) if free else []

    remaining = generate_slots(schedule, window, busy)

    assert remaining == [slot for slot in free if slot not in busy]


@given(cases(), st.data())
@thorough
def test_a_narrower_window_returns_a_subset_of_the_same_grid(
    case: Case, data: st.DataObject
) -> None:
    schedule, window = case
    seconds = int(window.duration.total_seconds())
    cut_start = data.draw(st.integers(min_value=0, max_value=seconds - 1))
    cut_end = data.draw(st.integers(min_value=cut_start + 1, max_value=seconds))
    narrower = TimeRange(
        window.start + timedelta(seconds=cut_start),
        window.start + timedelta(seconds=cut_end),
    )

    wide = generate_slots(schedule, window)

    assert generate_slots(schedule, narrower) == [slot for slot in wide if narrower.contains(slot)]


@given(cases(), st.data())
@thorough
def test_a_start_can_be_booked_exactly_when_the_listing_shows_it(
    case: Case, data: st.DataObject
) -> None:
    schedule, window = case
    lesson = schedule.lesson_duration
    listed = {slot.start: slot for slot in generate_slots(schedule, window)}
    # Real starts, and the instants around them where an off-by-one would hide.
    shifts = [-lesson, -timedelta(minutes=1), timedelta(0), timedelta(minutes=1), lesson]
    nearby = [start + shift for start in listed for shift in shifts]
    probes = data.draw(st.lists(st.sampled_from(nearby), max_size=8)) if nearby else []

    for probe in probes:
        if window.contains(TimeRange(probe, probe + lesson)):
            assert slot_starting_at(schedule, probe) == listed.get(probe), probe
