from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from tutor_calendar.api.deps import BookLessonDep
from tutor_calendar.api.schemas import BookingIn, BookingOut, ErrorOut
from tutor_calendar.application.errors import (
    IdempotencyKeyReusedError,
    SlotNotOfferedError,
    SlotTakenError,
    TutorNotFoundError,
)
from tutor_calendar.domain.scheduling import Student

router = APIRouter(tags=["bookings"])

IdempotencyKey = Annotated[
    str,
    Header(
        min_length=16,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "A random value the client makes up for this booking attempt, for example a "
            "UUID. Sending the same request again with the same key never books twice; "
            "it returns the booking the first attempt created."
        ),
    ),
]


@router.post(
    "/tutors/{slug}/bookings",
    status_code=status.HTTP_201_CREATED,
    summary="Book one lesson with a tutor",
    responses={
        201: {
            "headers": {
                "Idempotency-Replayed": {
                    "description": "'true' when this repeated an earlier request",
                    "schema": {"type": "string"},
                }
            }
        },
        404: {"model": ErrorOut, "description": "No such tutor"},
        409: {
            "model": ErrorOut,
            "description": (
                "The time cannot be booked: someone else has it, it is too soon, or the "
                "tutor does not offer it. Fetch the slots again and pick another."
            ),
        },
    },
)
async def book_lesson(
    slug: str,
    body: BookingIn,
    use_case: BookLessonDep,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> BookingOut:
    try:
        student = Student(body.student_name, body.student_email)
        result = await use_case.execute(slug, body.start, student, idempotency_key)
    except TutorNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except (SlotTakenError, SlotNotOfferedError) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (IdempotencyKeyReusedError, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error

    if result.replayed:
        response.headers["Idempotency-Replayed"] = "true"
    slot = result.booking.slot
    return BookingOut(
        id=result.booking.id, start=slot.start, end=slot.end, manage_token=result.manage_token
    )
