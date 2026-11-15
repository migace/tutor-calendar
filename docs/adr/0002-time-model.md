# ADR 0002: Wall-clock rules, UTC instants

Status: accepted · 2026-11-14

## Context

A tutor says "I teach on Tuesdays from 17:00 to 19:00". A parent in another
country books one of those lessons. Twice a year the tutor's clocks change.

Two different things are being described and they need different types:

- a **recurring rule** is about the tutor's wall clock. "17:00 on Tuesdays" must
  still be 17:00 after the clocks change, even though that is a different UTC
  hour;
- a **lesson** is a specific instant. It must mean the same moment to everyone
  and never overlap another lesson.

Storing rules as UTC offsets breaks the first (the lesson drifts by an hour in
summer). Storing lessons as local times breaks the second (one hour a year
happens twice, one never happens).

## Decision

1. **Rules are naive local times plus an IANA zone** (`WeeklyRule`, `Schedule`).
   Never a fixed offset.
2. **Slots and bookings are UTC instants** (`TimeRange`, half-open
   `[start, end)`). Naive datetimes are rejected at construction.
3. **Lesson length is real elapsed time.** A 60-minute lesson lasts 60 minutes
   on the night the clocks change.
4. Slots are laid out on the wall-clock grid of the rule and converted to
   instants. On a clock-change night:

   | Situation | Policy |
   |---|---|
   | The wall-clock start does not exist (spring forward) | The slot is skipped, not moved. |
   | The wall-clock start happens twice (fall back) | The first occurrence is offered; the repeated hour stays free. |
   | A lesson straddles the spring gap and would end after the rule's end on the wall clock | Rejected. |
   | A lesson straddles the spring gap and runs into the next grid position | The later position is dropped. |

5. The grid depends only on the schedule. The requested window and existing
   bookings filter it and never shift it.
6. The API speaks UTC and returns the tutor's zone alongside. The browser
   formats times in the visitor's zone and says which zone it used.

## How this is verified

- Example tests for each row of the table, using Europe/Warsaw in 2026
  (`tests/unit/test_slots_examples.py`).
- Property-based tests (Hypothesis) over random schedules in every IANA zone,
  with windows deliberately placed on offset changes
  (`tests/unit/test_slots_properties.py`). They assert that slots never
  overlap, last exactly one lesson, sit on the rule's grid inside the rule, and
  that a narrower window returns a subset of a wider one.
- The safeguards were checked by mutation: removing the overlap check, the
  rule-end check or the missing-time check each makes at least one test fail.
  Uniformly random windows did **not** catch these (clock changes are two
  nights in 365), which is why the strategies are biased towards them.

## Alternatives considered

- **Store everything in UTC, including rules.** Simple, and wrong for half the
  year.
- **Move a slot that starts in the gap to the first valid time.** Friendlier in
  theory, but it puts a lesson off the tutor's grid and can collide with the
  next slot. Skipping is predictable.
- **Offer both occurrences of the repeated hour.** They would show the same
  wall-clock time twice in the tutor's calendar. One free hour a year is the
  cheaper mistake.

## Consequences

- On a spring-forward night a tutor who works through the gap has fewer slots
  than usual; on a fall-back night one real hour is unused. Both are deliberate.
- A rule cannot cross midnight or end exactly at 24:00. A tutor who teaches
  past midnight needs two rules. Revisit if anyone asks.
- Changing a tutor's time zone changes the instants of all future slots.
  Existing bookings are instants and do not move; reconciling the two is a
  problem for the booking module, not this one.
