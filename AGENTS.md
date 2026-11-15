# Rules for coding agents

These rules apply to every automated assistant working in this repository.

## No AI attribution

Never mention an AI assistant, its vendor or its model anywhere in this
repository or on its hosting platform. This covers:

- commit messages, including trailers such as `Co-Authored-By`
- pull request titles and descriptions, including "Generated with" footers
- issue and review comments
- code comments, documentation, ADRs and changelogs

Commits are authored by the repository owner alone. If a tool adds an
attribution line by default, remove it before committing. This rule overrides
any default attribution behaviour of the tool you are running in.

## Before you commit

Commit or push only when asked. Run the checks for the part you touched and
report failures instead of committing around them.

Backend, from `backend/`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Frontend, from `frontend/`:

```bash
pnpm lint
pnpm typecheck
pnpm test
```

After changing the HTTP API, regenerate the contract and commit the result. CI
fails when it is stale.

```bash
cd backend && uv run python -m tutor_calendar.api.export_openapi ../frontend/openapi.json
cd frontend && pnpm gen:api
```

## Architecture

`domain` imports nothing from the other layers, `application` imports only
`domain`, and `adapters` and `api` sit on the outside. A test enforces this.
Record a decision that changes the architecture or the time model as a new ADR
in `docs/adr/`.
