from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.factories import FIRST_SLOT, NOW, a_booking
from tutor_calendar.domain.billing import (
    EntryKind,
    LedgerEntry,
    account_key,
    balance,
    charge_for,
    is_settled,
    statement_for,
)
from tutor_calendar.domain.scheduling import Actor, FreeUntil, TimeRange

HOUR = timedelta(hours=1)
AFTER = FIRST_SLOT + 2 * HOUR
TUTOR = uuid4()
A_DAY_AHEAD = FreeUntil(timedelta(hours=24))


def entry(minutes: int, at: datetime = NOW, kind: EntryKind = EntryKind.PURCHASE, **changes):  # type: ignore[no-untyped-def]
    values = {
        "id": uuid4(),
        "tutor_id": TUTOR,
        "account": "anna@example.com",
        "kind": kind,
        "minutes": minutes,
        "note": "a note",
        "created_at": at,
        "effective_at": at,
    }
    return LedgerEntry(**(values | changes))  # type: ignore[arg-type]


class TestEntries:
    def test_an_account_is_an_address_without_regard_to_case(self) -> None:
        assert account_key("  Anna@Example.COM ") == "anna@example.com"

    @pytest.mark.parametrize(
        ("changes", "reason"),
        [
            ({"minutes": 0}, "between 1 and 60000"),
            ({"minutes": 60_001}, "between 1 and 60000"),
            ({"account": "Anna@example.com"}, "lower-case"),
            ({"account": "not-an-address"}, "lower-case"),
            ({"note": "x" * 201}, "200 characters"),
            ({"minutes": -60}, "a purchase adds time"),
            ({"kind": EntryKind.ADJUSTMENT, "note": "  "}, "has to say why"),
            ({"kind": EntryKind.LESSON, "minutes": -60}, "names a lesson"),
            ({"booking_id": uuid4()}, "names a lesson"),
            ({"kind": EntryKind.LESSON, "minutes": 60, "booking_id": uuid4()}, "uses time up"),
            ({"created_at": datetime(2026, 11, 16, 8, 0)}, "timezone-aware"),  # noqa: DTZ001
        ],
    )
    def test_entries_that_make_no_sense_cannot_exist(self, changes, reason: str) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError, match=reason):
            entry(**({"minutes": 60} | changes))

    def test_a_correction_may_go_either_way(self) -> None:
        assert entry(-30, kind=EntryKind.ADJUSTMENT).minutes == -30
        assert entry(30, kind=EntryKind.ADJUSTMENT).minutes == 30


class TestChargingALesson:
    def test_a_lesson_that_took_place_costs_its_length(self) -> None:
        lesson = a_booking(TUTOR, minutes=45)

        charge = charge_for(lesson, AFTER)

        assert charge is not None
        assert (charge.kind, charge.minutes, charge.note) == (EntryKind.LESSON, -45, "Lesson")
        assert (charge.booking_id, charge.account) == (lesson.id, "anna@example.com")
        # On the statement it belongs to the day of the lesson, not the day it was charged.
        assert (charge.effective_at, charge.created_at) == (FIRST_SLOT, AFTER)

    def test_a_lesson_that_can_still_be_cancelled_is_not_charged_yet(self) -> None:
        lesson = a_booking(TUTOR)

        assert not is_settled(lesson, FIRST_SLOT + timedelta(minutes=30))
        with pytest.raises(ValueError, match="can still change"):
            charge_for(lesson, FIRST_SLOT + timedelta(minutes=30))
        assert is_settled(lesson, FIRST_SLOT + HOUR)

    def test_a_no_show_is_charged(self) -> None:
        missed = a_booking(TUTOR).mark_no_show(FIRST_SLOT + timedelta(minutes=10))

        charge = charge_for(missed, FIRST_SLOT + timedelta(minutes=10))

        assert charge is not None
        assert (charge.minutes, charge.note) == (-60, "Missed lesson")

    def test_a_late_cancellation_is_charged_at_once(self) -> None:
        late = a_booking(TUTOR).cancel(Actor.STUDENT, FIRST_SLOT - HOUR, A_DAY_AHEAD)

        charge = charge_for(late, FIRST_SLOT - HOUR)

        assert charge is not None
        assert (charge.minutes, charge.note) == (-60, "Lesson cancelled late")

    @pytest.mark.parametrize("by", [Actor.STUDENT, Actor.TUTOR])
    def test_a_cancellation_in_time_costs_nothing(self, by: Actor) -> None:
        cancelled = a_booking(TUTOR).cancel(by, FIRST_SLOT - 3 * 24 * HOUR, A_DAY_AHEAD)

        assert is_settled(cancelled, NOW)
        assert charge_for(cancelled, NOW) is None

    def test_charging_a_lesson_twice_produces_the_same_entry(self) -> None:
        lesson = a_booking(TUTOR)

        first, again = charge_for(lesson, AFTER), charge_for(lesson, AFTER + HOUR)

        assert first is not None
        assert again is not None
        # Same id, which is how a store knows to keep only one.
        assert first.id == again.id


