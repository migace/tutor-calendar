from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from tutor_calendar.api.deps import EngineDep
from tutor_calendar.api.schemas import HealthOut

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Liveness: the process is up")
async def live() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/ready", summary="Readiness: the database answers")
async def ready(engine: EngineDep) -> HealthOut:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not reachable",
        ) from error
    return HealthOut(status="ok")
