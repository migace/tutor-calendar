from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, Field


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


class HealthOut(BaseModel):
    status: str
