from __future__ import annotations

import datetime as dt
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, StringConstraints, field_validator

from tutor_calendar.domain.scheduling.booking import MAX_EMAIL_LENGTH, MAX_NAME_LENGTH
from tutor_calendar.domain.scheduling.recurrence import MAX_OCCURRENCES


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
    manage_token: str = Field(
        description="Lets whoever holds it view and cancel this booking. Keep it private."
    )


class ManagedBookingOut(BaseModel):
    tutor_name: str
    timezone: str = Field(description="IANA zone of the tutor")
    start: AwareDatetime
    end: AwareDatetime
    student_name: str
    status: str
    cancelled_by: str | None
    cancelled_late: bool | None
    free_cancellation_until: AwareDatetime | None = Field(
        description="Null when cancelling is free right up to the lesson"
    )
    can_cancel: bool
    late_if_cancelled_now: bool


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
    status: str = Field(description="confirmed, cancelled or no_show")
    cancelled_by: str | None
    cancelled_late: bool | None
    series_id: UUID | None = Field(description="Set when the lesson belongs to a weekly series")


class SeriesIn(BaseModel):
    student_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)
    ]
    student_email: Annotated[EmailStr, Field(max_length=MAX_EMAIL_LENGTH)]
    first_day: dt.date = Field(description="Day of the first lesson, on the tutor's calendar")
    start: dt.time = Field(description="Wall-clock time in the tutor's zone, to the minute")
    weeks: int = Field(ge=1, le=MAX_OCCURRENCES)
    skip_conflicts: bool = Field(
        default=False,
        description="Leave out lessons that overlap something already booked, instead of failing",
    )


class SeriesOut(BaseModel):
    id: UUID
    student_name: str
    student_email: str
    first_day: dt.date
    start: dt.time
    weeks: int
    lessons: list[LessonOut]
    days_without_lesson: list[dt.date] = Field(
        description="Days of the plan with no lesson: days off, skipped by a clock change, "
        "or left out because of a conflict"
    )


class SeriesConflictOut(BaseModel):
    detail: str
    conflicts: list[dt.date] = Field(description="Days on which a lesson is already booked")


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
