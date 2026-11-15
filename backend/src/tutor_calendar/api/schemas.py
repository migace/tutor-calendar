from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, StringConstraints, field_validator

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


class SignInLinkIn(BaseModel):
    email: Annotated[EmailStr, Field(max_length=MAX_EMAIL_LENGTH)]


class SignInIn(BaseModel):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]


class ProfileOut(BaseModel):
    slug: str
    display_name: str
    email: str
    timezone: str
    lesson_minutes: int


class WeeklyRuleModel(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 is Monday")
    start: dt.time = Field(description="Wall-clock time in the tutor's zone, to the minute")
    end: dt.time

    @field_validator("start", "end")
    @classmethod
    def wall_clock_to_the_minute(cls, value: dt.time) -> dt.time:
        if value.tzinfo is not None:
            raise ValueError("must be a wall-clock time without an offset")
        if value.second or value.microsecond:
            raise ValueError("must be a whole number of minutes")
        return value


class AvailabilityIn(BaseModel):
    rules: Annotated[list[WeeklyRuleModel], Field(max_length=70)]


class AvailabilityOut(BaseModel):
    timezone: str
    lesson_minutes: int
    rules: list[WeeklyRuleModel]


class LessonOut(BaseModel):
    id: UUID
    start: AwareDatetime
    end: AwareDatetime
    student_name: str
    student_email: str


class DayOut(BaseModel):
    date: dt.date
    lessons: list[LessonOut]


class WeekOut(BaseModel):
    timezone: str
    today: dt.date = Field(description="Today on the tutor's calendar")
    previous: dt.date = Field(description="A date in the week before this one")
    next: dt.date = Field(description="A date in the week after this one")
    days: list[DayOut] = Field(description="Monday to Sunday")


class ErrorOut(BaseModel):
    detail: str


class HealthOut(BaseModel):
    status: str
