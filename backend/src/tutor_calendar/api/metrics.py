"""What the process counts about itself, in the Prometheus text format. See ADR 0011.

Two kinds of number are served together. Counts of what this process did
(requests, booking outcomes) are kept in its memory and start again at zero
when it restarts. The state of the background work is not counted at all: it
is read from the database each time the metrics are asked for, so it is true
whichever worker did the work, and still there when no worker is running.

No label ever holds a tutor, a student or an address: the values are route
templates, status codes and a handful of fixed words.
"""

from __future__ import annotations

from enum import StrEnum

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ProcessCollector,
    disable_created_metrics,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from tutor_calendar.application.background import BackgroundWork

CONTENT_TYPE = CONTENT_TYPE_LATEST

# Without this every counter and histogram comes with a second series saying
# when it was created. Nothing here reads them.
disable_created_metrics()  # type: ignore[no-untyped-call]

# Seconds. Most requests here take a few milliseconds; the top end is for the
# day something is badly wrong.
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
# Anything else a client makes up is counted under one name, so that a scanner
# cannot add a series per request.
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


class BookingOutcome(StrEnum):
    BOOKED = "booked"
    # The time went to someone else first. See ADR 0003.
    TAKEN = "taken"
    # A repeat of an earlier request, answered with the booking that one made. See ADR 0004.
    REPLAYED = "replayed"
    # Too soon, or not a time the tutor teaches.
    NOT_OFFERED = "not_offered"


class Metrics:
    """One per application, so that two applications in one process count apart."""

    def __init__(self) -> None:
        self._registry = CollectorRegistry()
        # Memory and CPU of this process. Reports nothing where /proc does not exist.
        ProcessCollector(registry=self._registry)
        self._requests = Histogram(
            "tutor_calendar_http_request_duration_seconds",
            "Time to answer a request, by route template and status. "
            "Its _count is the number of requests.",
            ["method", "route", "status"],
            buckets=_BUCKETS,
            registry=self._registry,
        )
        self._bookings = Counter(
            "tutor_calendar_booking_requests",
            "Requests to book a lesson that reached a decision, by how they ended.",
            ["outcome"],
            registry=self._registry,
        )
        for outcome in BookingOutcome:
            # Present at zero from the start, so a rate can be drawn from the first one.
            self._bookings.labels(outcome.value)

    def request_answered(self, method: str, route: str, status: int, seconds: float) -> None:
        method = method if method in _METHODS else "OTHER"
        self._requests.labels(method, route, str(status)).observe(seconds)

    def booking(self, outcome: BookingOutcome) -> None:
        self._bookings.labels(outcome.value).inc()

    def render(self, work: BackgroundWork | None) -> bytes:
        """Everything, as text. ``work`` is None when the database could not be asked."""
        return generate_latest(self._registry) + generate_latest(_background(work))


def _background(work: BackgroundWork | None) -> CollectorRegistry:
    """The state of the background work as it is now.

    Built afresh for each reading: when the database does not answer these
    numbers are left out, not repeated from the last time it did.
    """
    registry = CollectorRegistry()
    Gauge(
        "tutor_calendar_database_up",
        "1 when the database answered this reading, 0 when it did not. "
        "At 0 the numbers about background work are missing.",
        registry=registry,
    ).set(0 if work is None else 1)
    if work is None:
        return registry
    Gauge(
        "tutor_calendar_outbox_waiting_messages",
        "E-mail queued and not sent yet, including messages waiting to be tried again.",
        registry=registry,
    ).set(work.unsent_messages)
    Gauge(
        "tutor_calendar_outbox_oldest_waiting_seconds",
        "How long the oldest unsent message has been queued. 0 when nothing is waiting.",
        registry=registry,
    ).set(work.oldest_unsent_age.total_seconds())
    Gauge(
        "tutor_calendar_lessons_awaiting_settlement",
        "Lessons whose cost is final and that the worker has not charged yet.",
        registry=registry,
    ).set(work.lessons_awaiting_settlement)
    last_success = Gauge(
        "tutor_calendar_worker_last_success_timestamp_seconds",
        "When each background job last finished without an error, as Unix time. "
        "A job that has never finished has no value.",
        ["job"],
        registry=registry,
    )
    for job, moment in work.last_success.items():
        last_success.labels(job).set(moment.timestamp())
    return registry
