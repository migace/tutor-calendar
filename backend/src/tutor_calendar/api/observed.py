"""What is written down about every request: an id, a log line and a measurement.

See ADR 0011. This is the outermost layer of the API, so it sees redirects,
refusals and failures as well as answers.
"""

from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from fastapi.routing import iter_route_contexts
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tutor_calendar.api.metrics import Metrics
from tutor_calendar.logs import request_id

REQUEST_ID_HEADER = "X-Request-ID"

# An id a caller sends is repeated in every log line and in a response header,
# so only something short and plain is taken. Anything else is replaced.
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")

# Asked every few seconds by whatever watches the process. Their successes
# would be most of the log and say nothing; their failures are still written.
_QUIET_ROUTES = frozenset({"/health", "/health/ready", "/metrics"})

# The request ended without an answer being started: it was cancelled, as at
# shutdown. Not a status this application ever sends; the number is borrowed
# from nginx. A client that merely hangs up does not show as this, because the
# server lets the application finish and discards what it sends.
CLIENT_CLOSED_REQUEST = 499

_MAX_PATH = 256

access = logging.getLogger("tutor_calendar.access")
logger = logging.getLogger("tutor_calendar.api")


def loggable_path(path: str) -> str:
    """The path as it may be written to a log.

    Students are named by id in every address the application hands out, and
    ids are kept: they are what makes a line useful. A segment that looks like
    an e-mail address is cut out, because a path is whatever the visitor typed
    and an old bookmark of a student's page still holds one. See ADR 0010.
    The query string is never part of this.
    """
    cut = "/".join("[address]" if "@" in segment else segment for segment in path.split("/"))
    return cut if len(cut) <= _MAX_PATH else cut[:_MAX_PATH] + "..."


class RouteTemplates:
    """The template of the route that answered, such as ``/api/v1/tutors/{slug}/slots``.

    Never the path itself: one series per student id would be useless and
    endless. What no API route claimed is the web app, or nothing.

    A route knows its own path but not the prefixes of the routers it was
    included under, so the whole templates are asked of the application once
    and looked up by route after that.
    """

    def __init__(self) -> None:
        self._whole: dict[int, str] = {}

    def of(self, scope: Scope, status: int) -> str:
        route = scope.get("route")
        if route is None:
            return self._without_a_route(scope, status)
        if id(route) not in self._whole:
            # The first request, or a route added since the last look.
            self._look(scope)
            self._whole.setdefault(id(route), str(getattr(route, "path", "unmatched")))
        return self._whole[id(route)]

    def _look(self, scope: Scope) -> None:
        self._whole = {
            id(context.original_route): context.path
            for context in iter_route_contexts(scope["app"].routes)
            if context.path is not None
        }

    def _without_a_route(self, scope: Scope, status: int) -> str:
        if isinstance(scope.get("endpoint"), StaticFiles):
            # The web app is mounted last and so is handed everything nothing
            # else answered, such as an API path that does not exist. Only
            # what it could serve is counted as its own.
            return "static" if status < 400 else "unmatched"
        if scope.get("endpoint") is None:
            return "unmatched"
        # The framework's own pages, such as /docs, are answered without
        # naming their route. Their paths have no parameters, so the path is
        # the template, but only if it is one the application really has.
        if not self._whole:
            self._look(scope)
        path = str(scope["path"])
        return path if path in self._whole.values() else "unmatched"


class Observed:
    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self._metrics = metrics
        self._routes = RouteTemplates()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        stated = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        this_request = stated if _SAFE_ID.fullmatch(stated) else uuid4().hex
        token = request_id.set(this_request)
        started = time.perf_counter()
        status: int | None = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = this_request
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Logged here, where the request's id is known, and answered here,
            # so that the person who saw the error can quote the id.
            logger.exception("unhandled error")
            if status is not None:
                # Part of an answer has gone out already; all that is left is to hang up.
                raise
            failure = JSONResponse({"detail": "internal server error"}, status_code=500)
            await failure(scope, receive, send_with_id)
        finally:
            seconds = time.perf_counter() - started
            self._record(scope, CLIENT_CLOSED_REQUEST if status is None else status, seconds)
            request_id.reset(token)

    def _record(self, scope: Scope, status: int, seconds: float) -> None:
        method, route = str(scope["method"]), self._routes.of(scope, status)
        self._metrics.request_answered(method, route, status, seconds)
        if route in _QUIET_ROUTES and status < 400:
            return
        path = loggable_path(str(scope["path"]))
        access.log(
            logging.ERROR if status >= 500 else logging.INFO,
            "%s %s %s",
            method,
            path,
            status,
            extra={
                "method": method,
                "path": path,
                "route": route,
                "status": status,
                "duration_ms": round(seconds * 1000, 1),
            },
        )
