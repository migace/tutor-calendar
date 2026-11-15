"""Ways a use case can refuse a request. The API maps each to a status code."""

from __future__ import annotations


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
