# ADR 0009: Request limits, counted in the process

Status: accepted · 2026-11-17

## Context

The demo is on the public internet. Two requests cost something that a loop
could run up: asking for a sign-in link sends an e-mail to an address the
visitor typed, and a booking takes a time away from everyone else and queues
another e-mail. Everything else is cheap one request at a time and not cheap a
thousand at a time.

The application runs as one process behind a proxy that ends TLS. On the demo
that proxy is Cloudflare, in front of a host whose port is also reachable
directly over IPv6.

## Decision

1. **The limits are in the application, as a dependency on the routes.** A
   limit in the proxy would be cheaper, and a real installation should have
   one too, but the demo's proxy is not ours to configure, and a limit that
   lives in someone else's dashboard is not in the repository, is not tested
   and is not there on the next host.
2. **They are at the edge, not in the use cases.** A limit is about who is
   knocking and how often. `BookLesson` knows a tutor, a time and a student;
   it has never heard of an address, and should not.
3. **A token bucket for each limit and each visitor.** The allowance can be
   used at once and is earned back evenly: five sign-in links per quarter of
   an hour is five in a row, then one every three minutes. A fixed window is
   simpler and lets a visitor use two allowances back to back across its
   edge. Per bucket one number is kept, the moment the allowance is whole
   again, so a visitor who has gone quiet can be forgotten without changing
   any answer.
4. **Four limits.** Every request to the API: 120 a minute. Sign-in links: 5
   per 15 minutes. Bookings: 10 per 10 minutes. Demo sessions: 20 per 10
   minutes. The health checks have none, so whatever watches the process is
   never told to wait. A refusal is `429` with `Retry-After`, comes before the
   request is validated, and costs the visitor nothing more.
5. **A visitor is an address, and for IPv6 a /64 network.** A home connection
   is given a whole /64 and can use any address in it, so counting single
   IPv6 addresses would count nothing.
6. **The address comes from the connection unless a header is named.** Behind
   a proxy every connection comes from the proxy. `TC_CLIENT_ADDRESS_HEADER`
   names the header the proxy writes the visitor's address in
   (`CF-Connecting-IP`, `X-Real-IP`). It is off by default, because a header
   is only worth believing when nothing reaches the process except through
   the proxy: anyone else can write it themselves. From a list such as
   `X-Forwarded-For` the last entry is taken, the one the nearest proxy
   added; the entries before it may have been written by the visitor.
7. **The counts are in memory.** There is one process, so there is one count.
   A restart forgets them, which lets a visitor start over once per
   deployment and loses nothing else.

## Consequences

- With more than one web process each would count on its own and the real
  limit would be the stated one times the number of processes. Then the counts
  belong in something shared. PostgreSQL would do and is already there; it
  would also put a write in front of every request, so the general limit
  should move to the proxy and only the two expensive ones to the database.
- **On the demo the header can be forged.** The server's port answers
  directly over IPv6, so someone who finds that address can send any
  `CF-Connecting-IP` they like and get a fresh allowance each time. Closing it
  means a firewall that lets only the proxy's addresses in, which is not set
  up. The limits stop a loop written against the public address, not a
  determined person.
- **Many addresses can still ask for links for one tutor.** Each stays under
  its own limit and the tutor's inbox fills anyway. Bounding the links
  outstanding per account is a rule about accounts and belongs in the use
  case; it is not built.
- People behind one address share an allowance: a school, an office, a mobile
  carrier's gateway. The general limit is set high for that reason. A tutor's
  whole class booking from the school's network in the same ten minutes would
  meet the booking limit.
- The tests turn the limits off and the limits have tests of their own, with
  a clock that only moves when told to. The load test needs them off as well:
  it is one visitor by design.
- The web app shows its own sentence for a `429` and does not retry it.
