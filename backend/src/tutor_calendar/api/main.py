from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine

from tutor_calendar.adapters.clock import SystemClock
from tutor_calendar.adapters.mail import OutboxMailer
from tutor_calendar.adapters.manage_links import HmacManageLinks, HmacStatementLinks
from tutor_calendar.adapters.postgres.billing import PostgresLedger, PostgresOutbox
from tutor_calendar.adapters.postgres.bookings import PostgresBookingRepository
from tutor_calendar.adapters.postgres.credentials import PostgresCredentialStore
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.rate_limit import ANY_REQUEST, Limited, RateLimiter
from tutor_calendar.api.routes import (
    auth,
    billing,
    health,
    managed_booking,
    panel,
    series,
    slots,
)
from tutor_calendar.api.routes import bookings as booking_routes
from tutor_calendar.api.schemas import ErrorOut
from tutor_calendar.api.web_app import HttpsRedirect, SecurityHeaders, WebApp
from tutor_calendar.application.ports import (
    BookingRepository,
    Clock,
    CredentialStore,
    Ledger,
    Mailer,
    ManageLinks,
    StatementLinks,
    TutorRepository,
)
from tutor_calendar.config import Settings

logger = logging.getLogger("tutor_calendar")


def _signing_secret(settings: Settings) -> str:
    if settings.secret_key is not None:
        return settings.secret_key
    logger.warning(
        "TC_SECRET_KEY is not set: links for managing a booking and for reading a "
        "statement will stop working when this process restarts."
    )
    return secrets.token_urlsafe(32)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    tutors: TutorRepository | None = None,
    bookings: BookingRepository | None = None,
    credentials: CredentialStore | None = None,
    mailer: Mailer | None = None,
    links: ManageLinks | None = None,
    ledger: Ledger | None = None,
    statement_links: StatementLinks | None = None,
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

    app = FastAPI(title="Tutor Calendar API", version="0.6.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.clock = clock or SystemClock()
    app.state.tutors = tutors or PostgresTutorRepository(engine)
    app.state.bookings = bookings or PostgresBookingRepository(engine)
    app.state.credentials = credentials or PostgresCredentialStore(engine)
    app.state.ledger = ledger or PostgresLedger(engine)
    # Nothing is sent while a request is being answered: mail is queued in the
    # database and a worker delivers it. See ADR 0007.
    app.state.mailer = mailer or OutboxMailer(PostgresOutbox(engine), app.state.clock)
    if links is None or statement_links is None:
        secret = _signing_secret(settings)
        links = links or HmacManageLinks(secret)
        statement_links = statement_links or HmacStatementLinks(secret)
    app.state.links = links
    app.state.statement_links = statement_links

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # The session cookie has to travel when the web app is on another origin.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Kept in this process: there is one of it. See ADR 0009.
    app.state.rate_limiter = RateLimiter() if settings.rate_limits else None
    api = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(Limited(ANY_REQUEST))],
        responses={
            429: {
                "model": ErrorOut,
                "description": (
                    "Too many requests from this address. `Retry-After` says how many "
                    "seconds to wait."
                ),
            }
        },
    )
    api.include_router(health.public)
    api.include_router(slots.router)
    api.include_router(booking_routes.router)
    api.include_router(auth.router)
    api.include_router(managed_booking.router)
    api.include_router(panel.router)
    api.include_router(series.router)
    api.include_router(billing.panel)
    api.include_router(billing.shared)
    # The health checks stay outside: whatever watches the process must never be told to wait.
    app.include_router(health.router)
    app.include_router(api)

    app.add_middleware(SecurityHeaders)
    if settings.public_url.startswith("https://"):
        # Outermost, so that nothing is answered over plain HTTP first.
        app.add_middleware(HttpsRedirect)
    if settings.static_dir is not None:
        # Last, so that it only sees what no API route claimed.
        app.mount("/", WebApp(settings.static_dir), name="web")
    return app


app = create_app()
