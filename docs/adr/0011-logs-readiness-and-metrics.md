# ADR 0011: Logs, readiness and metrics, sized for one server

Status: accepted · 2026-11-19

## Context

The demo runs on one small server, and until now the only way to learn how it
was doing was to open it. What it wrote down was uvicorn's access line, which
includes the query string and has no way to tie two lines together, and
whatever the worker printed. `/health/ready` answered `200` to a database with
no tables in it. Nothing could say whether the worker was still running,
whether mail was going out, or how many people had been told that a time was
taken.

Four things were already decided and shape the answer:

- The whole demo has about 150 MB to live in. There is no room for a second
  stack that watches the first.
- The application's port can be reached from the internet without going
  through the proxy (ADR 0009).
- Sign-in tokens and e-mail addresses stay out of everything that gets written
  down on the way (ADR 0005, ADR 0010).
- Use cases know nothing about HTTP or about what runs them (ADR 0001).

## Decision

1. **Every process writes one JSON object per line to standard output**: the
   migration, the seed, the web process and the worker, and the libraries
   inside them. A line has `time`, `level`, `service`, `logger` and `message`,
   then whatever the caller attached, and `error` with the traceback when
   there was one. The formatter is thirty lines on top of the standard
   library. `TC_LOG_FORMAT=text` is for a person at a terminal.

2. **Every request has an id.** A caller may send one in `X-Request-ID`. It is
   kept if it is 8 to 64 characters of letters, digits, `.`, `_` and `-`, and
   replaced otherwise, because it is repeated in every line and in a response
   header. The id goes back in the same header, also on refusals and
   redirects, and is on every line written while the request is being
   answered, without anyone passing it along.

3. **An error nobody handled is answered with the id and logged once.** The
   answer is `500` with a plain body; the line has the traceback and the same
   id as the request's own line.

4. **The application writes the line for each request, and uvicorn's is
   switched off.** It has the method, the path, the route's template, the
   status and the time taken.
   - The query string is never written.
   - Ids of students, lessons and series are kept: they are what makes a line
     worth having, and they are why ADR 0010 exists.
   - A part of the path that contains `@` is written as `[address]`. No
     address the application hands out has one, but a path is whatever the
     visitor typed, and a bookmark from before ADR 0010 still holds one.
   - The visitor's network address is not written. The request limits are the
     only thing here that needs it, and they keep it in memory.
   - Health checks and metric readings that succeed are left out. They would
     be most of the log. Ones that fail are written.
   - The server's WebSocket support is switched off. The application has no
     WebSockets, and with it on uvicorn answers a handshake itself and logs
     the caller's address and the whole query string, whatever its access log
     is set to. Found in review; a test now sends one.

5. **The database driver hides the values of a failed statement.** Otherwise
   the traceback of a database error quotes its parameters, which are names
   and addresses.

6. **Liveness and readiness are two questions.** `/health` looks at nothing:
   it is for whatever restarts a process that has stopped answering, and a
   slow database must not get a healthy process restarted. `/health/ready`
   asks the database, with two seconds to answer, which migration it is at.
   - No migrations at all, or fewer than this version has: `503`, saying
     which.
   - A migration this version has never heard of: `200`. A newer version
     migrated while this one was still serving, and migrations are written so
     that the previous version carries on (ADR 0010 has an example). Calling
     that unready would take every old process out of service at the same
     moment.

7. **Metrics are served in the Prometheus text format at `/metrics`**, with
   `prometheus-client`:
   - requests, as a histogram of the time taken by method, route template and
     status. Its `_count` is the number of requests;
   - bookings by outcome: `booked`, `taken`, `replayed`, `not_offered`;
   - e-mail queued and not sent, and how long the oldest has been waiting;
   - lessons whose cost is final and not charged yet;
   - when each background job last finished without an error;
   - whether the database answered, and the memory and CPU of the process.

   No label holds a tutor, a student or an address. The values are route
   templates, status codes, known methods and a few fixed words, so the number
   of series is bounded by the code and not by who visits.

8. **Only a bearer of `TC_METRICS_TOKEN` may read them, and without a token
   the endpoint answers `404`.** How busy a tutor is is not public, and the
   port is. The token must be at least 32 characters, or the process refuses
   to start: the endpoint is outside the request limits, so that a scraper is
   never told to wait, and the length of the token is what stops guessing.

9. **The state of the background work is read from the database when the
   metrics are asked for, by the web process.** The worker serves nothing. It
   writes one row per job to a new table, `background_jobs`, after each round
   in which the job finished, and the backlog is counted from the outbox and
   the lessons themselves. So the numbers are the same whichever worker did
   the work, and they are still there when no worker is running, which is the
   moment they matter. When the database does not answer they are left out and
   `tutor_calendar_database_up` is 0; a zero would say that nothing is
   waiting.

10. **Nothing inside the use cases writes a log or counts anything.** There
    were two ways to keep it so, and both are used.
    - *Measure at the edge*, where the edge already knows the answer. The
      route that takes a booking counts its outcome from what `BookLesson`
      returns or raises, exactly as it picks the status code. The worker
      records a job after the use case returns.
    - *A port*, where the answer is in the database. `Outbox.backlog`,
      `SettlementQueue.count_awaiting_settlement` and the new `JobLog` are
      ports with contract tests against PostgreSQL and the fakes, and
      `MeasureBackgroundWork` puts them together and returns plain numbers.
      Turning those into metrics is done by whoever asked.

    `test_architecture.py` now fails if `domain` or `application` imports
    `logging`, `prometheus_client`, `opentelemetry` or the logging module of
    this project.

