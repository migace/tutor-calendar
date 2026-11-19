"""A record of when each background job last finished without an error.

The worker writes a row per job after each round; the web process reads them
when it is asked for metrics. That is how "is the worker still working?" gets
an answer from a process that is not the worker, and keeps one when the worker
is gone.

Nothing here touches a table that was already there, so the previous version
of the application keeps working against the new schema.

See ADR 0011.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE background_jobs (
            name text NOT NULL,
            last_succeeded_at timestamptz NOT NULL,
            CONSTRAINT background_jobs_pkey PRIMARY KEY (name)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE background_jobs")
