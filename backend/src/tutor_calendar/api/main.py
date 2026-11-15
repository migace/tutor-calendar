from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine

from tutor_calendar.adapters.clock import SystemClock
from tutor_calendar.adapters.in_memory_tutors import InMemoryTutorRepository, demo_tutor
from tutor_calendar.api.routes import health, slots
from tutor_calendar.application.ports import Clock, TutorRepository
from tutor_calendar.config import Settings


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    tutors: TutorRepository | None = None,
) -> FastAPI:
    """Composition root: the only place where adapters are chosen and wired together."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Creating the engine opens no connection; that happens on first use.
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.engine = engine
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Tutor Calendar API", version="0.1.0", lifespan=lifespan)
    app.state.clock = clock or SystemClock()
    app.state.tutors = tutors or InMemoryTutorRepository([demo_tutor()])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(slots.router, prefix="/api/v1")
    return app


app = create_app()
