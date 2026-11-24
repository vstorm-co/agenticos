"""A pre-existing compacted thread must not reimport legacy messages on upgrade."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_upgrade_preserves_legacy_progress_and_can_be_reversed() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0333_channel_thread_context.py"
    spec = importlib.util.spec_from_file_location("channel_runtime_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            connection.execute(text("CREATE TABLE agent_runs (id UUID PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE conversations (id UUID PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE channel_sessions (id TEXT, last_message_at TEXT, thread_history_version INTEGER)"
                )
            )
            connection.execute(
                text("INSERT INTO channel_sessions VALUES ('old','2026-11-16',1), ('new',NULL,0)")
            )
            for _ in range(2):
                migration.upgrade()
                assert connection.execute(
                    text("SELECT id,thread_context_at FROM channel_sessions ORDER BY id")
                ).all() == [("new", None), ("old", "2026-11-16")]
                migration.downgrade()
                assert connection.execute(
                    text("SELECT id,last_message_at FROM channel_sessions ORDER BY id")
                ).all() == [("new", None), ("old", "2026-11-16")]
    finally:
        engine.dispose()
