"""Upgrade existing guards without allowing old unpinned passes to open them."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = pytest.mark.anyio


async def test_existing_guards_pin_their_own_judge_and_old_runs_remain_untrusted(
    db: AsyncSession,
) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0193_guard_judge_version.py"
    spec = importlib.util.spec_from_file_location("guard_judge_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def migrate(session: Session) -> None:
        connection = session.connection()
        connection.execute(
            text(
                "CREATE TEMP TABLE agents (id uuid, organization_id uuid, kind text, system_key text, current_version_id uuid) ON COMMIT DROP"
            )
        )
        connection.execute(
            text(
                "CREATE TEMP TABLE eval_suites (id int, organization_id uuid, pinned_dataset_version int, pinned_scoring jsonb) ON COMMIT DROP"
            )
        )
        connection.execute(text("CREATE TEMP TABLE eval_runs (id int) ON COMMIT DROP"))
        connection.execute(
            text("""
            INSERT INTO agents VALUES
            ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000010', 'judge', 'eval_judge', '00000000-0000-0000-0000-000000000101'),
            ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000010', 'judge', NULL, '00000000-0000-0000-0000-000000000102'),
            ('00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000020', 'judge', 'eval_judge', '00000000-0000-0000-0000-000000000103');
        """)
        )
        connection.execute(
            text("""
            INSERT INTO eval_suites VALUES
            (1, '00000000-0000-0000-0000-000000000010', 1, '{}'),
            (2, '00000000-0000-0000-0000-000000000010', 1, '{"judge":{"agent_id":"00000000-0000-0000-0000-000000000002"}}'),
            (3, '00000000-0000-0000-0000-000000000010', 1, '{"judge":{"agent_id":"00000000-0000-0000-0000-000000000003"}}'),
            (4, '00000000-0000-0000-0000-000000000010', NULL, NULL);
        """)
        )
        connection.execute(text("INSERT INTO eval_runs VALUES (1)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        rows = connection.execute(
            text("SELECT id, pinned_judge_version_id::text FROM eval_suites ORDER BY id")
        ).all()
        assert [(i, version) for i, version in rows] == [
            (1, "00000000-0000-0000-0000-000000000101"),
            (2, "00000000-0000-0000-0000-000000000102"),
            (3, None),
            (4, None),
        ]
        assert connection.execute(
            text("SELECT judge_pinned, judge_version_id FROM eval_runs")
        ).one() == (False, None)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(text("SELECT * FROM eval_runs")).one() == (1,)

    await db.run_sync(migrate)
