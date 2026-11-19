# The whole application in one image: the API, the worker, and the built web app.
#
#   web      (default)  migrates, seeds the demo tutor, serves the API and the web app
#   worker              docker run <image> python -m tutor_calendar.worker

FROM node:24-slim AS web
WORKDIR /web
RUN corepack enable
# Dependencies first: this layer is rebuilt only when the lockfile changes.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build


FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    TC_STATIC_DIR=/app/static

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./static

RUN useradd --system app
USER app

EXPOSE 8000
# Migrating and seeding on start keeps deployment to one step. Both are safe to repeat.
# All three write their logs as JSON lines; the last one listens on $PORT, 8000 if unset.
CMD ["sh", "-c", "alembic upgrade head && python -m tutor_calendar.demo && exec python -m tutor_calendar.web"]
