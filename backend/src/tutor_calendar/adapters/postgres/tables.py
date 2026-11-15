"""Table definitions used to build queries.

The schema itself is created by the hand-written migrations in ``migrations/``;
an integration test checks that the two descriptions agree.
"""

from __future__ import annotations

from sqlalchemy import (
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
    Column("timezone", Text, nullable=False),
    Column("lesson_minutes", Integer, nullable=False),
    Column("min_notice_minutes", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("lesson_minutes > 0", name="tutors_lesson_minutes_positive"),
    CheckConstraint("min_notice_minutes >= 0", name="tutors_min_notice_not_negative"),
)

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
    CheckConstraint(
        "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)"
        " AND lower_inc(during) AND NOT upper_inc(during)",
        name="bookings_during_is_half_open",
    ),
    UniqueConstraint("tutor_id", "idempotency_key", name=BOOKINGS_IDEMPOTENCY_KEY),
    # The guarantee against double booking. See ADR 0003.
    ExcludeConstraint(("tutor_id", "="), ("during", "&&"), name=BOOKINGS_NO_OVERLAP, using="gist"),
)
