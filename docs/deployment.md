# Deployment

The application is one image, a PostgreSQL database and two processes. Nothing
here is specific to a hosting provider.

## The pieces

| Piece | What runs | Notes |
|---|---|---|
| Web | the image's default command, which ends in `python -m tutor_calendar.web` | Migrates the database, stores the demo tutor, then serves the API and the web app on `$PORT` (8000 if unset). Several can serve at once and may start together: migrating takes a lock in the database, so one of them applies a new migration and the others wait and find it done. |
| Worker | `python -m tutor_calendar.worker` in the same image | Charges finished lessons, queues reminders, sends mail. Safe to run several of. |
| Database | PostgreSQL 17 | The `btree_gist` extension is created by the first migration, so the database user must be allowed to create extensions. |

Build the image from the root of the repository:

```bash
docker build -t tutor-calendar .
```

## Configuration

Everything is set through environment variables.

| Variable | Needed | What it is |
|---|---|---|
| `TC_DATABASE_URL` | yes | `postgresql+asyncpg://user:password@host:5432/database` |
| `TC_SECRET_KEY` | yes | At least 32 random characters. Signs the links for managing a booking and for reading a statement. The web process and the worker must have the same value. Changing it breaks every link already sent. |
| `TC_PUBLIC_URL` | yes | The address people open, such as `https://calendar.example.com`. Links in e-mails point here. |
| `TC_SMTP_HOST`, `TC_SMTP_PORT`, `TC_SMTP_USERNAME`, `TC_SMTP_PASSWORD`, `TC_SMTP_STARTTLS`, `TC_MAIL_FROM` | for real mail | Without a host, the worker writes each message to its log instead of sending it. |
| `TC_DEMO_MODE` | no | `true` for a public demonstration. See below. |
| `TC_COOKIE_SECURE` | no | Leave at its default of `true`. The site must be served over HTTPS. |
| `TC_CLIENT_ADDRESS_HEADER` | behind a proxy | The header in which the proxy writes the visitor's address, such as `CF-Connecting-IP` or `X-Real-IP`. The request limits tell visitors apart by it. Without it everyone behind the proxy shares one allowance. See below. |
| `TC_RATE_LIMITS` | no | `false` turns the request limits off. Only for a load test. |
| `TC_METRICS_TOKEN` | to read metrics | At least 32 random characters. Whoever sends it as `Authorization: Bearer ...` may read `/metrics`. Without it the endpoint answers `404`. A shorter one stops the process from starting. See [Watching it](#watching-it). |
| `TC_LOG_FORMAT` | no | `json`, the default, is one object per line. `text` is for reading in a terminal. |
| `WEB_CONCURRENCY` | no | Number of API processes in the web container. |

`TC_STATIC_DIR` is already set inside the image, and `TC_CORS_ORIGINS` is only
for development, when the web app runs on a different port from the API.

## Behind a proxy

The application expects something in front of it that ends TLS and passes
requests on as plain HTTP. Three things depend on what that proxy says:

- **Plain HTTP is redirected to HTTPS** when `TC_PUBLIC_URL` is an `https://`
  address and the proxy sends `X-Forwarded-Proto: http`. A request without the
  header, such as a health check from inside, is answered as it is.
- **`Strict-Transport-Security` is sent** to visitors who arrived over HTTPS.
- **The request limits count visitors by address**
  ([ADR 0009](adr/0009-request-limits-in-the-process.md)). The address of the
  connection is the proxy's, so name the header the proxy puts the real one in
  with `TC_CLIENT_ADDRESS_HEADER`. Do this only when the application's port
  cannot be reached except through the proxy. Anyone who can reach it directly
  can write that header themselves and be a new visitor with every request.

## A public demonstration

With `TC_DEMO_MODE=true`:

- the first start fills the demo tutor's calendar and accounts with a few weeks
  of made-up activity, dated relative to that day;
- the sign-in page offers a button that opens the demo tutor's panel without an
  e-mail link, in a session that lasts two hours;
- every page says that it is a demonstration.

Visitors will book lessons and change the tutor's hours. To put things back,
run this on a schedule, for example nightly:

```bash
python -m tutor_calendar.demo --reset
```

It empties every table of lessons, accounts, queued mail and sessions and seeds
the demo again. It refuses to run unless demo mode is on.

**Do not configure SMTP on a public demonstration.** The booking form accepts
any address, so anyone could use it to make the server send mail to strangers.
Without `TC_SMTP_HOST` nothing leaves the server.

**Never turn demo mode on for an installation with real students.** It lets
anyone into the demo tutor's panel, and makes `--reset` available.

### On one small server

`docker-compose.demo.yml` is everything above put together for a single machine
with Docker: the database, the web process, the worker without a mail server,
and a fourth container that runs the reset every night at 03:00 UTC.

On the server:

```bash
git clone https://github.com/migace/tutor-calendar.git
cd tutor-calendar
cp demo.env.example .env
```

Fill in `.env` as its comments say: the public address, a signing key and a
database password. Compose refuses to start while any of the three is missing.
A fourth, `TC_METRICS_TOKEN`, is optional: without it nobody can read the
metrics, which on a server whose port is open to everyone is the right default.
Then:

```bash
docker compose -f docker-compose.demo.yml up -d --build --wait
```

To put a newer version up, `git pull` and run the same command again. The
database lives in a Docker volume and is kept.

What it expects from the machine:

- **Something in front that terminates TLS** and passes requests to `DEMO_PORT`
  as plain HTTP, with `X-Forwarded-Proto` saying how the visitor arrived. The
  session cookie is marked `Secure`, so signing in works only over HTTPS, and
  visitors who come over plain HTTP are redirected.
- **The port is published on IPv4 and IPv6.** Some budget hosts reach the
  machine only over IPv6, and an application that listens on `0.0.0.0` alone is
  invisible to them.
- **About 150 MB of memory** when idle, measured on the four containers
  together. Building the image needs far more for a few minutes, mostly for the
  web app.

Nothing backs the database up, which is fine for sample data and for nothing
else. The request limits are on, and on a host whose port can be reached
without going through the proxy they can be walked around, as described below.

## Before using it for real

These are known and not built:

- **The request limits trust a header.** They hold only when the application
  cannot be reached except through the proxy that writes it, so keep the port
  closed to everyone else. Nothing bounds the sign-in links sent to one address
  from many visitors. A limit in the proxy as well costs nothing and stops a
  flood before it reaches the application.
- **Sent messages, used sign-in tokens and expired sessions are never removed.**
  The tables only grow.
- **There is no way to create a tutor** other than the demo one, short of
  writing to the database.
- **E-mail is in English only**, whatever language the reader chose in the
  interface.
- **A migration runs while the previous version is still serving**, if there
  is more than one web process. The lock keeps two processes from migrating at
  once; it does not make old code understand a new schema. A change the old
  code cannot live with has to be split over two releases, and nothing here
  checks that it was.
- **No backups are configured.** The ledger cannot be edited, which makes losing
  it worse, not better.
- **Nothing watches it.** The logs and the metrics below are there to be read,
  and nothing reads them: no alert fires, there is no dashboard, and the logs
  stay in Docker's files on the server until they are rotated away.

## Watching it

[ADR 0011](adr/0011-logs-readiness-and-metrics.md) has the reasons for all of
this. The API documents itself at `/docs`.

### Is it up, and can it serve?

Two questions, with an endpoint each. Neither counts against the request
limits.

| | Answers | Looks at | Use it for |
|---|---|---|---|
| `GET /health` | `200` while the process can answer at all | nothing | **Liveness**: deciding to restart a process that has hung. A database that is slow or away must not get the application restarted, and this cannot be affected by one. |
| `GET /health/ready` | `200` when the database answers within two seconds and has every migration this version needs, `503` with the reason otherwise | the database | **Readiness**: deciding whether to send requests here, and whether the things that depend on a migrated database may start. |

Both Compose files point their health check at `/health/ready`. Compose uses
"healthy" as a gate: the worker and the nightly reset wait for it, and so does
`up --wait`. Nothing in Compose restarts a container for being unhealthy, so
there is no liveness check to configure there. On a platform that has both
kinds of probe, give each its own endpoint.

A database that a newer version has already migrated further still counts as
ready, so that the previous version keeps serving while its replacement comes
up.

### Logs

Every process writes one JSON object per line to standard output: the
migration, the seed, the web process and the worker.

```json
{"time": "2026-11-19T10:08:24.644+00:00", "level": "info", "service": "web", "logger": "tutor_calendar.access", "message": "GET /api/v1/tutors/demo/slots 200", "request_id": "4a2d19e6146e49bd9f79ab3e4c75aed8", "method": "GET", "path": "/api/v1/tutors/demo/slots", "route": "/api/v1/tutors/{slug}/slots", "status": 200, "duration_ms": 6.6}
```

- **`request_id`** is on every line written while a request is being
  answered, and comes back to the caller in the `X-Request-ID` header, also
  on an error. A caller or a proxy may send its own in that header: 8 to 64
  characters of letters, digits, `.`, `_` and `-`. Anything else is replaced.
- **`service`** is `migrate`, `demo`, `web` or `worker`.
- **A request's line** has the path without its query string. Students appear
  by id. A part of a path that contains `@` is written as `[address]`.
- **Health checks and metric readings that succeed are not written**, or they
  would be most of the log.
- **An error** is one line with the traceback in `error`.

To follow one request: `docker compose logs web | grep <the id>`.

The worker is the exception to "no addresses in the log". Without
`TC_SMTP_HOST` it writes each message it would have sent, recipient and links
included. That is what the demo does, so the demo's worker log holds the
addresses visitors typed.

### Metrics

`GET /metrics` answers in the Prometheus text format to whoever sends
`TC_METRICS_TOKEN`, and `404` when no token is set:

```bash
curl -H "Authorization: Bearer $TC_METRICS_TOKEN" https://calendar.example.com/metrics
```

| Metric | What it says |
|---|---|
| `tutor_calendar_http_request_duration_seconds` | A histogram of the time taken to answer, by `method`, `route` (the template, such as `/api/v1/tutors/{slug}/slots`) and `status`. Its `_count` is the number of requests. What no API route claimed is under `static` or `unmatched`. |
| `tutor_calendar_booking_requests_total` | Booking requests by `outcome`: `booked`, `taken` (someone else got the time first), `replayed` (a repeat of an earlier request, answered with the same booking) and `not_offered` (too soon, or not a time the tutor teaches). |
| `tutor_calendar_outbox_waiting_messages` | E-mail queued and not sent, including messages waiting to be tried again. |
| `tutor_calendar_outbox_oldest_waiting_seconds` | How long the oldest of them has waited. |
| `tutor_calendar_lessons_awaiting_settlement` | Lessons that are over or cancelled and that the worker has not charged yet. |
| `tutor_calendar_worker_last_success_timestamp_seconds` | When each `job` (`settle`, `remind`, `deliver`) last finished without an error, as Unix time. |
| `tutor_calendar_database_up` | 1 when the database answered this reading. At 0 the four above are missing, not zero. |
| `process_resident_memory_bytes`, `process_cpu_seconds_total` | The web process itself. |

The rows about the outbox, the lessons and the worker are read from the
database at the moment of asking, so they describe the worker although the web
process serves them, and they are still there when the worker is not.

What would be worth an alert, written as Prometheus would want it. None of
these is set up anywhere:

```
# The worker has stopped, or one of its jobs keeps failing.
time() - tutor_calendar_worker_last_success_timestamp_seconds > 300

# Mail is not going out.
tutor_calendar_outbox_oldest_waiting_seconds > 900

# The application is failing.
sum(rate(tutor_calendar_http_request_duration_seconds_count{status=~"5.."}[5m])) > 0

# People are losing races for the same time more than they are winning them.
rate(tutor_calendar_booking_requests_total{outcome="taken"}[1h])
  > rate(tutor_calendar_booking_requests_total{outcome="booked"}[1h])
```

What the numbers cannot do:

- **Requests and bookings are counted in the web process's memory** and start
  at zero when it restarts. With `WEB_CONCURRENCY` above 1 each process counts
  on its own and a reading gets whichever answered, so run one web process if
  these two are to mean anything.
- **Nothing scrapes them.** Point a Prometheus, or anything that speaks its
  format, at `/metrics` with the token.
- **There are no traces.**
