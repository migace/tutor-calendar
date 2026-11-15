from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID

from tutor_calendar.domain.scheduling.availability import Schedule, WeeklyRule


@dataclass(frozen=True, slots=True)
class Tutor:
    id: UUID
    slug: str
    display_name: str
    # Where sign-in links are sent. Compared without regard to case.
    email: str
    schedule: Schedule
    # How far ahead a lesson has to be booked; nobody wants a booking for "in ten minutes".
    min_notice: timedelta = timedelta(hours=12)

    def __post_init__(self) -> None:
        if self.min_notice < timedelta(0):
            raise ValueError("minimum notice cannot be negative")
        local, at, host = self.email.rpartition("@")
        if not (at and local and host):
            raise ValueError("tutor email is not an address")

    def with_weekly_hours(self, rules: tuple[WeeklyRule, ...]) -> Tutor:
        """The same tutor teaching at different times. Invalid rules raise ``ValueError``."""
        return replace(self, schedule=replace(self.schedule, rules=rules))
