# ADR 0004: Booking requests can be repeated safely

Status: accepted · 2026-11-15

## Context

A parent taps "Book lesson" on a train. The request reaches the server and the
booking is stored, but the response is lost in a tunnel. The page shows an
error. What happens when they tap again?

Without help, the second request is refused: the time is taken, by their own
first attempt. They are told the slot went to someone else while holding a
booking they do not know about. Automatic retries make the same thing happen
without anyone tapping twice.

A client cannot tell "the request never arrived" from "the answer never came
back", so it has to be able to ask again and get the same answer.

## Decision

1. **Every booking request carries an `Idempotency-Key` header**: a random
   value chosen by the client, 16 to 64 characters. The page uses a UUID.
2. **The key is stored on the booking it created**, under
   `UNIQUE (tutor_id, idempotency_key)`. The insert is
   `INSERT ... ON CONFLICT ON CONSTRAINT ... DO NOTHING`. Storing the booking
   and recording its key are therefore one statement: there is no moment at
   which one exists without the other.
3. **A repeat returns the original booking** with the same `201` and body, plus
   `Idempotency-Replayed: true`. The lookup by key happens before any other
   check, so a repeat still succeeds after the time has moved inside the
   tutor's notice period.
4. **The same key with a different request is an error** (`422`). A key
   identifies one request, defined as tutor, start time, student name and
   email. Answering a different question with an old booking would be a silent
   lie.
5. **Refusals are not remembered.** A request that ends in `409` stores
   nothing, so its key is still unused.

On the client, `useBookLesson` keeps one key per distinct request and reuses it
for every repeat. That is what allows it to retry network failures and `5xx`
responses automatically, twice, without risk.

## How this is verified

- The repository contract runs against PostgreSQL and the in-memory fake:
  a repeated key returns the first booking and stores nothing; a refused
  booking does not use up its key.
- Through HTTP and a real database: 25 simultaneous requests with one key all
  return `201` with the same id, 24 of them marked as replays, and one row is
  stored.
- In the browser tests, the three requests behind one click (failure, `503`,
  success) carry the same key, and changing the email produces a new one. Making
  the hook generate a fresh key per attempt was tried as a mutation: both tests
  fail.

## Alternatives considered

- **A separate table of keys with the stored response**, the general form of
  this pattern. It can replay any endpoint and any status, but needs a second
  write that must be made atomic with the first, plus expiry. One endpoint whose
  only replayable outcome is the booking itself does not need it. If more
  endpoints become idempotent, this is the direction to grow in.
- **Deduplicating on the natural key** (tutor, start, email) with no header.
  Cannot tell a retry from a genuinely new request with the same details, and
  the exclusion constraint already makes the second one fail.
- **Returning `200` for a replay.** A client would have to treat two success
  codes alike. The header carries the distinction for anyone who wants it.

## Consequences

- Keys are kept as long as the booking, so there is nothing to expire.
- A known gap: if the first attempt was stored, its response was lost, and the
  visitor then edits their details before retrying, the new request has a new
  key and is refused because the time is taken by their own earlier booking.
  Closing it needs the booking to be findable by the visitor, which arrives
  with sign-in by e-mail link.
- The endpoint is public and unauthenticated. Rate limiting is not part of this
  decision and is not implemented yet.
