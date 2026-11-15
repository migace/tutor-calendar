"""Who pays when a lesson is cancelled.

Each tutor picks a policy. The lesson asks it one question at the moment of
cancelling, and remembers the answer; changing the policy later never rewrites
what was agreed for lessons already cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from tutor_calendar.domain.scheduling.booking import Actor, Booking


class CancellationPolicy(Protocol):
    def is_late(self, lesson: Booking, by: Actor, at: datetime) -> bool:
        """Whether cancelling ``lesson`` at ``at`` still leaves it to be paid for."""
        ...

    def free_until(self, lesson: Booking) -> datetime | None:
        """Last moment a student can cancel for free, or None if they always can."""
        ...


@dataclass(frozen=True, slots=True)
class AlwaysFree:
    """Cancelling costs nothing, right up to the start of the lesson."""

    def is_late(self, lesson: Booking, by: Actor, at: datetime) -> bool:
        return False

    def free_until(self, lesson: Booking) -> datetime | None:
        return None


@dataclass(frozen=True, slots=True)
class FreeUntil:
    """Free up to a fixed time before the lesson; after that it is charged.

    A tutor who cancels never charges the student, however late it is.
    """

    notice: timedelta

    def __post_init__(self) -> None:
        if self.notice <= timedelta(0):
            raise ValueError("cancellation notice must be positive")

    def is_late(self, lesson: Booking, by: Actor, at: datetime) -> bool:
        return by is Actor.STUDENT and at > lesson.slot.start - self.notice

    def free_until(self, lesson: Booking) -> datetime | None:
        return lesson.slot.start - self.notice


def policy_with_notice(notice: timedelta | None) -> CancellationPolicy:
    """The policy a tutor's setting stands for: no notice means always free."""
    return AlwaysFree() if notice is None else FreeUntil(notice)
