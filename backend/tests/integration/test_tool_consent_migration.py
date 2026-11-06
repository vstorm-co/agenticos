"""The scoped-consent revision preserves existing approvals and reverses cleanly."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_tool_consent_upgrade_and_downgrade_preserve_decisions(engine: AsyncEngine) -> None:
    spec = importlib.util.spec_from_file_location(
        "tool_consent_migration", Path("alembic/versions/0295_tool_approval_consent.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = f"consent_migration_{uuid4().hex}"
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await connection.execute(
            text(
                "CREATE TABLE tool_approvals (id integer PRIMARY KEY, organization_id uuid, decided_by_user_id uuid, tool_id varchar(100), status varchar(16), decided_via varchar(16))"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO tool_approvals (id, status, decided_via) VALUES (1, 'approved', 'click')"
            )
        )

        def change(sync_connection, direction: str) -> None:
            with Operations.context(MigrationContext.configure(sync_connection)):
                getattr(migration, direction)()

        await connection.run_sync(change, "upgrade")
        assert (
            await connection.scalar(text("SELECT remember_scope FROM tool_approvals WHERE id = 1"))
            is None
        )
        await connection.execute(
            text(
                "INSERT INTO tool_approvals (id, status, decided_via, remember_scope) VALUES (2, 'approved', 'click', 'conversation')"
            )
        )
        for scope, status, via in [
            ("everything", "approved", "click"),
            ("agent", "pending", "click"),
            ("agent", "approved", "standing"),
        ]:
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO tool_approvals (id, status, decided_via, remember_scope) VALUES (3, :status, :via, :scope)"
                        ),
                        {"status": status, "via": via, "scope": scope},
                    )
        await connection.run_sync(change, "downgrade")
        assert await connection.scalar(text("SELECT count(*) FROM tool_approvals")) == 2
        await connection.run_sync(change, "upgrade")
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM tool_approvals WHERE remember_scope IS NULL")
            )
            == 2
        )
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
