"""Lesson states, cancellation, and weekly series.

The exclusion constraint from 0002 becomes partial: a cancelled lesson no
longer occupies its time, so the slot can be booked again. See ADR 0006.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # NULL means cancelling is always free. Existing tutors get the default of a day.
    op.execute("ALTER TABLE tutors ADD COLUMN cancellation_notice_minutes integer DEFAULT 1440")
    op.execute("ALTER TABLE tutors ALTER COLUMN cancellation_notice_minutes DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE tutors ADD CONSTRAINT tutors_cancellation_notice_positive
            CHECK (cancellation_notice_minutes > 0)
        """
    )

    op.execute(
        """
        CREATE TABLE lesson_series (
            id uuid NOT NULL,
            tutor_id uuid NOT NULL,
            student_name text NOT NULL,
            student_email text NOT NULL,
            first_day date NOT NULL,
            start_time time NOT NULL,
            weeks integer NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT lesson_series_pkey PRIMARY KEY (id),
            CONSTRAINT lesson_series_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE RESTRICT,
            CONSTRAINT lesson_series_weeks_valid CHECK (weeks BETWEEN 1 AND 52)
        )
        """
    )
    op.execute("CREATE INDEX lesson_series_tutor_id_idx ON lesson_series (tutor_id)")

    op.execute(
        """
        ALTER TABLE bookings
            ADD COLUMN status text NOT NULL DEFAULT 'confirmed',
            ADD COLUMN cancelled_by text,
            ADD COLUMN cancelled_at timestamptz,
            ADD COLUMN cancelled_late boolean,
            ADD COLUMN series_id uuid,
            ADD CONSTRAINT bookings_status_valid
                CHECK (status IN ('confirmed', 'cancelled', 'no_show')),
            ADD CONSTRAINT bookings_cancelled_by_valid
                CHECK (cancelled_by IN ('student', 'tutor')),
            -- The three details are present together, and only for a cancelled lesson.
            ADD CONSTRAINT bookings_cancellation_is_complete CHECK (
                (status = 'cancelled') = (cancelled_by IS NOT NULL)
                AND (cancelled_by IS NULL) = (cancelled_at IS NULL)
                AND (cancelled_by IS NULL) = (cancelled_late IS NULL)
            ),
            ADD CONSTRAINT bookings_series_id_fkey
                FOREIGN KEY (series_id) REFERENCES lesson_series (id) ON DELETE RESTRICT
        """
    )
    op.execute("ALTER TABLE bookings ALTER COLUMN status DROP DEFAULT")
    op.execute("CREATE INDEX bookings_series_id_idx ON bookings (series_id)")

    op.execute("ALTER TABLE bookings DROP CONSTRAINT bookings_no_overlap")
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
            EXCLUDE USING gist (tutor_id WITH =, during WITH &&)
            WHERE (status <> 'cancelled')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP CONSTRAINT bookings_no_overlap")
    # Cancelled lessons may share their time with later bookings, which the
    # unconditional constraint would reject. Going back means losing them.
    op.execute("DELETE FROM bookings WHERE status = 'cancelled'")
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
            EXCLUDE USING gist (tutor_id WITH =, during WITH &&)
        """
    )
    op.execute("DROP INDEX bookings_series_id_idx")
    op.execute(
        """
        ALTER TABLE bookings
            DROP CONSTRAINT bookings_series_id_fkey,
            DROP CONSTRAINT bookings_cancellation_is_complete,
            DROP CONSTRAINT bookings_cancelled_by_valid,
            DROP CONSTRAINT bookings_status_valid,
            DROP COLUMN series_id,
            DROP COLUMN cancelled_late,
            DROP COLUMN cancelled_at,
            DROP COLUMN cancelled_by,
            DROP COLUMN status
        """
    )
    op.execute("DROP TABLE lesson_series")
    op.execute("ALTER TABLE tutors DROP COLUMN cancellation_notice_minutes")
