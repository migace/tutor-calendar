# ADR 0007: An append-only ledger, and e-mail through an outbox

Status: accepted · 2026-11-15

## Context

Two things were missing that have the same shape: something has to happen
because something else happened, and it must happen exactly as many times as it
should.

- **Money.** Tutors sell lesson time in advance. Each lesson that is charged
  (ADR 0006) must come off the student's balance once: not zero times, not
  twice, and in a way a parent can check a month later.
- **E-mail.** A booking should produce a confirmation, and a lesson a reminder.
  Sending from inside the request ties the request to a mail server: if the
  server is slow the visitor waits, and if it fails after the booking is stored
  there is a booking nobody was told about. Sending before storing risks the
  opposite.

Both are a write to the database that has to be followed by something else.
The database can make the first part reliable. The rest has to be built so that
doing it again is harmless.

## Decision

### 1. The balance is not stored. It is the sum of a ledger.

`ledger_entries` holds one row for each thing that changed an account: time
bought, a lesson charged, a correction. Time is counted in whole minutes,
because lesson lengths differ and "ten lessons" stops meaning anything the day
a tutor changes theirs. An account is a tutor and a student's address.

Entries are never changed or removed. A mistake is put right by adding an entry
that says so. The statement a parent saw last month is therefore the statement
they see today, with one more line.

This is enforced by the database, not by convention: a trigger rejects every
`UPDATE` and `DELETE` of a row. Application code has no way to do either. The
owner of the database can still empty the table with `TRUNCATE` or drop the
trigger, which is what the tests do to clean up; the guarantee is against code
and accidents, not against whoever administers the server.

### 2. A lesson is charged at most once, by a constraint

A charge names its lesson, and `booking_id` is unique. The id of a charge is
also derived from the lesson's id. Whatever tries to charge a lesson a second
time, and however, the insert is a no-op.

That is what lets the job that charges lessons be simple. It looks for lessons
whose cost has become final (the lesson is over, or was missed, or was cancelled
late), posts their charges, and then marks them as settled. If it stops halfway,
or two workers pick up the same lessons, running it again finishes the work and
the constraint discards the repeats.

Entries the tutor records by hand are made safe to repeat the same way as
bookings and series: the client chooses the id.

### 3. Statements are cut by when an entry takes effect

A statement is a calendar month on the tutor's calendar: the balance before it,
the entries in it, the balance after. A lesson is placed by when it started, not
by when the charge was recorded, so a lesson held on 30 November is on
November's statement even if the worker was down until December.

A parent reads statements through a signed link, the same construction as the
link for managing a booking (ADR 0006) but signed for a different purpose, so
neither kind of token opens the other.

### 4. E-mail is queued in the same transaction as its cause, and sent by a worker

A booking and its confirmation are inserted together: the `outbox` row is
written in the transaction that writes the booking. There is no booking without
a confirmation queued, and no confirmation for a booking that was rolled back.
Requests never talk to a mail server.

A worker takes waiting messages with `SELECT ... FOR UPDATE SKIP LOCKED`, sends
each one, and marks it sent. Two workers never hold the same message, and one
does not wait for the other. A message that fails stays queued, with the error
recorded, and is tried again after a pause that doubles up to an hour.

Reminders use the same compare-and-set as lesson changes: the worker that
manages to set `reminded_at` is the one that queues the message.

### 5. Delivery is at least once

If a worker dies after the mail server accepted a message and before the
database recorded it, the message is sent again. That is deliberate. The
alternative, recording first, loses mail instead, and a second copy of a
reminder is the cheaper failure. Exactly-once delivery to a system that cannot
take part in the transaction does not exist; what exists is choosing which way
to fail.

## How this is verified

- A property-based test cuts random account histories into consecutive periods
  and checks that each statement ends where the next begins and that together
  they account for every entry once.
- The contracts for the ledger and the outbox run against PostgreSQL and the
  in-memory fakes: twelve workers charging the same lesson charge it once; four
  workers delivering six messages send each once; a failed message is retried
  after its pause and does not hold up the others; of ten rivals for one slot
  only the winner gets a confirmation. The outbox contract found a real fault
  in the fake, which sent every message once per worker.
- Against a real database, `UPDATE` and `DELETE` on a ledger entry are refused
  by the trigger, and entries that make no sense by `CHECK` constraints.
- The worker is run end to end with a clock the test moves: confirmation, then a
  reminder a day ahead, then one charge after the lesson, and nothing on a
  further run. Five workers started at once do each piece of work once.
- The SMTP adapter sends to a mail server started inside the test and the
  message, non-ASCII included, is read back from it.
- Mutations tried by hand, each caught: taking messages without the row lock,
  queueing a confirmation for a booking that was not stored, queueing a reminder
  without the check, charging a lesson that is still running, and retrying a
  failed message with no pause.

## Alternatives considered

- **A balance column, updated in place.** One number, no history, and every
  concurrent update a chance to lose one. Nothing to show a parent who asks why.
- **Computing charges from lessons on read, with no entries for them.** No job
  to run, but the ledger would no longer be the whole truth, and a later change
  to how lessons are priced would silently rewrite old statements.
- **A message broker.** The right tool at a scale this project does not have.
  It would not remove the problem either: a broker cannot join the database
  transaction, so the outbox would still be needed to feed it.
- **Sending mail in a background task of the web process.** Lost when the
  process restarts, and invisible when it fails.
- **Exactly-once delivery.** See above.

## Consequences

- There is a second process to run. Without the worker, bookings still work,
  but nothing is charged and no mail goes out. `docker compose up` starts it.
- Charges appear with a delay of up to one worker interval.
- A tutor cannot delete a wrong entry, only correct it. That is the point, and
  the form says so before the entry is recorded.
- Sent messages stay in the outbox table. Clearing old ones is not built yet.
- The worker and the API must share `TC_SECRET_KEY`, or the links in reminders
  could not be opened. Without a key the worker sends no reminders and says so.
