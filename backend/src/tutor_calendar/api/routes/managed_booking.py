"""What a student can do with the manage token they received when booking.

The token is sent as a bearer credential, never in the URL, so it does not end
up in access logs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tutor_calendar.api.deps import ManageBookingDep
from tutor_calendar.api.schemas import ErrorOut, ManagedBookingOut
from tutor_calendar.application.errors import LessonChangeRefusedError, LessonNotFoundError
from tutor_calendar.application.lessons import ManagedLesson

router = APIRouter(
    prefix="/booking",
    tags=["bookings"],
    responses={401: {"model": ErrorOut, "description": "The manage token is missing or not valid"}},
)

_bearer = HTTPBearer(auto_error=False, description="The manage token from the booking response")


def _token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> str:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="a manage token is required")
    return credentials.credentials


ManageToken = Annotated[str, Depends(_token)]


def _out(managed: ManagedLesson) -> ManagedBookingOut:
    lesson = managed.lesson
    cancellation = lesson.cancellation
    return ManagedBookingOut(
        tutor_name=managed.tutor.display_name,
        timezone=managed.tutor.schedule.timezone.key,
        start=lesson.slot.start,
        end=lesson.slot.end,
        student_name=lesson.student.name,
        status=lesson.status.value,
        cancelled_by=cancellation.by.value if cancellation else None,
        cancelled_late=cancellation.late if cancellation else None,
        free_cancellation_until=managed.free_until,
        can_cancel=managed.can_cancel,
        late_if_cancelled_now=managed.late_now,
    )


@router.get("", summary="The booking a manage token belongs to")
async def view_booking(token: ManageToken, use_case: ManageBookingDep) -> ManagedBookingOut:
    try:
        return _out(await use_case.view(token))
    except LessonNotFoundError as error:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="this link is not valid"
        ) from error


@router.delete(
    "",
    summary="Cancel the booking",
    description=(
        "Free until the tutor's deadline. After it the lesson is cancelled all the "
        "same but still charged, and the response says so in `cancelled_late`."
    ),
    responses={409: {"model": ErrorOut, "description": "Already cancelled, or already started"}},
)
async def cancel_booking(token: ManageToken, use_case: ManageBookingDep) -> ManagedBookingOut:
    try:
        return _out(await use_case.cancel(token))
    except LessonNotFoundError as error:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="this link is not valid"
        ) from error
    except LessonChangeRefusedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
