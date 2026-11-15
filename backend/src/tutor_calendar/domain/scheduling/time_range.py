from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True, order=True)
class TimeRange:
    """Half-open interval ``[start, end)`` between two instants.

    Both ends are normalised to UTC on construction, so two ranges built from
    different offsets compare and sort by the instant they describe.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        for name in ("start", "end"):
            value: datetime = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.start >= self.end:
            raise ValueError("start must be before end")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def overlaps(self, other: TimeRange) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: TimeRange) -> bool:
        return self.start <= other.start and other.end <= self.end
