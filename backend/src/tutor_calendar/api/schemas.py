from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, StringConstraints

from tutor_calendar.domain.scheduling.booking import MAX_EMAIL_LENGTH, MAX_NAME_LENGTH


class TutorOut(BaseModel):
    slug: str
    display_name: str
    timezone: str = Field(description="IANA zone the tutor's schedule is defined in")
    lesson_minutes: int


class SlotOut(BaseModel):
    start: AwareDatetime = Field(description="UTC instant the lesson starts")
    end: AwareDatetime = Field(description="UTC instant the lesson ends")


class SlotsResponse(BaseModel):
    tutor: TutorOut
    slots: list[SlotOut]


class BookingIn(BaseModel):
    start: AwareDatetime = Field(
        description="Start of the slot to book, exactly as returned by the slots endpoint"
    )
    student_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)
    ]
    student_email: Annotated[EmailStr, Field(max_length=MAX_EMAIL_LENGTH)]


class BookingOut(BaseModel):
    id: UUID
    start: AwareDatetime
    end: AwareDatetime


class ErrorOut(BaseModel):
    detail: str


class HealthOut(BaseModel):
    status: str
