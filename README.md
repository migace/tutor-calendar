# Tutor Calendar

A booking calendar for independent tutors: fixed weekly lessons, prepaid
packages of hours, a monthly statement for the parent, and a cancellation
policy that is enforced rather than argued about.

General-purpose booking tools handle one-off appointments well. A tutor's week
looks different: the same students at the same times, paid for in blocks, with
"can we move Thursday?" as the most common request. This project is built
around that workflow.

> **Status: week 4 of 6.** A visitor can book a lesson and cancel it with a
> link. A tutor can sign in, see their week, change their hours, cancel lessons
> and set up weekly lessons for regular students. Packages of hours are next,
> and e-mail is still written to the log instead of being sent. See the
> [roadmap](#roadmap).

## What is interesting here

**A slot cannot be booked twice, and a test tries hard to do it.** The naive
"check that the time is free, then insert" passes every ordinary test and fails
in production: with the protection removed, 22 to 24 of 25 simultaneous
requests for one slot got through. Here the database refuses overlapping
bookings with an exclusion constraint, and a test fires 25 requests at one slot
through the whole stack and expects exactly one `201`. A longer stress test
then turned up a deadlock that the first version mishandled.
[ADR 0003](docs/adr/0003-no-double-booking.md) tells that story.

**A lost response does not cost anyone their lesson.** Booking requests carry
an idempotency key, so a retry after a timeout returns the booking the first
attempt made. The page relies on that to retry failed requests on its own.
[ADR 0004](docs/adr/0004-idempotent-booking-requests.md) covers the design and
its one known gap.

**Weekly lessons are just lessons.** "Tuesdays at 17:00 for ten weeks" is laid
out into ordinary bookings when it is created, so the constraint that prevents
double booking, the slot list and cancellation all cover a series without a
second code path. A cancelled lesson gives its time back, whether it is charged
depends on the tutor's policy, and a student and a tutor cancelling the same
lesson at once cannot both win.
[ADR 0006](docs/adr/0006-lesson-states-cancellation-and-series.md) weighs this
against expanding series on read.

**Sign-in without passwords, and without the usual holes.** Tutors sign in with
a single-use link. Tokens are stored only as digests, the link's token never
reaches a server log, the session cookie cannot be read by scripts, and asking
for a link does not reveal who has an account. A link opened in twelve browsers
at once signs in exactly one. [ADR 0005](docs/adr/0005-sign-in-by-email-link.md)
goes through each choice and what is still missing.

**Fakes that cannot drift from the real thing.** Fast tests run against
in-memory repositories. Each port has one set of contract tests that runs
against both the fake and PostgreSQL, so the fake cannot quietly become more
forgiving than the database. See [`tests/contract`](backend/tests/contract).

**Time is modelled, not formatted.** A recurring rule ("Tuesdays 17:00-19:00")
is a wall-clock fact in the tutor's zone; a lesson is a UTC instant. The slot
generator converts between the two and has an explicit policy for the two
nights a year when a local time does not exist or happens twice.
[ADR 0002](docs/adr/0002-time-model.md) explains the policy.

**The tests go looking for trouble.** Besides hand-written cases for each DST
rule, property-based tests generate random schedules in every IANA time zone
and assert that slots never overlap, last exactly one lesson and stay on the
tutor's grid. Random dates almost never land on a clock change, so the
generators are biased towards them; removing any of the three DST safeguards in
the code makes the suite fail.
See [`test_slots_properties.py`](backend/tests/unit/test_slots_properties.py).

**The architecture is enforced by a test.** The domain is plain Python with no
framework imports, use cases depend on ports, and
[`test_architecture.py`](backend/tests/unit/test_architecture.py) fails the
build if an inner layer imports an outer one.
[ADR 0001](docs/adr/0001-hexagonal-modular-monolith.md) has the reasoning.

**One API contract, checked at compile time.** The frontend's types are
generated from the backend's OpenAPI document, and CI fails if the committed
contract is out of date.

## Stack

| | |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 17 |
| Frontend | React 19, TypeScript, Vite, TanStack Query |
| Tests | pytest, Hypothesis, Vitest, Testing Library |
| Tooling | uv, pnpm, Ruff, mypy (strict), ESLint, GitHub Actions |

## Run it

You need [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/) and, for
the database, Docker.

```bash
docker compose up -d db
```

```bash
cd backend && uv sync && uv run alembic upgrade head && uv run python -m tutor_calendar.demo && uv run uvicorn tutor_calendar.api.main:app --reload
```

```bash
cd frontend && pnpm install && pnpm dev
```

Open <http://localhost:5173> for the demo tutor's booking page. The API
documents itself at <http://localhost:8000/docs>.

To see the tutor panel, go to <http://localhost:5173/panel> and ask for a
sign-in link for `demo@example.com`. E-mail is not sent yet: the message, with
its link, appears in the output of the API.

Links for managing a booking are signed with `TC_SECRET_KEY`. Without it the
API makes up a key at start and says so, and those links stop working when it
restarts. See `backend/.env.example`.

The second command migrates the database and stores a demo tutor, whose
booking page is the one the frontend opens.

To run the API and the database in containers instead, with the same
migration and demo tutor:

```bash
docker compose up --build
```

## Test it

```bash
cd backend && uv run pytest
```

```bash
cd frontend && pnpm test
```

Tests marked `integration` need the database from `docker compose up -d db`.
They create and migrate a database of their own, `tutor_calendar_test`, and
leave development data alone. Without PostgreSQL they are skipped locally and
fail in CI.

After changing the API, regenerate the contract and the frontend types:

```bash
cd backend && uv run python -m tutor_calendar.api.export_openapi ../frontend/openapi.json && cd ../frontend && pnpm gen:api
```

## Layout

```
backend/src/tutor_calendar/
  domain/        rules and value objects; imports nothing but the standard library
  application/   use cases and the ports they need
  adapters/      implementations of ports: PostgreSQL, in-memory fakes, clock
  api/           FastAPI routes, schemas and the composition root
backend/tests/
  unit/          domain, use cases, the architecture rule
  contract/      what a repository must do, run against PostgreSQL and the fake
  api/           HTTP behaviour, with fakes behind it
  integration/   the schema and concurrent bookings, against PostgreSQL
frontend/src/
  api/           generated types and a thin client
  ui/            components that know nothing about tutors: Button, TextField, Notice
  features/      booking, auth and panel: one folder per user-facing feature
docs/adr/        architecture decision records
```

## Roadmap

1. **Scheduling core and walking skeleton** - done.
2. **Booking a single lesson**: exclusion constraint against double booking, a
   concurrency test, idempotent requests, the public booking flow - done.
3. **Tutor panel**: sign-in by e-mail link, week view, editing availability, the
   start of a component library - done.
4. **Recurring lessons** with exceptions, the lesson state machine, cancellation
   policy - done.
5. Packages of hours as an append-only ledger, the parent's statement,
   reminders through a transactional outbox.
6. Accessibility audit, demo data, load-test numbers, a hosted demo.

Deliberately out of scope for now: online payments, Google Calendar sync, SMS,
schools with several teachers, a native mobile app.
