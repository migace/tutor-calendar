from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from tutor_calendar.domain.scheduling.availability import Schedule


@dataclass(frozen=True, slots=True)
class Tutor:
    slug: str
    display_name: str
    schedule: Schedule
    # How far ahead a lesson has to be booked; nobody wants a booking for "in ten minutes".
    min_notice: timedelta = timedelta(hours=12)

    def __post_init__(self) -> None:
        if self.min_notice < timedelta(0):
            raise ValueError("minimum notice cannot be negative")