class TestStatements:
    NOVEMBER = TimeRange(datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))

    def test_a_statement_starts_from_what_came_before_and_lists_the_period(self) -> None:
        october = entry(600, datetime(2026, 10, 5, tzinfo=UTC))
        used = entry(-60, datetime(2026, 10, 20, tzinfo=UTC), EntryKind.ADJUSTMENT)
        late_november = entry(-45, datetime(2026, 11, 25, tzinfo=UTC), EntryKind.ADJUSTMENT)
        early_november = entry(300, datetime(2026, 11, 2, tzinfo=UTC))
        december = entry(120, datetime(2026, 12, 1, tzinfo=UTC))

        statement = statement_for(
            [december, late_november, october, early_november, used], self.NOVEMBER
        )

        assert statement.opening == 540
        assert statement.entries == (early_november, late_november)
        assert statement.closing == 795

    def test_an_empty_account_has_an_empty_statement(self) -> None:
        statement = statement_for([], self.NOVEMBER)

        assert (statement.opening, statement.entries, statement.closing) == (0, (), 0)

    def test_a_balance_can_be_negative(self) -> None:
        lesson = charge_for(a_booking(TUTOR), AFTER)
        assert lesson is not None

        assert balance([lesson]) == -60


# Hypothesis wants naive bounds and attaches the zone itself.
moments = st.datetimes(
    min_value=datetime(2026, 1, 1),  # noqa: DTZ001
    max_value=datetime(2026, 12, 31),  # noqa: DTZ001
    timezones=st.just(UTC),
)
histories = st.lists(
    st.tuples(st.integers(-600, 600).filter(lambda minutes: minutes != 0), moments), max_size=30
)


@given(histories, st.lists(moments, min_size=2, max_size=6, unique=True))
def test_consecutive_statements_join_up_and_add_to_the_balance(history, cuts) -> None:  # type: ignore[no-untyped-def]
    entries = [entry(minutes, at, EntryKind.ADJUSTMENT) for minutes, at in history]
    boundaries = sorted(cuts)
    periods = [TimeRange(a, b) for a, b in itertools.pairwise(boundaries)]

    statements = [statement_for(entries, period) for period in periods]

    # Each statement ends where the next begins: no minute appears twice or goes missing.
    for earlier, later in itertools.pairwise(statements):
        assert earlier.closing == later.opening
    # And everything from the first cut to the last is accounted for.
    inside = [e for e in entries if boundaries[0] <= e.effective_at < boundaries[-1]]
    assert statements[-1].closing - statements[0].opening == balance(inside)
    assert sum(len(s.entries) for s in statements) == len(inside)


def test_the_id_of_a_charge_depends_only_on_the_lesson() -> None:
    lesson = a_booking(TUTOR)
    charge = charge_for(lesson, AFTER)

    assert charge is not None
    assert isinstance(charge.id, UUID)
    assert charge.id != lesson.id
