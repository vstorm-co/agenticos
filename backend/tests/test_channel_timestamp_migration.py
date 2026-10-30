"""Text-context version upgrades preserve the existing thread file marker."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_text_versions_upgrade_without_invalidating_the_file_backfill() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0179_channel_history_version.py"
    spec = importlib.util.spec_from_file_location("channel_timestamp_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
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
            for _ in range(2):
                migration.upgrade()
                assert connection.execute(
                    text("SELECT id, thread_history_version FROM channel_sessions ORDER BY id")
                ).all() == [("new", 0), ("old", 0)]
                connection.execute(text("UPDATE channel_sessions SET thread_history_version = 1"))
                migration.downgrade()
                assert connection.execute(
                    text(
                        "SELECT id, thread_backfilled_at, conversation_id FROM channel_sessions ORDER BY id"
                    )
                ).all() == [("new", None, "conversation2"), ("old", "2026-10-29", "conversation1")]
    finally:
        engine.dispose()