## How this is verified

- API tests, with fakes: the id is made up, kept or replaced; it is on
  refusals, on a redirect and on a `500`; one line per request with the route
  template; a booking, a sign-in and a student's statement leave no `@`, no
  token and no session in the log, and the statement's line has the student's
  id; the query string is not there; metrics are `404` without a token and
  `401` with a wrong one; and booking, booking again with the same key,
  booking a taken time and booking a time not offered move one count each.
- Contract tests for the three ports, against both implementations: what
  counts as waiting, that a message which keeps failing keeps its age, that
  twelve workers reporting at once leave the latest time and a late one does
  not put it back.
- Against PostgreSQL: readiness for a database with nothing in it, one
  migration short, current, and ahead; the worker records the jobs it
  finished and not the one that raised; a booking over HTTP and the worker
  round after it change the metrics.
- The real processes are started and every line they write is parsed:
  `alembic upgrade head`, the worker, and the web process answering a request
  with a query string in it and refusing a WebSocket handshake with a token
  in it.
- Nineteen mutations were tried by hand, among them: taking any id the caller
  sends, leaving addresses in paths, logging the query string, labelling by
  path, serving metrics without the token, not telling a replay from a
  booking, readiness that ignores a database that is behind, readiness that
  refuses one that is ahead, a backlog dated from the next try, a job recorded
  although it failed, a use case importing `logging`, uvicorn's access log
  left on, and its WebSocket support left on. Each made at least one test
  fail.
- The image was built and the demo's Compose file started from it on a
  developer's machine. The containers became healthy, every line they wrote
  was JSON, and a booking, the same request again and a rival for the same
  time showed in `/metrics` as one `booked`, one `replayed` and one `taken`,
  next to the worker's three jobs. CI builds the image and does not run it.

## Alternatives considered

- **OpenTelemetry.** The version of FastAPI in use has it built in:
  `FastAPI(telemetry=...)` produces request spans and request metrics, and
  does nothing until a provider is configured, which is how it is left here.
  Turning it on means the SDK and an exporter in the process and, for the
  automatic setup, a collector to send to over OTLP. There is no collector on
  this server and no memory to give one. The numbers that matter most here,
  the backlog and the booking outcomes, are not about HTTP and would have
  needed instruments of their own either way. And an endpoint that is pulled
  can be read with `curl` on the day nothing else is set up, which is every
  day so far. This is not closed: a collector can scrape the same endpoint,
  and when there is somewhere to send traces, FastAPI's can be switched on
  without touching anything decided here.
- **A metrics endpoint on the worker.** A worker that has died reports
  nothing, and "nothing" is not an alert. It would also be a second port to
  guard.
- **A port for booking outcomes, handed to `BookLesson`.** The use case would
  announce each outcome to something that counts. It already announces them,
  by returning and raising, to a route that has to tell them apart anyway.
  This becomes right when an outcome appears where no edge can see it.
- **A logging library** (structlog, python-json-logger). A dependency in
  place of thirty lines.
- **Metrics on a second port, open only to the machine itself.** No token to
  keep, but a second listener in the process, and it cannot be read through
  the proxy by anything that is not on the server.
- **Letting in only some addresses.** Behind a proxy every connection comes
  from the proxy, and the header that names the real address can be written by
  anyone who reaches the port (ADR 0009).
- **Readiness that demands exactly the newest migration.** Simpler to state,
  and an outage during every deployment with more than one process.
- **Writing a digest of the address** to the log, so that one person's
  requests could be followed. The student's id already does that where it
  matters, and a digest of an address can be recomputed by anyone who has the
  address.

## Consequences

- **Nothing looks at any of this.** There is no alerting and no dashboard, and
  on the demo nothing reads `/metrics` unless a person does. The logs stay on
  the server, in Docker's files, capped at 30 MB per container.
  `docs/deployment.md` says what would be worth alerting on.
- **The counts are kept per process and start at zero when it restarts.**
  That is what a Prometheus counter is and a scraper allows for it. With more
  than one web process each would keep its own and a reading would get
  whichever answered, so the request and booking counts would be wrong. It is
  the limit ADR 0009 already has, for the same reason. The numbers read from
  the database do not have it.
- **There are no traces.** A request can be followed through the log by its
  id, inside one process.
- **The id stops at the outbox.** A confirmation queued by a request is sent
  by a worker round that knows nothing of the request.
- **The worker still writes whole e-mails to its log when no mail server is
  configured**, address and link included. That is the stand-in for sending
  in development, and the demo runs that way so that nothing leaves the
  machine, so the demo's worker log holds whatever addresses visitors typed.
  This decision is about the lines written for requests and does not change
  that.
- **Only an address is cut out of a path.** Anything else a visitor types
  into one is written, up to 256 characters.
- **A setting that is refused at start is named and not quoted**, so a token
  that was too short does not end up in the log of every container that
  failed to start. That refusal is the one thing still written as plain text:
  it happens before logging is set up.
- **The proxy in front and the host keep logs of their own**, with the
  visitor's address and the full URL. Nothing here changes what they write.
- **Readiness cannot tell a newer version's database from a stranger's.** A
  migration it does not know counts as newer.
- One more table, three one-row writes per worker round, and three small
  queries per reading of the metrics.
- An installation that parsed uvicorn's access lines will find JSON instead.
  Development still starts uvicorn directly and keeps its output.
