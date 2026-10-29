"""Timestamp backfill refresh: retain sessions and make old reads eligible again."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_old_thread_stamps_are_cleared_without_deleting_sessions() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0179_reread_thread_timestamps.py"
    spec = importlib.util.spec_from_file_location("channel_timestamp_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # This revision is portable UPDATE-only SQL; PostgreSQL's complete Alembic
    # chain is also exercised by CI's migration tests.
    engine = create_engine("sqlite://")
    try:
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            connection.execute(
                text(
                    "CREATE TABLE channel_sessions (id TEXT, thread_backfilled_at TEXT, conversation_id TEXT)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO channel_sessions VALUES ('old', '2026-10-29', 'conversation1'), ('new', NULL, 'conversation2')"
                )
            )
            for direction in (migration.upgrade, migration.upgrade, migration.downgrade):
                direction()
                assert connection.execute(
                    text(
                        "SELECT id, thread_backfilled_at, conversation_id FROM channel_sessions ORDER BY id"
                    )
                ).all() == [("new", None, "conversation2"), ("old", None, "conversation1")]
    finally:
        engine.dispose()
