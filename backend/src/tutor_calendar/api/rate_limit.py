"""How often one visitor may ask for something. See ADR 0009.

The limits live here, at the edge, and not in the use cases: they are about
who is knocking and how often, which the application knows nothing about.
"""

from __future__ import annotations

import ipaddress
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from fastapi import HTTPException, Request, status

from tutor_calendar.config import Settings


@dataclass(frozen=True)
class Limit:
    """``burst`` requests at once, earned back evenly over ``per_seconds``.

    Five per quarter of an hour means five in a row, then one every three
    minutes. There is no moment at which the whole allowance comes back, so
    there is no edge of a window to wait for and then double up on.
    """

    name: str
    burst: int
    per_seconds: float


# Every request to the API. High enough that a person using the app never
# meets it; low enough that a loop does.
ANY_REQUEST = Limit("any request", burst=120, per_seconds=60)
# Each of these sends an e-mail to an address the visitor typed in.
SIGN_IN_LINKS = Limit("sign-in links", burst=5, per_seconds=15 * 60)
# Each of these takes a slot away from everyone else and queues an e-mail.
BOOKINGS = Limit("bookings", burst=10, per_seconds=10 * 60)
# Each of these stores a session.
DEMO_SESSIONS = Limit("demo sessions", burst=20, per_seconds=10 * 60)

# Room for rounding: the tenth request of ten must not be refused because
# nine intervals added up to a hair more than nine.
_ROUNDING = 1e-9


class RateLimiter:
    """Counts requests in this process's memory.

    For each limit and each visitor it remembers one number: the moment the
    visitor's allowance will be whole again. Every request pushes that moment
    back by the time it takes to earn one request; a request is refused when
    the moment is further away than the whole allowance takes to earn.

    Nothing here waits, so on one event loop a check cannot be interleaved
    with another. With several processes each would count on its own; see the
    ADR for what to do then.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._whole_again_at: dict[tuple[str, str], float] = {}
        self._tidy_at = 1024

    def seconds_to_wait(self, limit: Limit, visitor: str) -> float:
        """Count one request. Zero when it may go ahead, otherwise how long until one may."""
        now = self._now()
        key = (limit.name, visitor)
        earning_one = limit.per_seconds / limit.burst
        whole_again_at = max(self._whole_again_at.get(key, now), now)
        spent = (whole_again_at - now) / earning_one
        if spent > limit.burst - 1 + _ROUNDING:
            # A refused request costs nothing, or hammering would never be let back in.
            return (spent - (limit.burst - 1)) * earning_one
        self._whole_again_at[key] = whole_again_at + earning_one
        if len(self._whole_again_at) >= self._tidy_at:
            self._forget_the_idle(now)
        return 0.0

    def _forget_the_idle(self, now: float) -> None:
        """Drop visitors whose allowance is whole again: forgetting them changes nothing."""
        self._whole_again_at = {
            key: moment for key, moment in self._whole_again_at.items() if moment > now
        }
        # Not on every request: wait until the table has doubled.
        self._tidy_at = max(1024, 2 * len(self._whole_again_at))

    def __len__(self) -> int:
        return len(self._whole_again_at)


def visitor_of(request: Request, header: str | None) -> str:
    """Whose allowance a request counts against.

    Behind a proxy every connection comes from the proxy, so the address is
    read from the header the proxy puts it in. That header is only worth
    believing when nothing can reach this process except through the proxy.
    """
    stated = request.headers.get(header) if header else None
    if stated is not None:
        # In a list of addresses, the last one was added by the nearest proxy.
        stated = stated.rsplit(",", 1)[-1].strip()
    elif request.client is not None:
        stated = request.client.host
    try:
        address = ipaddress.ip_address(stated or "")
    except ValueError:
        # Better one shared allowance than none at all.
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        # One household is given 2^64 addresses and may use any of them, so
        # the network it was given is counted, not the address.
        return str(ipaddress.ip_network((address, 64), strict=False).network_address)
    return str(address)


class Limited:
    """A dependency that answers 429 once the visitor is over a limit."""

    def __init__(self, limit: Limit) -> None:
        self.limit = limit

    def __call__(self, request: Request) -> None:
        limiter = cast(RateLimiter | None, request.app.state.rate_limiter)
        if limiter is None:
            return
        settings = cast(Settings, request.app.state.settings)
        visitor = visitor_of(request, settings.client_address_header)
        wait = limiter.seconds_to_wait(self.limit, visitor)
        if wait > 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many requests, try again later",
                headers={"Retry-After": str(math.ceil(wait))},
            )
