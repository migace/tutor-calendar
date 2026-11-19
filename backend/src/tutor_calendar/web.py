"""The web process: the API and the built web app, with logs as JSON lines.

    python -m tutor_calendar.web

This is what the image runs. Development starts uvicorn directly, with
``--reload``, and keeps uvicorn's own output.
"""

from __future__ import annotations

import os

import uvicorn

from tutor_calendar.config import Settings
from tutor_calendar.logs import logging_config


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "tutor_calendar.api.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        # Handed to uvicorn so that it is applied in every process it starts.
        log_config=logging_config("web", settings.log_format),
        # The application writes its own line per request, with the request's
        # id and without the query string. See ADR 0011.
        access_log=False,
    )


if __name__ == "__main__":
    main()
