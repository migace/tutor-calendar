# ADR 0001: A modular monolith with a hexagonal core

Status: accepted · 2026-11-14

## Context

The product is a booking calendar for one independent tutor at a time. The
difficult parts are rules, not scale: when a slot exists, who may book it, what
a late cancellation costs. Those rules have to be testable in milliseconds and
without a database, because the interesting cases (two nights a year when the
clocks change, two parents booking the same slot at once) are exactly the ones
nobody triggers by clicking around.

One developer builds and operates it.

## Decision

One deployable backend, split into four layers with a single dependency rule:
**imports point inwards only**.

```
api  ──►  application  ──►  domain
              ▲
adapters ─────┘   (implement the ports the application declares)
```

- `domain/` is plain Python: dataclasses and functions. No FastAPI, SQLAlchemy
  or Pydantic, no clock, no I/O.
- `application/` holds use cases and the **ports** they need (`Clock`,
  `TutorRepository`), declared as `typing.Protocol`s.
- `adapters/` implements ports: PostgreSQL, the system clock, later e-mail.
- `api/` maps HTTP to use-case calls. `api/main.py` is the composition root,
  the only place that knows which adapter backs which port.

The rule is enforced by a test (`tests/unit/test_architecture.py`) that parses
imports, so it cannot erode silently.

Inside the layers, code is grouped by module (`scheduling` now; `billing`,
`notifications` and `identity` as they arrive), not by technical kind.

## Alternatives considered

- **Django.** Faster to a working CRUD and an admin panel. Rejected because the
  ORM model would become the domain model, and the time rules in ADR 0002 would
  end up tested through the database.
- **Framework-first FastAPI** (routers calling SQLAlchemy directly). Less code
  today. Rejected for the same reason: no seam to test booking rules without
  PostgreSQL, and no natural place for a fixed clock.
- **Microservices.** There is one team of one and one database. Nothing to gain.

## Consequences

- Domain tests run without a database: the scheduling rules are covered by
  example-based and property-based tests in well under a minute.
- Time is injectable. Every "now" goes through the `Clock` port, so tests pin it.
- More files and some mapping code between layers than a framework-first layout.
- The first repository is in-memory. That is the port doing its job, but it
  means persistence is not exercised until the PostgreSQL adapter lands.
