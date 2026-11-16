"""The ledger of prepaid lesson time, and the outbox of e-mail to send.

Both tables are written by ordinary application code, so the two properties
they exist for are enforced here, where no code path can forget them:

* ledger entries can be added but never changed or removed;
* a lesson can be charged at most once.

See ADR 0007.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ledger_entries (
            id uuid NOT NULL,
            tutor_id uuid NOT NULL,
            account text NOT NULL,
            kind text NOT NULL,
            minutes integer NOT NULL,
            note text NOT NULL,
            booking_id uuid,
            created_at timestamptz NOT NULL,
            effective_at timestamptz NOT NULL,
            CONSTRAINT ledger_entries_pkey PRIMARY KEY (id),
            CONSTRAINT ledger_entries_tutor_id_fkey
                FOREIGN KEY (tutor_id) REFERENCES tutors (id) ON DELETE RESTRICT,
            CONSTRAINT ledger_entries_booking_id_fkey
                FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE RESTRICT,
            -- One charge per lesson, whoever tries to add it and however often.
            CONSTRAINT ledger_entries_booking_id_key UNIQUE (booking_id),
            CONSTRAINT ledger_entries_kind_valid
                CHECK (kind IN ('purchase', 'lesson', 'adjustment')),
            CONSTRAINT ledger_entries_minutes_not_zero CHECK (minutes <> 0),
            CONSTRAINT ledger_entries_account_is_lower_case CHECK (account = lower(account)),
            CONSTRAINT ledger_entries_charge_names_its_lesson
                CHECK ((kind = 'lesson') = (booking_id IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX ledger_entries_account_idx ON ledger_entries (tutor_id, account)")
    op.execute(
        """
        CREATE FUNCTION ledger_entries_are_permanent() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ledger entries cannot be changed or removed; add a correcting entry'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER ledger_entries_append_only
            BEFORE UPDATE OR DELETE ON ledger_entries
            FOR EACH ROW EXECUTE FUNCTION ledger_entries_are_permanent()
        """
    )

    op.execute(
        """
        CREATE TABLE outbox (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            recipient text NOT NULL,
            subject text NOT NULL,
            body text NOT NULL,
            created_at timestamptz NOT NULL,
            available_at timestamptz NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            last_error text,
            sent_at timestamptz,
            CONSTRAINT outbox_pkey PRIMARY KEY (id)
        )
        """
    )
    # Only what is still waiting is ever searched for, so only that is indexed.
    op.execute("CREATE INDEX outbox_waiting_idx ON outbox (available_at) WHERE sent_at IS NULL")

    op.execute(
        """
        ALTER TABLE bookings
            ADD COLUMN settled_at timestamptz,
            ADD COLUMN reminded_at timestamptz
        """
    )
    op.execute(
        "CREATE INDEX bookings_awaiting_settlement_idx ON bookings (upper(during))"
        " WHERE settled_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX bookings_awaiting_settlement_idx")
    op.execute("ALTER TABLE bookings DROP COLUMN reminded_at, DROP COLUMN settled_at")
    op.execute("DROP TABLE outbox")
    op.execute("DROP TABLE ledger_entries")
    op.execute("DROP FUNCTION ledger_entries_are_permanent()")
