"""The unpublished quote migration preserves old runs and full monetary precision."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.eval_run import EvalRunRequest
from app.services.eval_run import EvalRunService
from tests.integration.test_eval_runs import _agent, _dataset, _owner
from tests.integration.test_eval_runs import _environment as _environment

pytestmark = pytest.mark.anyio


async def test_quote_migration_roundtrip_preserves_existing_runs(db: AsyncSession) -> None:
    ctx = await _owner(db)
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=1)
    started = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    await db.flush()
    path = Path(__file__).parents[2] / "alembic/versions/0386_eval_run_quoted_usd.py"
    spec = importlib.util.spec_from_file_location("quote_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db.connection()

    def cycle(conn: Connection) -> None:
        operations = Operations(MigrationContext.configure(conn))
        with patch.object(migration, "op", operations):
            migration.downgrade()
            assert conn.scalar(text("SELECT count(*) FROM eval_runs")) == 1
            migration.upgrade()
            assert conn.execute(
                text("SELECT quoted_usd, grading_estimate_usd FROM eval_runs")
            ).one() == (None, 0)
            conn.execute(
                text(
                    "UPDATE eval_runs SET quoted_usd=1000000.123456, grading_estimate_usd=0.000001"
                )
            )
            assert conn.scalar(text("SELECT quoted_usd::text FROM eval_runs")) == "1000000.123456"
            assert (
                conn.scalar(text("SELECT grading_estimate_usd::text FROM eval_runs")) == "0.000001"
            )
            migration.downgrade()
            assert conn.scalar(text("SELECT count(*) FROM eval_runs")) == 1
            migration.upgrade()

    await connection.run_sync(cycle)
    assert started.id is not None
