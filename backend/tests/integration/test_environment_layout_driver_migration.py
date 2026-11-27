"""Layout fencing is a real constraint and cannot be removed beneath live work."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_layout_constraint_round_trip_refuses_live_work_and_preserves_other_drivers(
    db: AsyncSession,
):
    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/0384_environment_layout_driver.py"
    )
    spec = importlib.util.spec_from_file_location("environment_layout_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0383_environment_project_files"

    def cycle(session: Session) -> None:
        connection = session.connection()
        insert = text(
            "INSERT INTO conversation_environment_drivers(resource_key,control,lease_token,lease_until) VALUES(:key,:control,:token,now()+interval '1 minute')"
        )
        for control in ("human", "agent", "layout"):
            connection.execute(insert, {"key": control, "control": control, "token": uuid4()})
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="active layout leases"):
                migration.downgrade()
            connection.execute(
                text(
                    "UPDATE conversation_environment_drivers SET lease_until=now()-interval '1 second' WHERE control='layout'"
                )
            )
            migration.downgrade()
            assert set(
                connection.execute(
                    text("SELECT control FROM conversation_environment_drivers")
                ).scalars()
            ) == {"human", "agent"}
            with connection.begin_nested() as savepoint:
                with pytest.raises(IntegrityError):
                    connection.execute(
                        insert, {"key": "layout", "control": "layout", "token": uuid4()}
                    )
                savepoint.rollback()
            migration.upgrade()
            connection.execute(insert, {"key": "layout", "control": "layout", "token": uuid4()})
            with connection.begin_nested() as savepoint:
                with pytest.raises(IntegrityError):
                    connection.execute(
                        insert, {"key": "invalid", "control": "arbitrary", "token": uuid4()}
                    )
                savepoint.rollback()
            checks = inspect(connection).get_check_constraints("conversation_environment_drivers")
            assert any("layout" in check["sqltext"] for check in checks)

    await db.run_sync(cycle)
