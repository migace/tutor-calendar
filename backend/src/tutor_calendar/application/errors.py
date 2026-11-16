"""Ways a use case can refuse a request. The API maps each to a status code."""

from __future__ import annotations

from tutor_calendar.domain.scheduling import TimeRange


class TutorNotFoundError(Exception):
    def __init__(self, slug: str) -> None:
        super().__init__(f"no tutor with slug {slug!r}")
        self.slug = slug


class InvalidWindowError(Exception):
    pass


class SlotNotOfferedError(Exception):
    """The requested time is not, or is no longer, one the tutor offers."""


class SlotTakenError(Exception):
    """Another booking already occupies the requested time."""

    def __init__(self) -> None:
        super().__init__("this time has just been booked by someone else")


class IdempotencyKeyReusedError(Exception):
    """The key has already been used for a different booking request."""

    def __init__(self) -> None:
        super().__init__("this Idempotency-Key was already used for a different request")


class InvalidSignInLinkError(Exception):
    """The sign-in token is unknown, expired or has been used already."""

    def __init__(self) -> None:
        super().__init__("this sign-in link is not valid any more")


class NotSignedInError(Exception):
    def __init__(self) -> None:
        super().__init__("sign in to continue")


class InvalidAvailabilityError(Exception):
    """The weekly hours a tutor asked for contradict each other."""


class LessonNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("no such lesson")


class LessonChangeRefusedError(Exception):
    """The lesson is not in a state that allows what was asked."""


class SeriesConflictError(Exception):
    """Some lessons of a weekly series would overlap lessons already booked."""

    def __init__(self, slots: list[TimeRange]) -> None:
        super().__init__("some of these lessons overlap lessons that are already booked")
        # The lessons of the series that are in the way of something.
        self.slots = slots


class InvalidSeriesError(Exception):
    pass


class InvalidEntryError(Exception):
    """A ledger entry that makes no sense, or an id reused for a different entry."""


class StatementNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("no such statement")


class SeriesNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("no such series")
