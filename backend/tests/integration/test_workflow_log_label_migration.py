"""The label-origin migration preserves existing log snapshots, on real PostgreSQL."""

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.anyio


def _round_trip(connection: Connection) -> None:
    revision = ScriptDirectory.from_config(Config("alembic.ini")).get_revision(
        "0321_workflow_log_label_origin"
    )
    assert revision is not None
    # A temporary table shadows the real table only on this test's connection.
    connection.execute(
        text(
            "CREATE TEMP TABLE workflow_log_entries (step_label varchar(128) NOT NULL) ON COMMIT DROP"
        )
    )
    connection.execute(text("INSERT INTO workflow_log_entries VALUES ('Manual')"))
    with Operations.context(MigrationContext.configure(connection)):
        revision.module.upgrade()
        assert connection.execute(
            text("SELECT step_label, step_definition_id FROM workflow_log_entries")
        ).one() == ("Manual", None)
        connection.execute(
            text(
                "INSERT INTO workflow_log_entries (step_label, step_definition_id) VALUES ('API request', 'core.input')"
            )
        )
        revision.module.downgrade()
    assert connection.execute(
        text("SELECT step_label FROM workflow_log_entries ORDER BY step_label")
    ).scalars().all() == ["API request", "Manual"]


async def test_existing_labels_survive_upgrade_and_downgrade(db: AsyncSession) -> None:
    connection = await db.connection()
    await connection.run_sync(_round_trip)
