"""Tutor e-mail addresses, sign-in tokens and sessions.

Tokens and sessions are keyed by the SHA-256 digest of the secret given to the
user, never by the secret itself. See ADR 0005.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tutors ADD COLUMN email text")
    # Tutors created before this migration get a placeholder nobody can receive
    # mail at. The only such tutor is the demo one, whose address this matches.
    op.execute("UPDATE tutors SET email = slug || '@example.com'")
    op.execute("ALTER TABLE tutors ALTER COLUMN email SET NOT NULL")
    # Addresses are compared without regard to case, so they are unique that way too.
    op.execute("CREATE UNIQUE INDEX tutors_email_key ON tutors (lower(email))")

    op.execute(
        """
        CREATE TABLE sign_in_tokens (
            digest text NOT NULL,
            tutor_id uuid NOT NULL,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            CONSTRAINT sign_in_tokens_pkey PRIMARY KEY (digest),
            CONSTRAINT sign_in_tokens_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sessions (
            digest text NOT NULL,
            tutor_id uuid NOT NULL,
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT sessions_pkey PRIMARY KEY (digest),
            CONSTRAINT sessions_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE sessions")
    op.execute("DROP TABLE sign_in_tokens")
    op.execute("DROP INDEX tutors_email_key")
    op.execute("ALTER TABLE tutors DROP COLUMN email")
