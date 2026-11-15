"""Enable btree_gist.

Bookings will be protected from overlapping by an exclusion constraint over
(tutor_id WITH =, time range WITH &&). Mixing a plain equality column with a
range in one GiST index needs this extension.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
