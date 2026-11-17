# ADR 0005: Tutors sign in with a link, and stay signed in with a cookie

Status: accepted · 2026-11-15

## Context

The tutor panel shows students' names and e-mail addresses and can change what
the public is offered, so it needs sign-in. The users are individual tutors who
open the panel a few times a week, often on a phone.

A password would be one more thing for them to forget and for this project to
store, reset and protect against guessing. Every password system ends up with
"e-mail me a reset link" anyway, which already makes the mailbox the real key.

## Decision

1. **Sign-in is a link sent by e-mail.** The tutor enters their address and
   receives a link containing a random token. The token is 256 bits from the
   operating system, works once, and expires after 15 minutes.
2. **The request never says whether the address is known.** The endpoint
   answers `202` either way, so it cannot be used to list who has an account.
3. **The token travels in the URL fragment** (`/sign-in/verify#token=...`).
   Browsers do not send the fragment to servers, so the token stays out of
   access logs and `Referer` headers. The page reads it, posts it once and
   removes it from the address bar. A link scanner that merely fetches the URL
   cannot use the token up, because redeeming it takes a `POST`.
4. **Redeeming is one atomic statement**: an `UPDATE ... WHERE used_at IS NULL
   AND expires_at > now RETURNING tutor_id`. Two requests with the same token
   cannot both succeed.
5. **A session is a second random token in a cookie**: `HttpOnly`, so scripts
   cannot read it; `Secure`; `SameSite=Lax`; valid for 30 days. Signing out
   deletes the session on the server, not just the cookie.
6. **Only SHA-256 digests of both tokens are stored.** A copy of the database
   is not enough to sign in as anyone. A fast hash is appropriate because the
   tokens are random: there is nothing to guess, unlike with a password.

## Cross-site request forgery

The session cookie is sent automatically, so another site could try to make the
tutor's browser call the API. Three things stop it:

- `SameSite=Lax` keeps the cookie off cross-site `POST`, `PUT` and `DELETE`
  requests.
- Endpoints that change something accept only JSON, or use `PUT` or `DELETE`.
  A page on another site can send none of those without a CORS preflight, and
  the API answers preflights for its own web origin alone. A form post or a
  `text/plain` post, which need no preflight, is rejected with `422`.
- No endpoint changes state on `GET`.

Tests cover the cookie attribute, the rejected content types and the preflight
answer for a foreign origin.

## How this is verified

- A contract for the credential store runs against PostgreSQL and the in-memory
  fake: single use, expiry, and twelve simultaneous attempts to redeem one
  token of which exactly one succeeds.
- Through HTTP and a real database, one link opened in twelve browsers at once
  creates one session.
- API tests check the cookie's attributes, that the two answers to a link
  request are identical, that signing out kills the session on the server, and
  that every panel endpoint answers `401` without a session.
- The browser tests render the app in React's strict mode, which mounts
  components twice, and assert that the single-use token is still posted once.
- Mutations tried by hand, each caught: allowing a token to be redeemed twice,
  ignoring expiry, making the cookie readable by scripts, and dropping the
  tutor filter from the week query.

## Alternatives considered

- **Passwords.** Familiar, but they add storage, reset and brute-force
  protection for no gain when the mailbox can already reset them.
- **Sign in with Google.** Fewer steps for those who have an account, but a
  dependency on a third party and its consent screens. It can be added next to
  links later.
- **A signed token (JWT) in browser storage instead of a server-side session.**
  Nothing to look up per request, but readable by any script on the page and
  impossible to revoke before it expires. Sign-out has to actually work.
- **The token in the query string.** Simpler to read, but it would be written
  to every access log on the way.

## Consequences

- Whoever controls the mailbox controls the account. That is true of password
  reset as well; here it is explicit.
- Each request to the panel costs one indexed lookup of the session.
- Sign-in messages are queued in the outbox and sent by the worker (ADR 0007).
  With no mail server configured the worker writes them to its log, which is
  enough for development.
- Not implemented yet, and needed before that: a limit on how many links can be
  requested for one address, and removal of expired tokens and sessions.
  [ADR 0009](0009-request-limits-in-the-process.md) later limited how many
  links one visitor can ask for, which is not the same thing.
