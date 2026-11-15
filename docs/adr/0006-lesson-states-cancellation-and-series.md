# ADR 0006: Lesson states, who pays for a cancellation, and weekly series

Status: accepted · 2026-11-15

## Context

Until now a booking could only exist. Real lessons get cancelled, students fail
to turn up, and most of a tutor's week is the same students at the same times.
Three questions needed answers that the rest of the system can rely on:

- What can happen to a lesson, and in what order?
- When a lesson is cancelled, is it still paid for?
- How is "every Tuesday at 17:00" represented?

The week after this one adds prepaid packages of hours, which will ask of each
lesson exactly one thing: is it charged?

## Decision

### 1. A lesson is in one of three states

```
confirmed ──cancel──▶ cancelled
    │
    └──mark no-show──▶ no-show
```

Nothing leaves `cancelled` or `no-show`. There is no "completed" state: a lesson
that took place is a confirmed lesson whose time has passed, and storing that
separately would only create a second fact that could disagree with the clock.

The transitions are methods on `Booking` that return a new value or raise.
A lesson can be cancelled only before it starts and marked as a no-show only
after. Two properties derive from the state and are all other code needs:
`occupies_time` (false only when cancelled) and `is_charged`.

Stored lessons change by compare-and-set: the `UPDATE` matches only while the
status is still the one that was read. A student and a tutor cancelling the
same lesson at the same moment cannot both succeed, and the one who loses is
told so instead of silently overwriting the other.

### 2. The tutor's cancellation policy is a strategy

Whether a cancellation is charged depends on the tutor. `CancellationPolicy`
has two implementations, chosen from one tutor setting:

- `FreeUntil(notice)`: free up to a fixed time before the lesson, charged after.
- `AlwaysFree`: never charged.

Under either, a lesson the tutor cancels is not charged. The lesson asks the
policy once, when it is cancelled, and stores the answer (`cancelled_late`).
Changing the policy later does not rewrite what was agreed for lessons already
cancelled.

A late cancellation is still a cancellation: the student is charged, but the
tutor gets the hour back and it can be booked again.

### 3. A cancelled lesson gives its time back

The exclusion constraint from ADR 0003 becomes partial:

```sql
EXCLUDE USING gist (tutor_id WITH =, during WITH &&) WHERE (status <> 'cancelled')
```

Cancelled lessons stay in the table, so the tutor can see what was called off
and the ledger can charge the late ones. A `CHECK` constraint ties the
cancellation details to the status, so a half-recorded cancellation cannot be
stored by any writer.

### 4. A weekly series is stored as ordinary lessons

"Tuesdays at 17:00 for ten weeks" is a wall-clock fact, like an availability
rule (ADR 0002): each lesson is at 17:00 on the tutor's clock, whatever the
clocks did in between. When a series is created it is laid out into concrete
lessons, each stored as a normal booking that points at its series.

This is the decision with the largest consequences. Every protection a single
booking has, a series lesson has too, with no second code path: the exclusion
constraint, the slot listing, the week view, cancellation. An "exception" to a
series is simply one of its lessons being cancelled.

If some lessons would overlap existing ones, nothing is stored and the tutor is
told which days clash. They can then book the remaining weeks. The check and the
inserts happen in one transaction behind the tutor's row lock, so the answer
cannot go stale in between.

The client chooses the series id (`PUT /me/series/{id}`), and each lesson's id
is derived from the series id and its day. Repeating the request therefore
returns the series as first created and can never add a lesson twice.

### 5. Students manage a booking with a signed link, not an account

The booking response carries a manage token: the booking id plus an HMAC of it
under a server secret. Whoever holds it can view and cancel that one booking.
Nothing is stored. Because the token is computed, a repeated booking request
(ADR 0004) gets the same link the first attempt got. The token is sent as a
bearer credential and, in the page address, kept in the fragment.

This closes the gap noted in ADR 0004 only in part: a visitor who has the
confirmation can now cancel, but one whose response was lost still has no link.

## How this is verified

- A property-based test fires random sequences of cancel and no-show requests
  at a lesson and checks that it changes state at most once, and that a refused
  request leaves it untouched.
- Another lays out series in every time zone and checks that each lesson starts
  at the planned time on the tutor's clock and that none overlap.
- The repository contract (PostgreSQL and the in-memory fake) covers
  compare-and-set, twelve simultaneous changes to one lesson of which one wins,
  a series clash storing nothing, and a series racing single bookings for the
  same six slots with every slot ending up taken exactly once.
- Through HTTP and a real database: a student and a tutor cancelling one lesson
  twelve times at once produce one `200` and eleven `409`.
- Mutations tried by hand, each caught: applying a change without the status
  check, a tutor's late cancellation being charged, a manage token accepted
  without its signature, cancelled lessons counted as busy for a series.

## Alternatives considered

- **Expanding series on read** from a stored rule. No rows to create, and an
  open-ended series is natural. But every reader has to merge rules with
  bookings and exceptions, the exclusion constraint cannot see a lesson that
  exists only as a rule, and "is this slot free" stops being one query. The
  hard guarantee of this project would hold for one kind of lesson only.
- **A "completed" state set by a scheduled job.** It adds a moving part whose
  only output is something the clock already says.
- **A state-machine library or a transition table.** Three states and two
  arrows fit in two methods that can be read at a glance.
- **Deleting cancelled lessons.** Simpler constraint, but the history and the
  late-cancellation charge would be gone.
- **Accounts for students.** A parent booking one lesson should not have to
  create one. A signed link gives exactly the access that is needed.

## Consequences

- A series has an end: at most 52 lessons. "Until further notice" means
  extending it, which is not built yet.
- Creating a series writes one row per lesson. At 52 rows that is nothing.
- Changing the time of a series means ending it and starting another.
- Anyone who obtains a manage link can cancel that lesson. It is a capability,
  and is treated like one: never logged, never in a query string.
- `TC_SECRET_KEY` must be set in any real deployment. Without it the
  application signs with a random key and says so in its log, and links stop
  working when it restarts.
