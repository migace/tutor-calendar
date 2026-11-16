"""A small load test for the booking API.

    uv run python scripts/load_test.py                 run against http://127.0.0.1:8000
    uv run python scripts/load_test.py --cleanup       remove what an earlier run left behind

It creates a tutor with a very full timetable, then measures three things:

* browse   - visitors listing free slots, for an ordinary tutor and for an
             absurdly busy one, before and after hundreds of bookings
* book     - visitors booking different slots at the same time
* contend  - many visitors going for the very same slot

After each write scenario it asks the database what was actually stored, so a
fast run that double-booked would be reported as a failure, not as a result.

The numbers describe one machine on one day. They are useful for comparing two
versions of the code on the same machine, and for nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass
from datetime import time as wall_time
from datetime import timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.config import Settings
from tutor_calendar.domain.scheduling import Schedule, Tutor, Weekday, WeeklyRule

SLUG = "load-test"
TUTOR_ID = UUID("7d5c1f4e-0000-4000-8000-00000000beef")
ORDINARY_SLUG = "load-test-ordinary"
ORDINARY_ID = UUID("7d5c1f4e-0000-4000-8000-00000000cafe")
MAIL_DOMAIN = "loadtest.example.com"


def busy_tutor() -> Tutor:
    """06:00 to 22:00 every day in 15-minute lessons: 64 slots a day."""
    return Tutor(
        id=TUTOR_ID,
        slug=SLUG,
        display_name="Load Test",
        email=f"tutor@{MAIL_DOMAIN}",
        schedule=Schedule(
            timezone=ZoneInfo("Europe/Warsaw"),
            lesson_duration=timedelta(minutes=15),
            rules=tuple(WeeklyRule(day, wall_time(6, 0), wall_time(22, 0)) for day in Weekday),
        ),
        min_notice=timedelta(hours=1),
    )


def ordinary_tutor() -> Tutor:
    """Four hour-long lessons on four afternoons and a Saturday morning, like the demo."""
    afternoons = [Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY]
    return Tutor(
        id=ORDINARY_ID,
        slug=ORDINARY_SLUG,
        display_name="Load Test (ordinary)",
        email=f"ordinary@{MAIL_DOMAIN}",
        schedule=Schedule(
            timezone=ZoneInfo("Europe/Warsaw"),
            lesson_duration=timedelta(minutes=60),
            rules=(
                *(WeeklyRule(day, wall_time(15, 0), wall_time(19, 0)) for day in afternoons),
                WeeklyRule(Weekday.SATURDAY, wall_time(9, 0), wall_time(13, 0)),
            ),
        ),
    )


@dataclass
class Result:
    name: str
    requests: int
    concurrency: int
    seconds: float
    latencies_ms: list[float]
    statuses: dict[int, int]
    check: str

    def row(self) -> str:
        cuts = statistics.quantiles(self.latencies_ms, n=100)
        codes = ", ".join(f"{count} x {status}" for status, count in sorted(self.statuses.items()))
        return (
            f"| {self.name} | {self.requests} | {self.concurrency} "
            f"| {self.requests / self.seconds:.0f} "
            f"| {statistics.median(self.latencies_ms):.0f} | {cuts[94]:.0f} | {cuts[98]:.0f} "
            f"| {codes} | {self.check} |"
        )


async def run(
    name: str,
    client: httpx2.AsyncClient,
    requests: list[httpx2.Request],
    concurrency: int,
    check: str = "",
) -> Result:
    gate = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: dict[int, int] = {}

    async def one(request: httpx2.Request) -> None:
        async with gate:
            started = time.perf_counter()
            response = await client.send(request)
            latencies.append((time.perf_counter() - started) * 1000)
            statuses[response.status_code] = statuses.get(response.status_code, 0) + 1

    started = time.perf_counter()
    await asyncio.gather(*(one(request) for request in requests))
    return Result(
        name, len(requests), concurrency, time.perf_counter() - started, latencies, statuses, check
    )


def booking(client: httpx2.AsyncClient, start: str, n: int) -> httpx2.Request:
    return client.build_request(
        "POST",
        f"/api/v1/tutors/{SLUG}/bookings",
        json={
            "start": start,
            "student_name": f"Student {n}",
            "student_email": f"student{n}@{MAIL_DOMAIN}",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )


async def stored(engine: AsyncEngine) -> tuple[int, int]:
    """How many lessons the tutor has, and how many pairs of them overlap."""
    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM bookings WHERE tutor_id = :id"), {"id": TUTOR_ID}
        )
        overlapping = await connection.scalar(
            text(
                "SELECT count(*) FROM bookings a JOIN bookings b"
                " ON a.id < b.id AND a.tutor_id = b.tutor_id AND a.during && b.during"
                " WHERE a.tutor_id = :id"
            ),
            {"id": TUTOR_ID},
        )
    return int(count or 0), int(overlapping or 0)


async def cleanup(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM outbox WHERE recipient LIKE :domain"), {"domain": f"%@{MAIL_DOMAIN}"}
        )
        await connection.execute(
            text("DELETE FROM bookings WHERE tutor_id = :id"), {"id": TUTOR_ID}
        )
        await connection.execute(
            text("DELETE FROM tutors WHERE id IN (:busy, :ordinary)"),
            {"busy": TUTOR_ID, "ordinary": ORDINARY_ID},
        )


async def main(base_url: str, only_cleanup: bool) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        await cleanup(engine)
        if only_cleanup:
            print("Removed the load-test tutor and everything booked with them.")
            return
        tutors = PostgresTutorRepository(engine)
        await tutors.add_if_absent(busy_tutor())
        await tutors.add_if_absent(ordinary_tutor())

        limits = httpx2.Limits(max_connections=200)
        async with httpx2.AsyncClient(base_url=base_url, limits=limits, timeout=60) as client:
            slots = (await client.get(f"/api/v1/tutors/{SLUG}/slots")).json()["slots"]
            starts = [slot["start"] for slot in slots]
            print(f"{len(starts)} free slots to work with.\n")

            ordinary = client.build_request("GET", f"/api/v1/tutors/{ORDINARY_SLUG}/slots")
            listing = client.build_request("GET", f"/api/v1/tutors/{SLUG}/slots")
            results = [
                await run("browse, ordinary tutor (40 slots)", client, [ordinary] * 1000, 50),
                await run(f"browse, {len(starts)} slots free", client, [listing] * 1000, 50),
            ]

            distinct = [booking(client, start, n) for n, start in enumerate(starts[:600])]
            book = await run("book", client, distinct, 50)
            count, overlapping = await stored(engine)
            book.check = f"{count} stored, {overlapping} overlapping"
            results.append(book)

            results.append(await run("browse, 600 of them booked", client, [listing] * 1000, 50))

            same = [booking(client, starts[700], n) for n in range(300)]
            contend = await run("contend", client, same, 100)
            after, overlapping = await stored(engine)
            contend.check = f"{after - count} stored, {overlapping} overlapping"
            results.append(contend)

        columns = ["scenario", "requests", "at once", "req/s", "p50 ms", "p95 ms", "p99 ms"]
        print(f"| {' | '.join([*columns, 'answers', 'stored'])} |")
        print("|---|---|---|---|---|---|---|---|---|")
        for result in results:
            print(result.row())

        failed = (
            book.statuses != {201: 600}
            or contend.statuses != {201: 1, 409: 299}
            or (after, overlapping) != (601, 0)
        )
        if failed:
            raise SystemExit(
                "\nFAILED: the answers or the stored lessons are not what they must be."
            )
        print("\nEvery booking was answered correctly and nothing overlaps.")
    finally:
        await cleanup(engine)
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cleanup", action="store_true", help="only remove earlier leftovers")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.base_url, arguments.cleanup))
