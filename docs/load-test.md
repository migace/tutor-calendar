# Load test

`backend/scripts/load_test.py` creates two tutors, fires requests at the running
API, and then asks the database what was actually stored. A run that was fast
but double-booked a slot is reported as a failure, not as a result.

```bash
cd backend && uv run python scripts/load_test.py
```

## What the numbers are, and are not

They were measured once, on 16 November 2026, on a Windows laptop running the
API and PostgreSQL in Docker Desktop, with the client on the host. Requests go
through Docker's port forwarding, and every query crosses a virtual network.

They are useful for comparing two versions of the code on the same machine.
They say nothing reliable about a real server, and should not be quoted as the
capacity of the application.

## Results

One API process, which is how `docker compose up` runs it:

| scenario | requests | at once | req/s | p50 ms | p95 ms | p99 ms | answers | stored |
|---|---|---|---|---|---|---|---|---|
| browse, ordinary tutor (40 slots) | 1000 | 50 | 148 | 288 | 744 | 987 | 1000 x 200 | |
| browse, 895 slots free | 1000 | 50 | 55 | 679 | 2021 | 3098 | 1000 x 200 | |
| book 600 different slots | 600 | 50 | 104 | 458 | 707 | 792 | 600 x 201 | 600 stored, 0 overlapping |
| browse, 600 of them booked | 1000 | 50 | 49 | 921 | 2098 | 2622 | 1000 x 200 | |
| contend for one slot | 300 | 100 | 105 | 822 | 1510 | 2068 | 1 x 201, 299 x 409 | 1 stored, 0 overlapping |

Four API processes (`WEB_CONCURRENCY=4`), same database:

| scenario | requests | at once | req/s | p50 ms | p95 ms | p99 ms | answers | stored |
|---|---|---|---|---|---|---|---|---|
| browse, ordinary tutor (40 slots) | 1000 | 50 | 289 | 108 | 535 | 781 | 1000 x 200 | |
| browse, 895 slots free | 1000 | 50 | 109 | 181 | 1399 | 1994 | 1000 x 200 | |
| book 600 different slots | 600 | 50 | 126 | 399 | 737 | 941 | 600 x 201 | 600 stored, 0 overlapping |
| browse, 600 of them booked | 1000 | 50 | 96 | 290 | 1577 | 2236 | 1000 x 200 | |
| contend for one slot | 300 | 100 | 197 | 426 | 826 | 1013 | 1 x 201, 299 x 409 | 1 stored, 0 overlapping |

The "895 slots" tutor is deliberately absurd: lessons of 15 minutes from 06:00
to 22:00 every day. A real tutor offers a few dozen slots in two weeks.

## What the test showed

**The guarantees hold under load.** In every run, each of 600 simultaneous
bookings for different slots was stored once, and of 300 requests for one slot
exactly one was accepted. The database held no overlapping lessons afterwards.

**Reading scales with processes; booking with one tutor does not, by design.**
Four processes roughly doubled the rate of listing. Bookings for a single tutor
barely moved, because writers for one tutor queue on that tutor's row
(ADR 0003). The limit is per tutor, so many tutors booking at once would spread
across processes; this test did not measure that.

**It found a slow path, which was then fixed.** Listing slots compared every
slot with every booked lesson. Measured without HTTP, generating two weeks of
896 slots took 5 ms with an empty calendar and 29 ms with 300 lessons booked.
The comparison was replaced with a single pass over both lists, which brought
the second figure down to 5 ms. A property-based test holds the faster version
to the plain definition (a slot is offered unless some busy range overlaps it)
for busy ranges of any length that may overlap each other, and two deliberate
mistakes in the new code were both caught by the tests.

**What limits listing now is not the algorithm.** Each request loads the tutor
with three queries and the bookings with a fourth, and the response for 895
slots is large. For an ordinary tutor that is where the time goes. Caching the
tutor between requests would be the next step, and was not done because nothing
suggests it is needed.

## Not measured

- Many tutors at once, which is the realistic shape of load.
- The tutor panel, statements and the worker.
- Anything over a real network or on a real server.
- Behaviour over time: every run lasted seconds.
