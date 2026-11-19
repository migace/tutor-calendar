"""Whether the database has the migrations this version of the code needs.

Used by the readiness check. See ADR 0011.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cache
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection

# backend/migrations, next to src/. The image keeps the same layout.
MIGRATIONS = Path(__file__).parents[4] / "migrations"


class SchemaState(Enum):
    CURRENT = "current"
    # No migration has ever been applied.
    EMPTY = "empty"
    BEHIND = "behind"
    # At a migration this code has never heard of: a newer version has been here.
    AHEAD = "ahead"


@dataclass(frozen=True, slots=True)
class Schema:
    state: SchemaState
    applied: str | None
    needed: str


@cache
def _known(directory: Path) -> tuple[str, frozenset[str]]:
    """The newest migration in the code, and every migration in it.

    Read from the files once: they do not change while the process runs.
    """
    scripts = ScriptDirectory(str(directory))
    head = scripts.get_current_head()
    if head is None:
        raise RuntimeError(f"no migrations found in {directory}")
    return head, frozenset(script.revision for script in scripts.walk_revisions())


async def schema(connection: AsyncConnection, directory: Path = MIGRATIONS) -> Schema:
    head, known = _known(directory)
    try:
        applied = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    except ProgrammingError:
        # The table Alembic keeps its place in does not exist yet.
        applied = None
    if applied is None:
        state = SchemaState.EMPTY
    elif applied == head:
        state = SchemaState.CURRENT
    elif applied in known:
        state = SchemaState.BEHIND
    else:
        state = SchemaState.AHEAD
    return Schema(state, applied, head)
