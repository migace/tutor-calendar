from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.factories import NOW
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.in_memory_bookings import InMemoryBookingRepository
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository
from tutor_calendar.api.main import create_app
from tutor_calendar.demo import demo_tutor


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The API with fakes behind it: the demo tutor, no bookings, a clock stopped at NOW."""
    app = create_app(
        clock=FixedClock(NOW),
        tutors=InMemoryTutorRepository([demo_tutor()]),
        bookings=InMemoryBookingRepository(),
    )
    with TestClient(app) as test_client:
        yield test_client
