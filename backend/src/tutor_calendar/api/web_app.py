"""Serving the built web app from the API process, and the headers that go with it.

In development the web app runs on Vite's server and none of this is used. In
production one process serving both means one origin: no CORS, and cookies and
links that simply work.
"""

from __future__ import annotations

from pathlib import Path

from starlette.datastructures import URL, Headers
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

# What a page from this origin may load and do. Everything comes from the
# origin itself: no inline scripts, no third parties, and no framing by others.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
    ]
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    # Browsers must not guess a content type other than the one declared.
    "X-Content-Type-Options": "nosniff",
    # Links to other sites say nothing about the page they were followed from.
    "Referrer-Policy": "no-referrer",
}


# For a year the browser goes straight to HTTPS without asking over HTTP first.
STRICT_TRANSPORT_SECURITY = "max-age=31536000"


def _arrived_over(headers: Headers) -> str | None:
    """How the visitor reached the proxy in front: "http", "https", or None without one.

    TLS ends at that proxy, so this process only ever sees plain HTTP and has
    to be told. A request without the header did not come through the proxy:
    it is a health check from inside.
    """
    stated = headers.get("x-forwarded-proto")
    if stated is None:
        return None
    # In a list, the first entry is the hop the visitor made.
    return stated.split(",", 1)[0].strip().lower()


class HttpsRedirect:
    """Sends a visitor who came over plain HTTP to the same address over HTTPS.

    Used when the public address is an HTTPS one. Without it the page loads
    over HTTP and then fails where it matters: the session cookie is marked
    Secure, so signing in appears to do nothing.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _arrived_over(Headers(scope=scope)) == "http":
            # 308 keeps the method and the body, so a POST is repeated as a POST.
            redirect = RedirectResponse(URL(scope=scope).replace(scheme="https"), status_code=308)
            await redirect(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if _arrived_over(request.headers) == "https":
            response.headers.setdefault("Strict-Transport-Security", STRICT_TRANSPORT_SECURITY)
        # The interactive API documentation loads its scripts from a CDN and
        # would be blocked by the policy. It is a developer tool, left as it is.
        if request.url.path not in {"/docs", "/redoc"}:
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
        return response


class WebApp(StaticFiles):
    """The built single-page app.

    A path that is not a file is a page inside the app (``/panel/students``),
    so it is answered with ``index.html`` and the app's own router takes over.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Starlette hands the path over with the separators of the operating system.
        path = path.replace("\\", "/")
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or not _is_a_page(path):
                raise
            response = await super().get_response("index.html", scope)
        if path.startswith("assets/"):
            # Vite puts a hash of the content in these names, so a name never
            # changes meaning and can be cached for good.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            # index.html names the current assets and must always be fresh.
            response.headers["Cache-Control"] = "no-cache"
        return response


# What a browser asks a web server for besides pages. A missing one of these
# is missing: answering a request for a script with HTML would only hide it.
_FILE_SUFFIXES = (
    ".js", ".css", ".map", ".json", ".txt", ".xml", ".ico", ".png", ".jpg", ".svg",
    ".webp", ".woff", ".woff2", ".webmanifest",
)  # fmt: skip
# Paths that belong to the API. An unknown one is an error, not a page.
_NOT_PAGES = ("api/", "health", "docs", "openapi.json", "redoc", "assets/")


def _is_a_page(path: str) -> bool:
    """Whether a path with no file behind it is a page of the app.

    Not decided by "has a dot in it": the address of a student's account ends
    in their e-mail address.
    """
    return not path.startswith(_NOT_PAGES) and not path.lower().endswith(_FILE_SUFFIXES)
