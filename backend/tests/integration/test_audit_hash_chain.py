"""The audit trail's tamper-evidence chain, against Postgres.

A hash chain is exactly the thing a mocked session cannot vouch for: the head read
that `record_audit` links each entry to is a real `ORDER BY seq DESC LIMIT 1`, the
`seq` itself is a database identity, and whether two concurrent writes fork the
chain turns on a real advisory lock and a real transaction boundary. So these run
against a database.

What they hold: a written chain reads back and verifies with no false break -
including details that round-trip through JSONB - an edited or deleted row is
detected and named, and concurrent audited writes for one organization serialize
into a single unbroken chain rather than forking at a shared head (#1622).

The reads share the test's own `db` session, which the fixture rolls back and the
engine disposes; only the concurrency test needs more than one connection, and it
owns a dedicated engine it disposes itself, so no session is left holding
`app_admin_audit_logs` when the next test's reset truncates it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit import record_audit
from app.db.models.audit_log import AppAdminAuditLog
from app.repositories import audit_log_repo
from app.services.audit import AuditService

# The whole module carries `security`: tamper evidence over the audit trail is a
# control the matrix in `docs/security.md` names, and every test here holds one
# half of it - that an intact chain verifies, and that an edited or deleted row
# does not. Only `test_a_tenant_less_write_chains_and_verifies` trips the
# keyword net in `test_security_marker.py`, and marking that one alone would
# leave the two tamper-detection tests out of a set that exists to be counted.
pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _write_chain(db: AsyncSession, organization_id: uuid.UUID | None, count: int) -> None:
    for index in range(count):
        await record_audit(
            db,
            actor_user_id=uuid.uuid4(),
            action=f"agent.action.{index}",
            organization_id=organization_id,
            target_type="agent",
            target_id=uuid.uuid4(),
            details={"fields": ["name", "budget"], "version": index},
            ip_address="203.0.113.5",
        )
    await db.commit()


class TestRoundTrip:
    async def test_a_written_chain_reads_back_and_verifies(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)

        entries = await audit_log_repo.chain_for_org(db, organization_id=org)
        result = await AuditService(db).verify_chain(org)

        assert result.first_break is None
        assert result.entries_checked == 5
        # A real identity column assigns seq, monotonic in write order.
        assert [entry.seq for entry in entries] == sorted(entry.seq for entry in entries)
        assert entries[0].prev_hash is None
        assert all(entry.prev_hash is not None for entry in entries[1:])

    async def test_two_organizations_keep_independent_chains(self, db) -> None:
        org_a, org_b = uuid.uuid4(), uuid.uuid4()
        await _write_chain(db, org_a, 3)
        await _write_chain(db, org_b, 2)

        results = {r.organization_id: r for r in await AuditService(db).verify_all_chains()}

        assert results[org_a].first_break is None
        assert results[org_a].entries_checked == 3
        assert results[org_b].first_break is None
        assert results[org_b].entries_checked == 2


class TestTheDeploymentChain:
    async def test_a_tenant_less_write_chains_and_verifies(self, db) -> None:
        """`organization_id=None` is the deployment-wide chain, whose advisory-lock
        key is `-2147483648` - the `pg_advisory_xact_lock` overload trap that must
        not throw (#1622). Deployment settings, impersonation and app-admin user
        management all write here."""
        for index in range(3):
            await record_audit(
                db,
                actor_user_id=uuid.uuid4(),
                action=f"deployment.action.{index}",
                organization_id=None,
            )
        await db.commit()

        result = await AuditService(db).verify_chain(None)

        assert result.first_break is None
        assert result.entries_checked == 3


class TestTamperIsDetected:
    async def test_editing_a_stored_row_is_detected(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)
        entries = await audit_log_repo.chain_for_org(db, organization_id=org)
        victim = entries[2]

        await db.execute(
            text("UPDATE app_admin_audit_logs SET action = :action WHERE id = :id"),
            {"action": "agent.action.forged", "id": victim.id},
        )
        await db.commit()
        db.expire_all()  # so the verify re-reads the tampered row rather than the cached one

        result = await AuditService(db).verify_chain(org)

        assert result.first_break is not None
        assert result.first_break.seq == victim.seq
        assert result.first_break.entry_id == victim.id
        assert "entry_hash" in result.first_break.reason

    async def test_deleting_a_row_is_detected(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)
        entries = await audit_log_repo.chain_for_org(db, organization_id=org)
        removed, orphaned = entries[2], entries[3]

        await db.execute(
            text("DELETE FROM app_admin_audit_logs WHERE id = :id"), {"id": removed.id}
        )
        await db.commit()
        db.expire_all()

        result = await AuditService(db).verify_chain(org)

        assert result.first_break is not None
        # The entry after the hole now points at a hash the walk never arrives with.
        assert result.first_break.seq == orphaned.seq
        assert "prev_hash" in result.first_break.reason


class TestConcurrency:
    async def test_concurrent_writes_for_one_org_do_not_fork_the_chain(self, schema_url) -> None:
        """A dedicated engine, disposed here, so the several connections this test
        opens are its own and are gone before the next test's reset runs."""
        org = uuid.uuid4()
        writers = 6
        engine = create_async_engine(schema_url)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)

            async def write(index: int) -> None:
                async with factory() as session:
                    await record_audit(
                        session,
                        actor_user_id=uuid.uuid4(),
                        action=f"concurrent.{index}",
                        organization_id=org,
                    )
                    await session.commit()

            await asyncio.gather(*(write(index) for index in range(writers)))

            async with factory() as reader:
                entries = await audit_log_repo.chain_for_org(reader, organization_id=org)
                result = await AuditService(reader).verify_chain(org)
                heads = await reader.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.organization_id == org,
                        AppAdminAuditLog.prev_hash.is_(None),
                    )
                )
                head_count = len(heads.scalars().all())
        finally:
            await engine.dispose()

        assert result.first_break is None
        assert result.entries_checked == writers
        # Serialized, not forked: every seq distinct, one head, the rest linked.
        assert len({entry.seq for entry in entries}) == writers
        assert head_count == 1
        assert entries[0].prev_hash is None
        assert all(entry.prev_hash is not None for entry in entries[1:])
