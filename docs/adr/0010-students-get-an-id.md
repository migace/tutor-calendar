# ADR 0010: Students get an id of their own

Status: accepted · 2026-11-18

## Context

A student was their e-mail address and nothing else. Bookings name it, the
ledger files lesson time under it (ADR 0007), and so the address was also how
the panel and the API pointed at a student:

```
GET /api/v1/me/students/anna@example.com/statement
/panel/students/anna@example.com
```

An address of a page or a request is the one part of it that gets written
down by everyone it passes: the application's access log, the proxy in front
of it, the browser's history. ADR 0005 went to some length to keep sign-in
tokens out of exactly those places, and then the address of a child's parent
went into every one of them. It was found by reading the code, not by an
incident.

One thing about the panel shaped the answer. A tutor can type the address of
someone who has not booked anything yet and record a package for them, because
selling a package before the first lesson is common. So an id cannot be worked
out from lessons and entries that already exist: there may be none.

## Decision

1. **A `students` table pairs each address with a random id.**

   ```sql
   CREATE TABLE students (
       id uuid NOT NULL DEFAULT gen_random_uuid(),
       tutor_id uuid NOT NULL,
       account text NOT NULL,   -- the address in lower case, as in the ledger
       created_at timestamptz NOT NULL,
       CONSTRAINT students_account_unique UNIQUE (tutor_id, account)
   )
   ```

   The same address with another tutor is another student with another id.

2. **Addresses of pages and requests name a student only by that id.** The
   e-mail address is sent once, in the body of `POST /me/students`, which
   answers with the student it belongs to and adds them if the tutor has none.
   Everything after that uses the id.

3. **A student is enrolled where they first appear, in the same transaction.**
   Storing a booking or a weekly series enrols its student as part of the same
   change, and recording a ledger entry enrols the address first. So nobody has
   a lesson or an entry without an id. Two requests for a new address at the
   same moment are settled by the unique constraint, not by the code: both get
   the one student.

4. **Bookings and the ledger still name students by address.** The table is
   the one place that pairs an address with an id. Making bookings and entries
   refer to the id instead is the next step, and is left out on purpose: it is
   not needed to get addresses out of logs, and it is a much larger change to
   tables that hold the two guarantees this project cares most about.

5. **An id that belongs to another tutor's student is answered exactly like
   one that belongs to nobody**: `404`. Holding an id is not enough to read or
   change anything.

6. **An address that was looked up and never used is enrolled but not
   listed.** The list of students shows whoever has a lesson or an entry, as it
   did before, so a mistyped address does not stay on it for ever.

## The data that was already there

Migration 0006 enrols everyone who has a booking or a ledger entry, with one
`INSERT ... SELECT ... ON CONFLICT DO NOTHING`.

The migration only adds things, so the previous version of the application
keeps working against the new schema. It does not enrol anyone, though: a
booking it takes after the migration has run leaves a student without an id
until that version is gone. On one container this cannot happen, because the
old process stops before the new one starts. With several it can, and the
remedy is to run the same statement once more after the last old process has
stopped. It changes nothing for anyone already enrolled, and a test runs it
twice to check that.

## How this is verified

- `tests/contract/test_student_directory.py` states what any directory must
  do and runs against PostgreSQL and the in-memory fake: a booking enrols its
  student, a series does, a refused booking enrols nobody, one address written
  two ways is one student, ten simultaneous enrolments of one address leave
  one student, and two tutors never share one.
- Removing the enrolment from the booking, from the series or from the fake
  was tried as a mutation: between one and five of those tests fail each time.
- `tests/integration/test_migrations.py` builds the database as it was at
  migration 0005, with students known from lessons, from a package and from
  both, migrates, and checks who was enrolled. Then it runs the statement
  again.
- The API tests send an address where the id belongs and expect it to be
  refused, and check that no path in the OpenAPI document takes an e-mail.
- A frontend test opens an account for a new address and asserts that the
  address appears in no request's address, only in one request's body.

## Alternatives considered

- **Encrypt the address and put that in the path** (AES-SIV, so that the same
  student always has the same id). No table, and the smallest change. Rejected
  because it works around the missing model instead of supplying it: it adds a
  cryptography dependency for one feature, every id changes when the key does,
  and its length still gives away the length of the address.
- **Derive the id from the address** (a UUID computed from the tutor and the
  address under a secret). No table and no dependency, but it cannot be turned
  back into an address, so the server would have to search the students it
  already knows, and a student with nothing recorded could not have a page.
- **Keep the address in the path and leave it out of the log.** The
  application's own log is the only one of the three places it controls.
- **Do the whole thing now**: give bookings and ledger entries a `student_id`
  and stop comparing addresses. Right in the end, see point 4.

## Consequences

- The e-mail address is still what identifies a student in bookings and in
  the ledger, so **a student cannot change their address** yet. Now there is
  an id for bookings and entries to move to when that is built.
- The address is not gone from everything a browser sends. The link a tutor
  shares with a parent still carries it, encoded but not hidden, inside the
  token. That token travels in the fragment of the link and in a header,
  neither of which is logged, which is why it was left alone.
- Ids are random, so they do not survive the demo's nightly reset: a bookmark
  of a demo student's page leads to "There is no such student" the next day.
  So does a bookmark from before this change, which holds an address.
- An address that was looked up and never used leaves a row behind. Nothing
  removes it.
- One more query per request on a student's pages, to turn the id into the
  address the ledger knows.
