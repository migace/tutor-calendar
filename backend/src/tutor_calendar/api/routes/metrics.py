"""The metrics, for whoever holds the token. See ADR 0011."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError

from tutor_calendar.api.deps import MeasureBackgroundWorkDep, MetricsDep, SettingsDep
from tutor_calendar.api.metrics import CONTENT_TYPE
from tutor_calendar.application.background import BackgroundWork

router = APIRouter()
logger = logging.getLogger("tutor_calendar.api")

# The numbers that come from the database must not hold up the ones that do not.
DATABASE_TIMEOUT_SECONDS = 2.0


def _allowed(authorization: str | None, token: str) -> bool:
    scheme, _, given = (authorization or "").partition(" ")
    # Compared in constant time, and as bytes: a header may hold anything.
    return scheme.lower() == "bearer" and secrets.compare_digest(
        given.strip().encode(), token.encode()
    )


# Not part of the API the web app is generated from: this is for an operator's tools.
@router.get("/metrics", include_in_schema=False)
async def metrics(
    settings: SettingsDep,
    collected: MetricsDep,
    measure: MeasureBackgroundWorkDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    if settings.metrics_token is None:
        # Off until someone decides who may read it. The application's port
        # may be open to everyone, and how busy a tutor is is not public.
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not _allowed(authorization, settings.metrics_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})

    work: BackgroundWork | None
    try:
        async with asyncio.timeout(DATABASE_TIMEOUT_SECONDS):
            work = await measure.execute()
    except (SQLAlchemyError, OSError):
        # What this process counted is still worth having, most of all now.
        logger.warning("the database did not answer; metrics about background work left out")
        work = None
    return Response(collected.render(work), headers={"Content-Type": CONTENT_TYPE})
