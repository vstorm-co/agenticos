"""The retained-evidence backfill redacts nested JSON and is safe to repeat."""

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = pytest.mark.anyio


async def test_existing_eval_evidence_is_redacted_idempotently(db: AsyncSession) -> None:
    path = Path(__file__).parents[2] / "alembic/versions/0191_eval_evidence_redaction.py"
    spec = importlib.util.spec_from_file_location("eval_evidence_redaction_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    secret = "ghp_" + "r" * 36
    calls = [{"args": {"token": secret}, "result": [secret, 1, True, None]}]

    def backfill(session: Session) -> None:
        connection = session.connection()
        # A temporary table shadows the real one on this connection, avoiding
        # unrelated foreign keys while exercising the backfill against PostgreSQL.
        connection.execute(
            text(
                "CREATE TEMP TABLE eval_run_cases (id uuid PRIMARY KEY, answer text, "
                "calls jsonb NOT NULL, error text) ON COMMIT DROP"
            )
        )
        connection.execute(
            text("INSERT INTO eval_run_cases VALUES (:id, :answer, CAST(:calls AS jsonb), :error)"),
            {"id": uuid.uuid4(), "answer": secret, "calls": json.dumps(calls), "error": secret},
        )
        connection.execute(
            text("INSERT INTO eval_run_cases VALUES (:id, NULL, '[]'::jsonb, NULL)"),
            {"id": uuid.uuid4()},
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            once = [
                dict(row)
                for row in connection.execute(
                    text("SELECT * FROM eval_run_cases ORDER BY id")
                ).mappings()
            ]
            migration.upgrade()
            twice = [
                dict(row)
                for row in connection.execute(
                    text("SELECT * FROM eval_run_cases ORDER BY id")
                ).mappings()
            ]
        assert once == twice
        assert secret not in str(once)
        redacted = next(row for row in once if row["answer"] is not None)
        assert "[redacted:" in redacted["answer"]
        assert redacted["calls"][0]["result"][1:] == [1, True, None]
        assert sum(row["answer"] is None for row in once) == 1

    await db.run_sync(backfill)
