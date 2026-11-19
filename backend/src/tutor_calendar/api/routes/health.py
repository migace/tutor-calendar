"""Two questions asked by whatever watches the process. See ADR 0011.

"Are you alive?" is answered without looking at anything, so that a slow
database cannot get a healthy process restarted. "Can you serve?" looks at the
database, and is the one to send traffic by.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from tutor_calendar.adapters.postgres.migrations import SchemaState, schema
from tutor_calendar.api.deps import EngineDep, SettingsDep
from tutor_calendar.api.schemas import ConfigOut, HealthOut

router = APIRouter(prefix="/health", tags=["health"])

# Whoever asks gives up after a few seconds. Answering "no" before then is
# worth more than an answer that never arrives.
READINESS_TIMEOUT_SECONDS = 2.0


@router.get("", summary="Liveness: the process is up")
async def live() -> HealthOut:
    return HealthOut(status="ok")


@router.get(
    "/ready",
    summary="Readiness: the database answers and has the migrations this version needs",
)
async def ready(engine: EngineDep) -> HealthOut:
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS), engine.connect() as connection:
            found = await schema(connection)
    except (SQLAlchemyError, OSError) as error:
        # A connection that timed out arrives here too: TimeoutError is an OSError.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not reachable",
        ) from error
    if found.state is SchemaState.EMPTY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database has not been migrated",
        )
    if found.state is SchemaState.BEHIND:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"database is behind: it is at migration {found.applied} "
                f"and this version needs {found.needed}"
            ),
        )
    # A database that is ahead was migrated by a newer version that is being
    # put up next to this one. Migrations are written so that the previous
    # version keeps working, so this process goes on serving until it is stopped.
    return HealthOut(status="ok")


public = APIRouter(tags=["configuration"])


@public.get("/config", summary="What the web app needs to know before anyone signs in")
async def config(settings: SettingsDep) -> ConfigOut:
    return ConfigOut(demo_mode=settings.demo_mode)
