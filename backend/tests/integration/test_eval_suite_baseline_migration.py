"""Existing passes without a quality bar become non-passing baselines."""

import importlib.util
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = pytest.mark.anyio


async def test_baseline_backfill_preserves_real_passes_and_never_restores_invalid_ones(
    db: AsyncSession,
) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0192_eval_suite_baseline.py"
    spec = importlib.util.spec_from_file_location("eval_suite_baseline_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def backfill(session: Session) -> None:
        connection = session.connection()
        connection.execute(
            text(
                "CREATE TEMP TABLE eval_suite_results (id int PRIMARY KEY, "
                "status text NOT NULL CONSTRAINT ck_eval_suite_result_status "
                "CHECK (status IN ('pending', 'running', 'passed', 'failed', 'inconclusive', 'skipped', 'error')), "
                "threshold jsonb NOT NULL, summary jsonb, reason text) ON COMMIT DROP"
            )
        )
        for row_id, status, threshold, summary in (
            (1, "passed", {"min_pass_rate": None}, {"pass_rate": 0, "baseline_run_id": None}),
            (2, "passed", {"min_pass_rate": 0.8}, {"pass_rate": 1, "baseline_run_id": None}),
            (3, "passed", {"min_pass_rate": None}, {"pass_rate": 1, "baseline_run_id": "run-1"}),
            (4, "failed", {"min_pass_rate": None}, {"pass_rate": 0, "baseline_run_id": None}),
        ):
            connection.execute(
                text(
                    "INSERT INTO eval_suite_results VALUES (:id, :status, CAST(:threshold AS jsonb), CAST(:summary AS jsonb), NULL)"
                ),
                {
                    "id": row_id,
                    "status": status,
                    "threshold": json.dumps(threshold),
                    "summary": json.dumps(summary),
                },
            )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
            upgraded = {
                row.id: row.status
                for row in connection.execute(text("SELECT id, status FROM eval_suite_results"))
            }
            assert upgraded == {1: "baseline_set", 2: "passed", 3: "passed", 4: "failed"}
            migration.downgrade()
        restored = connection.execute(
            text("SELECT status, summary->>'message' FROM eval_suite_results WHERE id = 1")
        ).one()
        assert restored.status == "inconclusive"
        assert "without passing" in restored[1]

    await db.run_sync(backfill)
