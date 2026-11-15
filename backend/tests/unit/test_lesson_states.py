from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.factories import FIRST_SLOT, a_booking
from tutor_calendar.domain.scheduling import (
    Actor,
    AlwaysFree,
    Booking,
    Cancellation,
    FreeUntil,
    LessonStatus,
    LessonTransitionError,
    policy_with_notice,
)

HOUR = timedelta(hours=1)
A_DAY_AHEAD = FreeUntil(timedelta(hours=24))
LONG_BEFORE = FIRST_SLOT - timedelta(days=3)
SHORTLY_BEFORE = FIRST_SLOT - 2 * HOUR
DURING = FIRST_SLOT + timedelta(minutes=10)


def a_lesson() -> Booking:
    return a_booking(uuid4())


class TestCancelling:
    def test_in_good_time_it_costs_nothing(self) -> None:
        cancelled = a_lesson().cancel(Actor.STUDENT, LONG_BEFORE, A_DAY_AHEAD)

        assert cancelled.status is LessonStatus.CANCELLED
        assert cancelled.cancellation == Cancellation(Actor.STUDENT, LONG_BEFORE, late=False)
        assert not cancelled.is_charged
        assert not cancelled.occupies_time

    def test_after_the_deadline_it_is_still_charged(self) -> None:
        cancelled = a_lesson().cancel(Actor.STUDENT, SHORTLY_BEFORE, A_DAY_AHEAD)

        assert cancelled.cancellation is not None
        assert cancelled.cancellation.late
        assert cancelled.is_charged
        # Charged or not, the tutor has the hour back.
        assert not cancelled.occupies_time

    def test_exactly_at_the_deadline_is_still_in_time(self) -> None:
        deadline = FIRST_SLOT - timedelta(hours=24)

        on_time = a_lesson().cancel(Actor.STUDENT, deadline, A_DAY_AHEAD)
        just_late = a_lesson().cancel(Actor.STUDENT, deadline + timedelta(seconds=1), A_DAY_AHEAD)

        assert not on_time.is_charged
        assert just_late.is_charged

    def test_a_tutor_who_cancels_never_charges_the_student(self) -> None:
        cancelled = a_lesson().cancel(Actor.TUTOR, SHORTLY_BEFORE, A_DAY_AHEAD)

        assert cancelled.cancellation == Cancellation(Actor.TUTOR, SHORTLY_BEFORE, late=False)
        assert not cancelled.is_charged

    def test_some_tutors_never_charge_for_cancelling(self) -> None:
        cancelled = a_lesson().cancel(Actor.STUDENT, SHORTLY_BEFORE, AlwaysFree())

        assert not cancelled.is_charged

    @pytest.mark.parametrize("moment", [FIRST_SLOT, DURING, FIRST_SLOT + 5 * HOUR])
    def test_a_lesson_that_has_started_cannot_be_cancelled(self, moment) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(LessonTransitionError, match="has started"):
            a_lesson().cancel(Actor.STUDENT, moment, A_DAY_AHEAD)

    def test_it_cannot_be_cancelled_twice(self) -> None:
        cancelled = a_lesson().cancel(Actor.STUDENT, LONG_BEFORE, A_DAY_AHEAD)

        with pytest.raises(LessonTransitionError, match="a cancelled lesson cannot be cancelled"):
            cancelled.cancel(Actor.TUTOR, LONG_BEFORE + HOUR, A_DAY_AHEAD)


class TestNoShow:
    def test_a_no_show_is_charged_and_the_time_was_used(self) -> None:
        missed = a_lesson().mark_no_show(DURING)

        assert missed.status is LessonStatus.NO_SHOW
        assert missed.is_charged
        assert missed.occupies_time

    def test_nobody_is_a_no_show_before_the_lesson_starts(self) -> None:
        with pytest.raises(LessonTransitionError, match="has not started"):
            a_lesson().mark_no_show(SHORTLY_BEFORE)

    def test_a_cancelled_lesson_cannot_become_a_no_show(self) -> None:
        cancelled = a_lesson().cancel(Actor.STUDENT, LONG_BEFORE, A_DAY_AHEAD)

        with pytest.raises(LessonTransitionError, match="a cancelled lesson"):
            cancelled.mark_no_show(DURING)

    def test_a_no_show_cannot_be_cancelled_afterwards(self) -> None:
        missed = a_lesson().mark_no_show(DURING)

        with pytest.raises(LessonTransitionError, match="a no-show lesson"):
            missed.cancel(Actor.TUTOR, DURING, A_DAY_AHEAD)


class TestPolicies:
    def test_the_deadline_is_the_notice_before_the_lesson(self) -> None:
        lesson = a_lesson()

        assert A_DAY_AHEAD.free_until(lesson) == FIRST_SLOT - timedelta(hours=24)
        assert AlwaysFree().free_until(lesson) is None

    def test_a_tutors_setting_picks_the_policy(self) -> None:
        assert policy_with_notice(None) == AlwaysFree()
        assert policy_with_notice(timedelta(hours=6)) == FreeUntil(timedelta(hours=6))

    @pytest.mark.parametrize("notice", [timedelta(0), timedelta(hours=-1)])
    def test_a_notice_must_be_positive(self, notice: timedelta) -> None:
        with pytest.raises(ValueError, match="positive"):
            FreeUntil(notice)


def test_a_plain_lesson_is_charged_and_occupies_its_time() -> None:
    lesson = a_lesson()

    assert lesson.status is LessonStatus.CONFIRMED
    assert lesson.is_charged
    assert lesson.occupies_time


def test_cancellation_details_and_status_must_agree() -> None:
    lesson = a_lesson()

    with pytest.raises(ValueError, match="exactly when it is cancelled"):
        Booking(
            id=lesson.id,
            tutor_id=lesson.tutor_id,
            slot=lesson.slot,
            student=lesson.student,
            created_at=lesson.created_at,
            status=LessonStatus.CANCELLED,
        )


# What can be asked of a lesson, at a moment relative to its start.
events = st.tuples(
    st.sampled_from(["student cancels", "tutor cancels", "no-show"]),
    st.timedeltas(min_value=timedelta(days=-5), max_value=timedelta(days=1)),
)


@given(st.lists(events, max_size=6), st.sampled_from([A_DAY_AHEAD, AlwaysFree()]))
def test_whatever_is_tried_a_lesson_changes_state_at_most_once(history, policy) -> None:  # type: ignore[no-untyped-def]
    lesson = a_lesson()
    changes = 0

    for event, offset in history:
        at = FIRST_SLOT + offset
        before = lesson
        try:
            if event == "no-show":
                lesson = lesson.mark_no_show(at)
            else:
                actor = Actor.STUDENT if event.startswith("student") else Actor.TUTOR
                lesson = lesson.cancel(actor, at, policy)
        except LessonTransitionError:
            # A refused request leaves the lesson exactly as it was.
            assert lesson is before
            continue
        changes += 1
        assert before.status is LessonStatus.CONFIRMED
        assert lesson.status is not LessonStatus.CONFIRMED

    assert changes <= 1
    # The two facts the rest of the system relies on stay consistent.
    assert lesson.occupies_time == (lesson.status is not LessonStatus.CANCELLED)
    if lesson.cancellation is not None and lesson.cancellation.by is Actor.TUTOR:
        assert not lesson.is_charged
