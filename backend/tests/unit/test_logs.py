"""The shape of a log line. See ADR 0011."""

from __future__ import annotations

import json
import logging
import logging.config
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from tutor_calendar.api.observed import loggable_path
from tutor_calendar.logs import JsonFormatter, logging_config, request_id


def record(message: str, *args: object, **extra: Any) -> dict[str, Any]:
    """What one call to a logger comes out as."""
    made = logging.getLogger("tutor_calendar.test").makeRecord(
        "tutor_calendar.test", logging.INFO, __file__, 1, message, args, None, extra=extra
    )
    line = JsonFormatter("worker").format(made)
    assert "\n" not in line
    parsed: dict[str, Any] = json.loads(line)
    return parsed


def test_a_line_says_when_how_serious_who_and_what() -> None:
    line = record("round finished: %s", {"sent": 2}, sent=2, failed=0)

    moment = datetime.fromisoformat(line.pop("time"))
    assert moment.utcoffset() == timedelta(0)
    assert line == {
        "level": "info",
        "service": "worker",
        "logger": "tutor_calendar.test",
        "message": "round finished: {'sent': 2}",
        "sent": 2,
        "failed": 0,
    }


def test_a_line_carries_the_id_of_the_request_being_answered() -> None:
    assert "request_id" not in record("outside any request")

    token = request_id.set("3f1c8a526f6e4d0b9a441c2d3e4f5a6b")
    try:
        assert record("inside one")["request_id"] == "3f1c8a526f6e4d0b9a441c2d3e4f5a6b"
    finally:
        request_id.reset(token)


def test_an_error_is_one_line_with_its_traceback_inside() -> None:
    try:
        raise ValueError("first line\nsecond line")
    except ValueError:
        made = logging.getLogger("tutor_calendar.test").makeRecord(
            "tutor_calendar.test", logging.ERROR, __file__, 1, "it broke", (), sys.exc_info()
        )

    text = JsonFormatter("web").format(made)

    assert "\n" not in text
    line = json.loads(text)
    assert line["level"] == "error"
    assert line["error"].startswith("Traceback (most recent call last):")
    assert line["error"].endswith("ValueError: first line\nsecond line")


def test_a_value_that_is_not_json_is_written_as_text_and_never_raises() -> None:
    lesson = UUID("0b5c1f4e-6f0a-4c59-9a43-6d2f6f0c7d11")

    line = record(
        "charged", lesson=lesson, when=datetime(2026, 11, 17, 14, 0, tzinfo=UTC), thing=object
    )

    assert line["lesson"] == str(lesson)
    assert line["when"] == "2026-11-17 14:00:00+00:00"
    assert line["thing"] == "<class 'object'>"


def test_a_callers_field_cannot_replace_one_of_the_lines_own() -> None:
    line = record("hello", service="somebody-else", level="shouting", time="yesterday")

    assert (line["service"], line["level"], line["message"]) == ("worker", "info", "hello")
    assert line["time"] != "yesterday"


def test_uvicorns_coloured_copy_of_the_message_is_left_out() -> None:
    assert "color_message" not in record("Started server", color_message="\x1b[32mStarted\x1b[0m")


@pytest.mark.parametrize("log_format", ["json", "text"])
def test_the_configuration_is_one_python_accepts(log_format: Any) -> None:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        logging.config.dictConfig(logging_config("web", log_format))
        (handler,) = root.handlers
        assert isinstance(handler.formatter, JsonFormatter) == (log_format == "json")
        assert root.level == logging.INFO
    finally:
        # Put back what the test runner had, or it would stop seeing logs.
        root.handlers[:] = handlers
        root.setLevel(level)


@pytest.mark.parametrize(
    ("path", "written"),
    [
        ("/api/v1/tutors/demo/slots", "/api/v1/tutors/demo/slots"),
        (
            "/api/v1/me/students/31bf9ca7-80a8-4c59-b12f-b753c6eb10c5/statement",
            "/api/v1/me/students/31bf9ca7-80a8-4c59-b12f-b753c6eb10c5/statement",
        ),
        ("/panel/students/anna@example.com", "/panel/students/[address]"),
        ("/panel/students/Anna.Nowak+kid@Example.COM/x", "/panel/students/[address]/x"),
        ("/@", "/[address]"),
        ("/", "/"),
        ("/" + "a" * 400, "/" + "a" * 255 + "..."),
    ],
)
def test_a_path_is_logged_whole_except_for_an_address(path: str, written: str) -> None:
    assert loggable_path(path) == written
