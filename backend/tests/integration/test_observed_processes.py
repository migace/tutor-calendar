"""The processes as the image starts them: what they write, and what they report.

Everything else about logs and metrics is tested inside one Python process.
These tests start the real ones, because "every line is JSON" is a claim about
uvicorn's lines and Alembic's as much as about ours. See ADR 0011.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import BACKEND
from tests.factories import NOW, SECRET
from tutor_calendar.adapters.clock import FixedClock
from tutor_calendar.adapters.mail import InMemoryMailer
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.api.main import create_app
from tutor_calendar.config import Settings
from tutor_calendar.demo import demo_tutor
from tutor_calendar.worker import Worker

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

TOKEN = "a-metrics-token-used-only-by-the-tests-0123456789"
BEARER = {"Authorization": f"Bearer {TOKEN}"}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _environment(database_url: str, **more: str) -> dict[str, str]:
    return {
        **os.environ,
        "TC_DATABASE_URL": database_url,
        "TC_SECRET_KEY": SECRET,
        # Said outright: a developer's own choice of format must not decide what is tested.
        "TC_LOG_FORMAT": "json",
        **more,
    }


def _json_lines(output: str) -> list[dict[str, Any]]:
    """Every line of a process's output, each of which has to be one JSON object."""
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines, "the process wrote nothing"
    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            pytest.fail(f"not a JSON line: {line!r}")
    return parsed


def test_the_worker_and_the_migration_write_nothing_but_json_lines(database_url: str) -> None:
    for module, service in (("alembic", "migrate"), ("tutor_calendar.worker", "worker")):
        arguments = ["upgrade", "head"] if module == "alembic" else ["--once"]
        finished = subprocess.run(
            [sys.executable, "-m", module, *arguments],
            cwd=BACKEND,
            env=_environment(database_url),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert finished.returncode == 0, finished.stderr

        lines = _json_lines(finished.stdout + finished.stderr)

        assert {line["service"] for line in lines} == {service}
        assert all({"time", "level", "logger", "message"} <= set(line) for line in lines)


def test_the_web_process_writes_json_lines_and_one_per_request(database_url: str) -> None:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "tutor_calendar.web"],
        cwd=BACKEND,
        env=_environment(database_url, PORT=str(port)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"{base}/health/ready", timeout=2) as ready:
                    assert ready.status == 200
                break
            except (urllib.error.URLError, ConnectionError):
                assert process.poll() is None, "the web process stopped"
                assert time.monotonic() < deadline, "the web process never answered"
                time.sleep(0.2)
        # A WebSocket handshake, which uvicorn would otherwise answer and log
        # by itself, address and query string included.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as handshake:
            handshake.sendall(
                b"GET /ws?token=a-secret-in-a-handshake HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n"
                b"Sec-WebSocket-Version: 13\r\n"
                b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
            )
            assert handshake.recv(4096).startswith(b"HTTP/1.1 404")
        request = urllib.request.Request(f"{base}/api/v1/tutors/demo/slots?from=2026-11-16")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                given = response.headers["X-Request-ID"]
        except urllib.error.HTTPError as refusal:
            # No demo tutor in the test database is fine: it is the line we are after.
            given = refusal.headers["X-Request-ID"]
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=15)

    lines = _json_lines(output)
    assert {line["service"] for line in lines} == {"web"}
    # uvicorn's own lines came out in the same shape as ours.
    assert any(line["logger"].startswith("uvicorn") for line in lines)
    # Alembic is imported for the readiness check and would announce its plugins.
    assert not [line for line in lines if line["logger"].startswith("alembic")]
    # Our own line for each request that is not a health check, and uvicorn's
    # access log, which would have written the query string, is off.
    refused_handshake, request_line = (
        line for line in lines if line["logger"] == "tutor_calendar.access"
    )
    assert (refused_handshake["path"], refused_handshake["status"]) == ("/ws", 404)
    assert request_line["request_id"] == given
    assert request_line["path"] == "/api/v1/tutors/demo/slots"
    assert "2026-11-16" not in output
    assert "a-secret-in-a-handshake" not in output
    # Nor does any line name the address the requests came from.
    assert "127.0.0.1:" not in output.replace(f"127.0.0.1:{port}", "")


async def test_a_booking_and_the_worker_that_follows_it_show_in_the_metrics(
    engine: AsyncEngine, database_url: str
) -> None:
    await PostgresTutorRepository(engine).add_if_absent(demo_tutor())
    settings = Settings(database_url=database_url, secret_key=SECRET, metrics_token=TOKEN)

    def numbers(client: TestClient) -> dict[str, float]:
        page = client.get("/metrics", headers=BEARER)
        assert page.status_code == 200, page.text
        return {
            sample.name + "".join(f"|{value}" for value in sample.labels.values()): sample.value
            for family in text_string_to_metric_families(page.text)
            for sample in family.samples
            if "_bucket" not in sample.name and "process_" not in sample.name
        }

    def through_http() -> tuple[dict[str, float], dict[str, float]]:
        with TestClient(create_app(settings, clock=FixedClock(NOW))) as client:
            before = numbers(client)
            booked = client.post(
                "/api/v1/tutors/demo/bookings",
                json={
                    "start": "2026-11-17T14:00:00Z",
                    "student_name": "Anna Nowak",
                    "student_email": "anna@example.com",
                },
                headers={"Idempotency-Key": uuid4().hex},
            )
            assert booked.status_code == 201, booked.text
            return before, numbers(client)

    before, after = await asyncio.to_thread(through_http)

    assert before["tutor_calendar_database_up"] == 1
    assert before["tutor_calendar_booking_requests_total|booked"] == 0
    assert before["tutor_calendar_outbox_waiting_messages"] == 0
    assert after["tutor_calendar_booking_requests_total|booked"] == 1
    assert after["tutor_calendar_outbox_waiting_messages"] == 1
    assert "tutor_calendar_worker_last_success_timestamp_seconds|deliver" not in after

    # The worker comes round a minute later and sends the confirmation.
    a_minute_later = NOW.replace(minute=1)
    await Worker(settings, engine, FixedClock(a_minute_later), InMemoryMailer()).run_once()

    def afterwards() -> dict[str, float]:
        with TestClient(create_app(settings, clock=FixedClock(a_minute_later))) as client:
            return numbers(client)

    finally_ = await asyncio.to_thread(afterwards)
    assert finally_["tutor_calendar_outbox_waiting_messages"] == 0
    assert finally_["tutor_calendar_outbox_oldest_waiting_seconds"] == 0
    assert (
        finally_["tutor_calendar_worker_last_success_timestamp_seconds|deliver"]
        == a_minute_later.timestamp()
    )
