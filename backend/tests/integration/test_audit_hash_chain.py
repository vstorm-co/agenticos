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
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.audit import record_audit
from app.db.models.audit_log import AppAdminAuditLog
from app.repositories import audit_log_repo
from app.services.audit import AuditService

pytestmark = pytest.mark.anyio


async def _write_chain(db, organization_id: uuid.UUID, count: int) -> None:
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
    async def test_a_written_chain_reads_back_and_verifies(self, db, engine) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as reader:
            entries = await audit_log_repo.chain_for_org(reader, organization_id=org)
            result = await AuditService(reader).verify_chain(org)

        assert result.first_break is None
        assert result.entries_checked == 5
        # A real identity column assigns seq, monotonic in write order.
        assert [entry.seq for entry in entries] == sorted(entry.seq for entry in entries)
        assert entries[0].prev_hash is None
        assert all(entry.prev_hash is not None for entry in entries[1:])

    async def test_two_organizations_keep_independent_chains(self, db, engine) -> None:
        org_a, org_b = uuid.uuid4(), uuid.uuid4()
        await _write_chain(db, org_a, 3)
        await _write_chain(db, org_b, 2)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as reader:
            results = await AuditService(reader).verify_all_chains()

        by_org = {result.organization_id: result for result in results}
        assert by_org[org_a].first_break is None
        assert by_org[org_a].entries_checked == 3
        assert by_org[org_b].first_break is None
        assert by_org[org_b].entries_checked == 2


class TestTheDeploymentChain:
    async def test_a_tenant_less_write_chains_and_verifies(self, db, engine) -> None:
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

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as reader:
            result = await AuditService(reader).verify_chain(None)

        assert result.first_break is None
        assert result.entries_checked == 3


class TestTamperIsDetected:
    async def test_editing_a_stored_row_is_detected(self, db, engine) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as tamperer:
            entries = await audit_log_repo.chain_for_org(tamperer, organization_id=org)
            victim = entries[2]
            await tamperer.execute(
                text("UPDATE app_admin_audit_logs SET action = :action WHERE id = :id"),
                {"action": "agent.action.forged", "id": victim.id},
            )
            await tamperer.commit()

        async with factory() as reader:
            result = await AuditService(reader).verify_chain(org)

        assert result.first_break is not None
        assert result.first_break.seq == victim.seq
        assert result.first_break.entry_id == victim.id
        assert "entry_hash" in result.first_break.reason

    async def test_deleting_a_row_is_detected(self, db, engine) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as tamperer:
            entries = await audit_log_repo.chain_for_org(tamperer, organization_id=org)
            removed, orphaned = entries[2], entries[3]
            await tamperer.execute(
                text("DELETE FROM app_admin_audit_logs WHERE id = :id"), {"id": removed.id}
            )
            await tamperer.commit()

        async with factory() as reader:
            result = await AuditService(reader).verify_chain(org)

        assert result.first_break is not None
        # The entry after the hole now points at a hash the walk never arrives with.
        assert result.first_break.seq == orphaned.seq
        assert "prev_hash" in result.first_break.reason


class TestConcurrency:
    async def test_concurrent_writes_for_one_org_do_not_fork_the_chain(self, engine) -> None:
        org = uuid.uuid4()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        writers = 6

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

        assert result.first_break is None
        assert result.entries_checked == writers
        # Serialized, not forked: every seq distinct and every entry but the first
        # links to a real predecessor.
        assert len({entry.seq for entry in entries}) == writers
        assert entries[0].prev_hash is None
        assert all(entry.prev_hash is not None for entry in entries[1:])
        # A fork would have shown two entries with prev_hash NULL.
        heads = await reader.execute(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.organization_id == org, AppAdminAuditLog.prev_hash.is_(None)
            )
        )
        assert len(heads.scalars().all()) == 1
