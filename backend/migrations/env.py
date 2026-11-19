from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tutor_calendar.adapters.postgres.tables import metadata
from tutor_calendar.config import Settings
from tutor_calendar.logs import configure_logging

config = context.config
if config.config_file_name is not None:
    # Run from the command line, as a starting container does. The tests
    # migrate without an ini file and keep the logging they already have.
    configure_logging("migrate", Settings().log_format)

# Migrations are written by hand. The metadata is here so that a test can ask
# Alembic whether the tables the code expects are the tables the migrations build.
target_metadata = metadata

# Any number that nothing else in this database uses as an advisory lock.
MIGRATION_LOCK = 7_021_500_001


def database_url() -> str:
    """The URL the caller chose (tests migrate a separate database), else the app's."""
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    # The image migrates when it starts, so replicas started together all
    # arrive here at once. Without this each would read "nothing applied yet"
    # and try to build the same tables. The lock belongs to the connection, not
    # to a transaction: whoever waits for it only then reads which migrations
    # are applied, finds them done, and does nothing. Closing the connection
    # gives the lock back, also when a migration fails.
    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK})
    connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(database_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
