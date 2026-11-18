"""Table definitions used to build queries.

The schema itself is created by the hand-written migrations in ``migrations/``;
an integration test checks that the two descriptions agree.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint

BOOKINGS_NO_OVERLAP = "bookings_no_overlap"
BOOKINGS_IDEMPOTENCY_KEY = "bookings_idempotency_key_unique"
STUDENTS_ACCOUNT = "students_account_unique"

metadata = MetaData(
    naming_convention={
        "pk": "%(table_name)s_pkey",
        "fk": "%(table_name)s_%(column_0_name)s_fkey",
        "uq": "%(table_name)s_%(column_0_name)s_key",
        "ix": "%(table_name)s_%(column_0_name)s_idx",
    }
)

tutors = Table(
    "tutors",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("slug", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("lesson_minutes", Integer, nullable=False),
    Column("min_notice_minutes", Integer, nullable=False),
    # NULL means cancelling is always free.
    Column("cancellation_notice_minutes", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("lesson_minutes > 0", name="tutors_lesson_minutes_positive"),
    CheckConstraint("min_notice_minutes >= 0", name="tutors_min_notice_not_negative"),
    CheckConstraint("cancellation_notice_minutes > 0", name="tutors_cancellation_notice_positive"),
)

# Addresses are compared without regard to case, so they are unique that way too.
Index("tutors_email_key", func.lower(tutors.c.email), unique=True)

availability_rules = Table(
    "availability_rules",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="CASCADE"), nullable=False),
    # 0 is Monday, as in date.weekday().
    Column("weekday", SmallInteger, nullable=False),
    # Wall-clock times in the tutor's zone, hence no time zone here. See ADR 0002.
    Column("start_time", Time(timezone=False), nullable=False),
    Column("end_time", Time(timezone=False), nullable=False),
    CheckConstraint("weekday BETWEEN 0 AND 6", name="availability_rules_weekday_valid"),
    CheckConstraint("start_time < end_time", name="availability_rules_start_before_end"),
    Index("availability_rules_tutor_id_idx", "tutor_id"),
)

days_off = Table(
    "days_off",
    metadata,
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="CASCADE"), primary_key=True),
    Column("day", Date, primary_key=True),
)

lesson_series = Table(
    "lesson_series",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="RESTRICT"), nullable=False),
    Column("student_name", Text, nullable=False),
    Column("student_email", Text, nullable=False),
    Column("first_day", Date, nullable=False),
    # A wall-clock time in the tutor's zone, like availability rules.
    Column("start_time", Time(timezone=False), nullable=False),
    Column("weeks", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("weeks BETWEEN 1 AND 52", name="lesson_series_weeks_valid"),
    Index("lesson_series_tutor_id_idx", "tutor_id"),
)

bookings = Table(
    "bookings",
    metadata,
    Column("id", Uuid, primary_key=True),
    # RESTRICT: a tutor with lessons on the books cannot be deleted by accident.
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="RESTRICT"), nullable=False),
    Column("during", TSTZRANGE, nullable=False),
    Column("student_name", Text, nullable=False),
    Column("student_email", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("cancelled_by", Text, nullable=True),
    Column("cancelled_at", DateTime(timezone=True), nullable=True),
    Column("cancelled_late", Boolean, nullable=True),
    Column("series_id", Uuid, ForeignKey("lesson_series.id", ondelete="RESTRICT"), nullable=True),
    # When the lesson's cost became final and was passed to the ledger, and
    # when its reminder was queued. Both are set once. See ADR 0007.
    Column("settled_at", DateTime(timezone=True), nullable=True),
    Column("reminded_at", DateTime(timezone=True), nullable=True),
    Index("bookings_series_id_idx", "series_id"),
    CheckConstraint(
        "status IN ('confirmed', 'cancelled', 'no_show')", name="bookings_status_valid"
    ),
    CheckConstraint("cancelled_by IN ('student', 'tutor')", name="bookings_cancelled_by_valid"),
    CheckConstraint(
        "(status = 'cancelled') = (cancelled_by IS NOT NULL)"
        " AND (cancelled_by IS NULL) = (cancelled_at IS NULL)"
        " AND (cancelled_by IS NULL) = (cancelled_late IS NULL)",
        name="bookings_cancellation_is_complete",
    ),
    CheckConstraint(
        "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)"
        " AND lower_inc(during) AND NOT upper_inc(during)",
        name="bookings_during_is_half_open",
    ),
    UniqueConstraint("tutor_id", "idempotency_key", name=BOOKINGS_IDEMPOTENCY_KEY),
    # The guarantee against double booking (ADR 0003). A cancelled lesson gives
    # its time back, so it is left out of the comparison (ADR 0006).
    ExcludeConstraint(
        ("tutor_id", "="),
        ("during", "&&"),
        name=BOOKINGS_NO_OVERLAP,
        using="gist",
        where=text("status <> 'cancelled'"),
    ),
)

# A student's name is the one on their latest booking, looked up by address.
Index("bookings_student_idx", bookings.c.tutor_id, func.lower(bookings.c.student_email))

# Pairs each student's address with an id that can stand for it where the
# address must not appear, such as the address of a page. Bookings and the
# ledger still name students by address. See ADR 0010.
students = Table(
    "students",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="RESTRICT"), nullable=False),
    # The address in lower case, exactly as the ledger files it.
    Column("account", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tutor_id", "account", name=STUDENTS_ACCOUNT),
    CheckConstraint("account = lower(account)", name="students_account_is_lower_case"),
)

# Both tables are keyed by the SHA-256 digest of a secret, never the secret. See ADR 0005.
sign_in_tokens = Table(
    "sign_in_tokens",
    metadata,
    Column("digest", Text, primary_key=True),
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True), nullable=True),
)

sessions = Table(
    "sessions",
    metadata,
    Column("digest", Text, primary_key=True),
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index(
    "bookings_awaiting_settlement_idx",
    func.upper(bookings.c.during),
    postgresql_where=bookings.c.settled_at.is_(None),
)

# Entries are only ever added. A trigger in migration 0005 rejects UPDATE and
# DELETE, so that holds for every writer, not just this code.
ledger_entries = Table(
    "ledger_entries",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tutor_id", Uuid, ForeignKey("tutors.id", ondelete="RESTRICT"), nullable=False),
    Column("account", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("minutes", Integer, nullable=False),
    Column("note", Text, nullable=False),
    # One charge per lesson, whoever tries to add it and however often.
    Column(
        "booking_id",
        Uuid,
        ForeignKey("bookings.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "kind IN ('purchase', 'lesson', 'adjustment')", name="ledger_entries_kind_valid"
    ),
    CheckConstraint("minutes <> 0", name="ledger_entries_minutes_not_zero"),
    CheckConstraint("account = lower(account)", name="ledger_entries_account_is_lower_case"),
    CheckConstraint(
        "(kind = 'lesson') = (booking_id IS NOT NULL)",
        name="ledger_entries_charge_names_its_lesson",
    ),
    Index("ledger_entries_account_idx", "tutor_id", "account"),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("recipient", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("last_error", Text, nullable=True),
    Column("sent_at", DateTime(timezone=True), nullable=True),
)
Index("outbox_waiting_idx", outbox.c.available_at, postgresql_where=outbox.c.sent_at.is_(None))
