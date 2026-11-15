# ADR 0003: The database refuses a double booking

Status: accepted · 2026-11-15

## Context

The one promise a booking calendar must never break: two students do not get
the same hour with the same tutor.

The obvious implementation breaks it. "Read the tutor's bookings, see that the
time is free, insert" is correct when requests arrive one after another, and
every ordinary test of it passes. When two requests arrive together, both read
before either has written, both see a free hour, and both insert. Measured
against this project's database with the protection removed: of 25 simultaneous
requests for one slot that each checked first, 22 to 24 were stored.

The rule is also not "one booking per start time". A tutor can change the
lesson length, so a 15:00-16:00 lesson has to block a later request for
15:30-16:15. The rule is about overlapping ranges.

## Decision

1. **An exclusion constraint on `bookings` makes overlap impossible.**

   ```sql
   CONSTRAINT bookings_no_overlap
       EXCLUDE USING gist (tutor_id WITH =, during WITH &&)
   ```

   `during` is a `tstzrange`, half-open `[start, end)` like `TimeRange` in the
   domain, so back-to-back lessons do not overlap. PostgreSQL enforces this for
   every writer: any number of requests, processes or servers, and anyone with
   a SQL prompt.

2. **The application does not check first.** `BookLesson` validates the request
   against the schedule and hands the booking to the repository. Whether the
   time is free is answered only by the insert. A check before the write would
   be a second, weaker copy of the rule and an extra query.

3. **Writers for one tutor queue on the tutor's row** (`SELECT ... FOR NO KEY
   UPDATE`) inside the transaction that inserts. This is not what prevents the
   double booking. It is there for the reason described next.

## What a stress test found

The first version had only the constraint, and passed a test that fires 25
requests at one slot. A longer test, repeating that in a loop with retries
mixed in, failed on the first or second round with `deadlock detected`.

That is documented PostgreSQL behaviour. An exclusion constraint is checked
after the row is inserted, so two conflicting inserts running at the same
moment can each find the other's unfinished row and wait for the other to
finish. The deadlock detector breaks the tie by aborting one of them a second
later. No double booking results, since one of the two had to fail anyway, but
the loser waits a second and gets a database error where a plain "that time is
taken" was due.

With the queue, the second writer waits milliseconds for the first to commit
and then meets a finished row, which produces an immediate, ordinary
constraint violation. The cost is that bookings for one tutor are written one
at a time. A write takes a few milliseconds and the calendar belongs to one
person, so there is nothing to gain from more.

## How this is verified

- `tests/contract/test_booking_repository.py` states what any booking
  repository must do, including the five ways two ranges can overlap, and runs
  the same tests against PostgreSQL and against the in-memory fake used by the
  fast tests. The fake cannot quietly become more permissive than the database.
- `tests/integration/test_concurrent_bookings.py` goes through the whole stack:
  25 simultaneous HTTP requests for one slot end as exactly one `201` and 24
  `409`, and the table holds one row.
- The stress test from the previous section is kept, at 8 rounds of 25 writes.
- Removing the constraint was tried as a mutation: 11 tests fail. Removing the
  queue: the stress test fails.

## Alternatives considered

- **Check, then insert.** Wrong under concurrency, as measured above.
- **`UNIQUE (tutor_id, start)`.** Simple, but only stops identical start times,
  not overlaps.
- **Only the per-tutor lock, with the check done in application code.** Correct
  as long as every writer remembers to take the lock. The constraint does not
  depend on anyone remembering.
- **`SERIALIZABLE` transactions.** Would catch the race, but as serialization
  failures that every caller has to retry, and it protects only code paths that
  run at that isolation level.
- **An advisory lock instead of a row lock.** Equivalent here. The row lock
  needs no mapping from tutor ids to lock numbers and will also order future
  changes to the tutor's own settings.

## Consequences

- The project requires PostgreSQL. Range types, GiST and exclusion constraints
  are not portable, and that is accepted.
- The real guarantee can only be tested against a real database, so those tests
  need PostgreSQL running. Locally they are skipped without one; in CI they
  must run.
- Cancelling a lesson has to free its time. ADR 0006 makes the constraint
  partial for that: `WHERE (status <> 'cancelled')`.
