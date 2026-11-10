"""A database the chain carried past 0175 without running it gets the column."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = pytest.mark.anyio

_PATH = Path(__file__).parents[2] / "alembic/versions/0214_profile_key_column_again.py"


def _migration():
    spec = importlib.util.spec_from_file_location("profile_key_column_migration", _PATH)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _profiles(connection: Connection, *, with_column: bool) -> None:
    """A temporary `model_profiles`, which shadows the real one for this transaction."""
    column = ", runs_without_key boolean NOT NULL DEFAULT false" if with_column else ""
    connection.execute(
        text(
            "CREATE TEMP TABLE model_profiles (id int, provider text, secret_id uuid, "
            f"base_url text{column}) ON COMMIT DROP"
        )
    )
    connection.execute(
        text("""
        INSERT INTO model_profiles (id, provider, secret_id, base_url) VALUES
        (1, 'ollama', NULL, 'http://ollama:11434'),
        (2, 'openai', NULL, NULL),
        (3, 'openai', '00000000-0000-0000-0000-000000000001', 'http://proxy'),
        (4, 'anthropic', NULL, 'http://gateway')
    """)
    )


def _upgrade(connection: Connection) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        _migration().upgrade()


def _keyless(connection: Connection) -> list[tuple[int, bool]]:
    return [
        (row.id, row.runs_without_key)
        for row in connection.execute(
            text("SELECT id, runs_without_key FROM model_profiles ORDER BY id")
        )
    ]


async def test_a_database_past_0175_without_its_column_gets_it_backfilled(
    db: AsyncSession,
) -> None:
    def migrate(session: Session) -> None:
        connection = session.connection()
        _profiles(connection, with_column=False)
        _upgrade(connection)
        assert _keyless(connection) == [(1, True), (2, False), (3, False), (4, False)]

    await db.run_sync(migrate)


async def test_a_database_that_ran_0175_is_left_as_it_is(db: AsyncSession) -> None:
    def migrate(session: Session) -> None:
        connection = session.connection()
        _profiles(connection, with_column=True)
        # A person's choice since 0175 ran; a second backfill would overwrite it.
        connection.execute(text("UPDATE model_profiles SET runs_without_key = id = 4"))
        _upgrade(connection)
        assert _keyless(connection) == [(1, False), (2, False), (3, False), (4, True)]

    await db.run_sync(migrate)
