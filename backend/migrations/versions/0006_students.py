"""Students get an identifier of their own.

Until now a student was their e-mail address: bookings and ledger entries both
name it, and so did every address of a student's page. This table gives each
student of a tutor an id that can stand for the address where the address must
not appear. Bookings and the ledger still refer to students by address; the
table is the one place that pairs the two.

Everyone who already has a lesson or an entry is enrolled here. The statement
that does it changes nothing when run again, which is what makes it safe to
repeat after a deployment during which the previous version was still taking
bookings.

See ADR 0010.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None

ENROL_EVERYONE_KNOWN = """
    INSERT INTO students (tutor_id, account, created_at)
    SELECT tutor_id, account, min(created_at)
    FROM (
        SELECT tutor_id, lower(student_email) AS account, created_at FROM bookings
        UNION ALL
        SELECT tutor_id, account, created_at FROM ledger_entries
    ) AS known
    GROUP BY tutor_id, account
    ON CONFLICT ON CONSTRAINT students_account_unique DO NOTHING
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE students (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            tutor_id uuid NOT NULL,
            account text NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT students_pkey PRIMARY KEY (id),
            CONSTRAINT students_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE RESTRICT,
            -- One student per address for each tutor, however many requests
            -- enrol the same address at once.
            CONSTRAINT students_account_unique UNIQUE (tutor_id, account),
            CONSTRAINT students_account_is_lower_case CHECK (account = lower(account))
        )
        """
    )
    op.execute(ENROL_EVERYONE_KNOWN)
    # A student's name is the one on their latest booking, looked up by address.
    op.execute("CREATE INDEX bookings_student_idx ON bookings (tutor_id, lower(student_email))")


def downgrade() -> None:
    op.execute("DROP INDEX bookings_student_idx")
    op.execute("DROP TABLE students")
