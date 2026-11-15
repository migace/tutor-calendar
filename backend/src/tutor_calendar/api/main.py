from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine

from tutor_calendar.adapters.clock import SystemClock
from tutor_calendar.adapters.mail import LoggingMailer
from tutor_calendar.adapters.manage_links import HmacManageLinks
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.credentials import PostgresCredentialStore
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.routes import auth, health, managed_booking, panel, series, slots
from tutor_calendar.api.routes import bookings as booking_routes
from tutor_calendar.application.ports import (
    BookingRepository,
    Clock,
    CredentialStore,
    Mailer,
    ManageLinks,
    TutorRepository,
)
from tutor_calendar.config import Settings

logger = logging.getLogger("tutor_calendar")


def _manage_links(settings: Settings) -> ManageLinks:
    if settings.secret_key is not None:
        return HmacManageLinks(settings.secret_key)
    logger.warning(
        "TC_SECRET_KEY is not set: links for managing a booking will stop working "
        "when this process restarts."
    )
    return HmacManageLinks.with_random_secret()


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    tutors: TutorRepository | None = None,
    bookings: BookingRepository | None = None,
    credentials: CredentialStore | None = None,
    mailer: Mailer | None = None,
    links: ManageLinks | None = None,
) -> FastAPI:
    """Composition root: the only place where adapters are chosen and wired together.

    Everything is backed by PostgreSQL unless a caller passes something else,
    which is how the fast tests swap in fakes.
    """
    settings = settings or Settings()
    # Creating the engine opens no connection; that happens on first use.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Tutor Calendar API", version="0.4.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.clock = clock or SystemClock()
    app.state.tutors = tutors or PostgresTutorRepository(engine)
    app.state.bookings = bookings or PostgresBookingRepository(engine)
    app.state.credentials = credentials or PostgresCredentialStore(engine)
    app.state.mailer = mailer or LoggingMailer()
    app.state.links = links or _manage_links(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # The session cookie has to travel when the web app is on another origin.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(slots.router, prefix="/api/v1")
    app.include_router(booking_routes.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(managed_booking.router, prefix="/api/v1")
    app.include_router(panel.router, prefix="/api/v1")
    app.include_router(series.router, prefix="/api/v1")
    return app


app = create_app()
