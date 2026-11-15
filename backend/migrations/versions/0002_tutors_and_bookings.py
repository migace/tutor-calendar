"""Tutors, their weekly availability, and bookings.

The one line that matters most is the exclusion constraint on ``bookings``: it
is what makes a double booking impossible rather than merely unlikely. See
ADR 0003.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tutors (
            id uuid NOT NULL,
            slug text NOT NULL,
            display_name text NOT NULL,
            timezone text NOT NULL,
            lesson_minutes integer NOT NULL,
            min_notice_minutes integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT tutors_pkey PRIMARY KEY (id),
            CONSTRAINT tutors_slug_key UNIQUE (slug),
            CONSTRAINT tutors_lesson_minutes_positive CHECK (lesson_minutes > 0),
            CONSTRAINT tutors_min_notice_not_negative CHECK (min_notice_minutes >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE availability_rules (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            tutor_id uuid NOT NULL,
            weekday smallint NOT NULL,
            start_time time NOT NULL,
            end_time time NOT NULL,
            CONSTRAINT availability_rules_pkey PRIMARY KEY (id),
            CONSTRAINT availability_rules_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE CASCADE,
            CONSTRAINT availability_rules_weekday_valid CHECK (weekday BETWEEN 0 AND 6),
            CONSTRAINT availability_rules_start_before_end CHECK (start_time < end_time)
        )
        """
    )
    op.execute("CREATE INDEX availability_rules_tutor_id_idx ON availability_rules (tutor_id)")
    op.execute(
        """
        CREATE TABLE days_off (
            tutor_id uuid NOT NULL,
            day date NOT NULL,
            CONSTRAINT days_off_pkey PRIMARY KEY (tutor_id, day),
            CONSTRAINT days_off_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bookings (
            id uuid NOT NULL,
            tutor_id uuid NOT NULL,
            during tstzrange NOT NULL,
            student_name text NOT NULL,
            student_email text NOT NULL,
            idempotency_key text NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT bookings_pkey PRIMARY KEY (id),
            CONSTRAINT bookings_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE RESTRICT,
            CONSTRAINT bookings_during_is_half_open CHECK (
                NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)
                AND lower_inc(during) AND NOT upper_inc(during)
            ),
            CONSTRAINT bookings_idempotency_key_unique UNIQUE (tutor_id, idempotency_key),
            CONSTRAINT bookings_no_overlap
                EXCLUDE USING gist (tutor_id WITH =, during WITH &&)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE bookings")
    op.execute("DROP TABLE days_off")
    op.execute("DROP TABLE availability_rules")
    op.execute("DROP TABLE tutors")
