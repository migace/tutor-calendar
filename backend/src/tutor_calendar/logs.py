"""Logs as one JSON object per line, from every process. See ADR 0011.

A line says when, how serious, which process, which logger and what. A line
written while a request is being answered also carries that request's id, so
everything one request caused can be found with one search.

Only the outside of the application writes logs: the API, the worker and the
adapters. The use cases and the domain never import this module or
``logging``, and a test keeps it that way.
"""

from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

LogFormat = Literal["json", "text"]

# The id of the request being answered. Set by the API's outermost middleware
# and read here, so no caller has to pass it along.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# What every record has. Anything else on a record was put there by the caller
# with ``extra=`` and belongs in the line.
_BUILT_IN = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
    # uvicorn's copy of the message with terminal colours in it.
    "color_message",
}

_TEXT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        current = request_id.get()
        if current is not None:
            line["request_id"] = current
        for name, value in vars(record).items():
            if name not in _BUILT_IN:
                line.setdefault(name, value)
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        # A value that is not JSON is written as its text: a log call must never raise.
        return json.dumps(line, default=str)


def logging_config(service: str, log_format: LogFormat = "json") -> dict[str, Any]:
    """Everything to standard output, in one format, whichever library wrote it.

    A dictionary and not a function call, because uvicorn applies it again in
    every process it starts.
    """
    formatter: dict[str, Any]
    if log_format == "json":
        formatter = {"()": f"{__name__}.{JsonFormatter.__name__}", "service": service}
    else:
        formatter = {"format": _TEXT}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"line": formatter},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "line",
            }
        },
        "root": {"level": "INFO", "handlers": ["stdout"]},
        # Alembic announces each of its plugins whenever it is imported, which
        # the readiness check does in every web process.
        "loggers": {"alembic.runtime.plugins": {"level": "WARNING"}},
    }


def configure_logging(service: str, log_format: LogFormat = "json") -> None:
    logging.config.dictConfig(logging_config(service, log_format))
