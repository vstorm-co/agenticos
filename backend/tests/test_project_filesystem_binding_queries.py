"""The repository always carries tenant/binding/run predicates; real PG verifies their effect."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import project_filesystem_bindings as repo
from tests.test_project_filesystem_bindings import mount_rows

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_binding_and_lease_queries_retain_their_authority_keys() -> None:
    rows = mount_rows()
    db = MagicMock(spec=AsyncSession)
    db.scalar.return_value = rows.binding
    assert (
        await repo.binding_for_session(
            db,
            organization_id=rows.actor.organization_id,
            connection_id=rows.connection.id,
            session_name=rows.binding.session_name,
        )
        is rows.binding
    )
    statement = db.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    assert set(statement.params.values()) == {
        rows.actor.organization_id,
        rows.connection.id,
        rows.binding.session_name,
    }
    for locked in (False, True):
        assert await repo.binding_by_id(db, rows.binding.id, for_update=locked) is rows.binding
        sql = str(db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
        assert ("FOR UPDATE" in sql) is locked
    await repo.insert_binding(db, row=rows.binding)
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uq_project_filesystem_binding_session DO NOTHING" in sql
    assert await repo.create_lease(db, lease=rows.lease) is rows.lease
    db.add.assert_called_once_with(rows.lease)
    db.scalar.return_value = rows.lease
    assert (
        await repo.lease_for_binding(db, binding=rows.binding, lease_id=rows.lease.id) is rows.lease
    )
    statement = db.scalar.await_args.args[0].compile(dialect=postgresql.dialect())
    assert set(statement.params.values()) == {
        rows.lease.id,
        rows.binding.id,
        rows.actor.organization_id,
    }
    db.scalars = AsyncMock(return_value=[rows.lease])
    now = datetime.now(UTC)
    assert await repo.live_leases(db, binding=rows.binding, now=now) == [rows.lease]
    statement = db.scalars.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True}
    )
    assert "revoked_at IS NULL" in str(statement) and "expires_at >" in str(statement)
    assert "EXISTS" in str(statement) and "conversation_environments.state IN" in str(statement)
    assert {"starting", "ready"}.issubset(set(statement.params.values()))
    assert {rows.binding.id, rows.actor.organization_id, now}.issubset(
        set(statement.params.values())
    )
    result = MagicMock()
    db.execute.return_value = result
    for identity in (None, rows.lease.id):
        result.scalar_one_or_none.return_value = identity
        assert await repo.renew_lease(
            db,
            lease_id=rows.lease.id,
            run_id=rows.run.id,
            organization_id=rows.actor.organization_id,
            now=now,
            expires_at=now + timedelta(seconds=90),
        ) is (identity is not None)
        statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        assert {rows.lease.id, rows.run.id, rows.actor.organization_id, now}.issubset(
            set(statement.params.values())
        )
    await repo.revoke_lease(
        db,
        lease_id=rows.lease.id,
        run_id=rows.run.id,
        organization_id=rows.actor.organization_id,
        now=now,
    )
    statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert {rows.lease.id, rows.run.id, rows.actor.organization_id, now}.issubset(
        set(statement.params.values())
    )
    db.commit.assert_not_called()
