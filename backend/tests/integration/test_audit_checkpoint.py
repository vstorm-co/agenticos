"""The audit chain's checkpoint, and the truncation it lets `audit-verify` catch.

The hash chain (#1622) cannot tell a truncated chain from a short one, or a deleted
chain from one that never existed - the survivors stay internally consistent. The
per-organization checkpoint (#1648) is the trusted high-water mark that closes that:
`record_audit` advances it beside every entry, and `verify_chain` reports a chain
whose head is behind it, or gone. These run against Postgres because the checkpoint
is a real upsert under the chain's advisory lock and `seq` is a real database
identity the checkpoint has to read back.

The database trigger that makes the checkpoint append-only lives in the migration,
not the models, so it is exercised in `tests/test_audit_checkpoint_migration.py`
against the real migration; here the schema comes from `create_all`, which is
enough for the detection these tests assert.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.audit import record_audit
from app.repositories import audit_log_repo
from app.services.audit import AuditService

pytestmark = pytest.mark.anyio


async def _write_chain(db, organization_id: uuid.UUID | None, count: int) -> None:
    for index in range(count):
        await record_audit(
            db,
            actor_user_id=uuid.uuid4(),
            action=f"agent.action.{index}",
            organization_id=organization_id,
        )
    await db.commit()


class TestTheCheckpointTracksTheChain:
    async def test_record_audit_advances_the_checkpoint_with_the_head(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 1)
        checkpoint = await audit_log_repo.checkpoint_for_org(db, organization_id=org)
        assert checkpoint is not None
        assert checkpoint.entry_count == 1

        await _write_chain(db, org, 1)
        db.expire_all()
        checkpoint = await audit_log_repo.checkpoint_for_org(db, organization_id=org)
        entries = await audit_log_repo.chain_for_org(db, organization_id=org)
        assert checkpoint.entry_count == 2
        assert checkpoint.max_seq == entries[-1].seq
        assert checkpoint.head_entry_hash == entries[-1].entry_hash

    async def test_an_intact_chain_with_a_checkpoint_verifies(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 4)
        result = await AuditService(db).verify_chain(org)
        assert result.first_break is None
        assert result.entries_checked == 4


class TestTruncationIsDetected:
    async def test_dropping_the_newest_entries_is_caught(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 5)
        entries = await audit_log_repo.chain_for_org(db, organization_id=org)

        # Truncate the tail: the surviving prefix stays hash-consistent, so only the
        # checkpoint reveals the chain used to reach further.
        await db.execute(
            text("DELETE FROM app_admin_audit_logs WHERE id = ANY(:ids)"),
            {"ids": [entries[-1].id, entries[-2].id]},
        )
        await db.commit()
        db.expire_all()

        result = await AuditService(db).verify_chain(org)
        assert result.first_break is not None
        assert result.first_break.entry_id is None
        assert "truncated" in result.first_break.reason.lower()

    async def test_deleting_a_whole_chain_is_caught_through_its_checkpoint(self, db) -> None:
        org = uuid.uuid4()
        await _write_chain(db, org, 3)

        await db.execute(
            text("DELETE FROM app_admin_audit_logs WHERE organization_id = :org"), {"org": org}
        )
        await db.commit()
        db.expire_all()

        # The org has no entries left, so it is surfaced only by its checkpoint.
        results = {r.organization_id: r for r in await AuditService(db).verify_all_chains()}
        assert org in results
        assert results[org].entries_checked == 0
        assert results[org].first_break is not None
        assert "missing" in results[org].first_break.reason.lower()

    async def test_a_deployment_chain_truncation_is_caught(self, db) -> None:
        """The null-organization chain gets a checkpoint too (one row, NULLS NOT
        DISTINCT), so tenant-less actions are as tamper-evident as any tenant's."""
        await _write_chain(db, None, 4)
        entries = await audit_log_repo.chain_for_org(db, organization_id=None)

        await db.execute(
            text("DELETE FROM app_admin_audit_logs WHERE id = :id"), {"id": entries[-1].id}
        )
        await db.commit()
        db.expire_all()

        result = await AuditService(db).verify_chain(None)
        assert result.first_break is not None
        assert "truncated" in result.first_break.reason.lower()
