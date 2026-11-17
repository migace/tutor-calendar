# Deployment

The application is one image, a PostgreSQL database and two processes. Nothing
here is specific to a hosting provider.

## The pieces

| Piece | What runs | Notes |
|---|---|---|
| Web | the image's default command | Migrates the database, stores the demo tutor, then serves the API and the web app on `$PORT` (8000 if unset). Several can serve at once, but start one first, so that a new migration is applied by one process and not raced by several. |
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
| `WEB_CONCURRENCY` | no | Number of API processes in the web container. |

`TC_STATIC_DIR` is already set inside the image, and `TC_CORS_ORIGINS` is only
for development, when the web app runs on a different port from the API.

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
Then:

```bash
docker compose -f docker-compose.demo.yml up -d --build --wait
```

To put a newer version up, `git pull` and run the same command again. The
database lives in a Docker volume and is kept.

What it expects from the machine:

- **Something in front that terminates TLS** and passes requests to `DEMO_PORT`
  as plain HTTP. The session cookie is marked `Secure`, so signing in works only
  when the visitor's side of the connection is HTTPS.
- **The port is published on IPv4 and IPv6.** Some budget hosts reach the
  machine only over IPv6, and an application that listens on `0.0.0.0` alone is
  invisible to them.
- **About 150 MB of memory** when idle, measured on the four containers
  together. Building the image needs far more for a few minutes, mostly for the
  web app.

Nothing backs the database up, which is fine for sample data and for nothing
else, and the lack of a request limit described below applies in full.

## Before using it for real

These are known and not built:

- **No limit on requests.** Nothing stops someone from asking for sign-in links
  or making bookings in a loop. Put a rate limit in front of the application.
- **Sent messages, used sign-in tokens and expired sessions are never removed.**
  The tables only grow.
- **There is no way to create a tutor** other than the demo one, short of
  writing to the database.
- **E-mail is in English only**, whatever language the reader chose in the
  interface.
- **No backups are configured.** The ledger cannot be edited, which makes losing
  it worse, not better.

## Checking a deployment

- `GET /health` answers `200` when the process is up.
- `GET /health/ready` answers `200` when the database can be reached, and `503`
  otherwise. Use this one for readiness checks.
- The API documents itself at `/docs`.
