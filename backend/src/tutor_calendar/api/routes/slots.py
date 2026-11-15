from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AwareDatetime

from tutor_calendar.api.deps import ListAvailableSlotsDep
from tutor_calendar.api.schemas import SlotOut, SlotsResponse, TutorOut
from tutor_calendar.application.list_available_slots import (
    InvalidWindowError,
    TutorNotFoundError,
)

router = APIRouter(tags=["slots"])


@router.get(
    "/tutors/{slug}/slots",
    summary="Slots that can still be booked with a tutor",
    responses={404: {"description": "No such tutor"}},
)
async def list_slots(
    slug: str,
    use_case: ListAvailableSlotsDep,
    start: Annotated[
        AwareDatetime | None,
        Query(alias="from", description="Start of the window; defaults to the earliest bookable"),
    ] = None,
    end: Annotated[
        AwareDatetime | None,
        Query(alias="to", description="End of the window; defaults to 14 days after the start"),
    ] = None,
) -> SlotsResponse:
    try:
        result = await use_case.execute(slug, start, end)
    except TutorNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidWindowError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error

    tutor = result.tutor
    return SlotsResponse(
        tutor=TutorOut(
            slug=tutor.slug,
            display_name=tutor.display_name,
            timezone=tutor.schedule.timezone.key,
            lesson_minutes=int(tutor.schedule.lesson_duration.total_seconds() // 60),
        ),
        slots=[SlotOut(start=slot.start, end=slot.end) for slot in result.slots],
    )
