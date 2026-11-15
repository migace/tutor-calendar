"""Weekly series of lessons, managed by the signed-in tutor."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from tutor_calendar.api.deps import EndSeriesDep, ListSeriesDep, SignedInTutor, StartSeriesDep
from tutor_calendar.api.routes.panel import lesson_out
from tutor_calendar.api.schemas import ErrorOut, SeriesConflictOut, SeriesIn, SeriesOut
from tutor_calendar.application.errors import (
    InvalidSeriesError,
    SeriesConflictError,
    SeriesNotFoundError,
)
from tutor_calendar.application.series import SeriesOverview
from tutor_calendar.domain.scheduling import Student, WeeklySeries, local_day

router = APIRouter(
    prefix="/me/series",
    tags=["tutor panel"],
    responses={401: {"model": ErrorOut, "description": "Not signed in"}},
)


def _out(overview: SeriesOverview) -> SeriesOut:
    plan = overview.series.plan
    return SeriesOut(
        id=overview.series.id,
        student_name=plan.student.name,
        student_email=plan.student.email,
        first_day=plan.first_day,
        start=plan.start,
        weeks=plan.weeks,
        lessons=[lesson_out(lesson) for lesson in overview.lessons],
        days_without_lesson=overview.days_without_lesson,
    )


@router.get("", summary="The tutor's weekly series, oldest first")
async def list_series(tutor: SignedInTutor, use_case: ListSeriesDep) -> list[SeriesOut]:
    return [_out(overview) for overview in await use_case.execute(tutor)]


@router.put(
    "/{series_id}",
    response_model=SeriesOut,
    summary="Book a lesson every week for a number of weeks",
    description=(
        "The client chooses the id. Sending the same request again returns the series "
        "as it was first created, so the request is safe to repeat."
    ),
    responses={
        409: {
            "model": SeriesConflictOut,
            "description": "Some lessons overlap ones already booked. Nothing was stored.",
        },
        422: {"description": "The plan is not possible, or the id belongs to another series"},
    },
)
async def start_series(
    series_id: UUID, body: SeriesIn, tutor: SignedInTutor, use_case: StartSeriesDep
) -> SeriesOut | JSONResponse:
    try:
        plan = WeeklySeries(
            first_day=body.first_day,
            start=body.start,
            weeks=body.weeks,
            student=Student(body.student_name, body.student_email),
        )
        overview = await use_case.execute(
            tutor, series_id, plan, skip_conflicts=body.skip_conflicts
        )
    except SeriesConflictError as error:
        tz = tutor.schedule.timezone
        conflict = SeriesConflictOut(
            detail=str(error), conflicts=[local_day(slot.start, tz) for slot in error.slots]
        )
        return JSONResponse(conflict.model_dump(mode="json"), status.HTTP_409_CONFLICT)
    except (InvalidSeriesError, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return _out(overview)


@router.delete(
    "/{series_id}",
    summary="End a series: cancel its lessons that have not started",
    description="Past lessons are kept. The cancelled ones are not charged.",
    responses={404: {"model": ErrorOut, "description": "No such series of this tutor"}},
)
async def end_series(series_id: UUID, tutor: SignedInTutor, use_case: EndSeriesDep) -> SeriesOut:
    try:
        return _out(await use_case.execute(tutor, series_id))
    except SeriesNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
