"""Endpoints for the signed-in tutor. Every one of them requires a session."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from tutor_calendar.api.deps import (
    ChangeOwnLessonDep,
    ChangeWeeklyHoursDep,
    ShowWeekDep,
    SignedInTutor,
)
from tutor_calendar.api.schemas import (
    AvailabilityIn,
    AvailabilityOut,
    DayOut,
    ErrorOut,
    LessonOut,
    ProfileOut,
    WeeklyRuleModel,
    WeekOut,
)
from tutor_calendar.application.errors import (
    InvalidAvailabilityError,
    LessonChangeRefusedError,
    LessonNotFoundError,
)
from tutor_calendar.domain.scheduling import Booking, Tutor, Weekday, WeeklyRule

router = APIRouter(
    prefix="/me",
    tags=["tutor panel"],
    responses={401: {"model": ErrorOut, "description": "Not signed in"}},
)


def profile_of(tutor: Tutor) -> ProfileOut:
    return ProfileOut(
        slug=tutor.slug,
        display_name=tutor.display_name,
        email=tutor.email,
        timezone=tutor.schedule.timezone.key,
        lesson_minutes=tutor.schedule.lesson_duration // dt.timedelta(minutes=1),
    )


def lesson_out(lesson: Booking) -> LessonOut:
    cancellation = lesson.cancellation
    return LessonOut(
        id=lesson.id,
        start=lesson.slot.start,
        end=lesson.slot.end,
        student_name=lesson.student.name,
        student_email=lesson.student.email,
        status=lesson.status.value,
        cancelled_by=cancellation.by.value if cancellation else None,
        cancelled_late=cancellation.late if cancellation else None,
        series_id=lesson.series_id,
    )


def _availability_of(tutor: Tutor) -> AvailabilityOut:
    schedule = tutor.schedule
    return AvailabilityOut(
        timezone=schedule.timezone.key,
        lesson_minutes=schedule.lesson_duration // dt.timedelta(minutes=1),
        rules=[
            WeeklyRuleModel(weekday=int(rule.weekday), start=rule.start, end=rule.end)
            for rule in schedule.rules
        ],
    )


@router.get("", summary="The signed-in tutor")
async def me(tutor: SignedInTutor) -> ProfileOut:
    return profile_of(tutor)


@router.get("/week", summary="One week of the tutor's lessons, Monday to Sunday")
async def week(
    tutor: SignedInTutor,
    use_case: ShowWeekDep,
    date: Annotated[
        dt.date | None,
        Query(description="Any day of the week to show; defaults to the current week"),
    ] = None,
) -> WeekOut:
    view = await use_case.execute(tutor, date)
    return WeekOut(
        timezone=tutor.schedule.timezone.key,
        today=view.today,
        previous=view.week.previous,
        next=view.week.next,
        days=[
            DayOut(
                date=day.day,
                lessons=[lesson_out(lesson) for lesson in day.lessons],
            )
            for day in view.week.days
        ],
    )


@router.get("/availability", summary="The hours the tutor teaches each week")
async def availability(tutor: SignedInTutor) -> AvailabilityOut:
    return _availability_of(tutor)


@router.put(
    "/availability",
    summary="Replace the hours the tutor teaches each week",
    description="Lessons that are already booked are not affected.",
    responses={422: {"description": "The hours overlap or end before they start"}},
)
async def change_availability(
    body: AvailabilityIn, tutor: SignedInTutor, use_case: ChangeWeeklyHoursDep
) -> AvailabilityOut:
    try:
        rules = [WeeklyRule(Weekday(rule.weekday), rule.start, rule.end) for rule in body.rules]
        changed = await use_case.execute(tutor, rules)
    except (InvalidAvailabilityError, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return _availability_of(changed)


_LESSON_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorOut, "description": "No such lesson of this tutor"},
    409: {"model": ErrorOut, "description": "The lesson is not in a state that allows this"},
}


@router.post(
    "/lessons/{lesson_id}/cancellation",
    summary="Cancel one of the tutor's lessons",
    description="A lesson the tutor cancels is never charged to the student.",
    responses=_LESSON_ERRORS,
)
async def cancel_lesson(
    lesson_id: UUID, tutor: SignedInTutor, use_case: ChangeOwnLessonDep
) -> LessonOut:
    try:
        return lesson_out(await use_case.cancel(tutor, lesson_id))
    except LessonNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except LessonChangeRefusedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/lessons/{lesson_id}/no-show",
    summary="Record that the student did not turn up",
    description="Possible once the lesson has started. A no-show is charged.",
    responses=_LESSON_ERRORS,
)
async def mark_no_show(
    lesson_id: UUID, tutor: SignedInTutor, use_case: ChangeOwnLessonDep
) -> LessonOut:
    try:
        return lesson_out(await use_case.mark_no_show(tutor, lesson_id))
    except LessonNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except LessonChangeRefusedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
