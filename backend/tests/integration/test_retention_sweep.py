"""The sweep against a real database: what leaves, and what survives it (#1420).

A unit test can assert that a delete was called. It cannot assert that a
conversation's messages went with it, that a run's manifest did, or - the one
that matters most - that the month's bill did not. Every one of those is a
cascade or a sum the ORM performs, which is exactly what a mocked session is
happy to pretend it did.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.conversation import Conversation, Message
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.memory import AgentMemoryFile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import RAGDocument
from app.db.models.run_manifest import RunManifest
from app.db.models.user import User
from app.schemas.retention import RetentionUpdate
from app.services.retention import RetentionService
from app.services.spend import organization_spend_since

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


async def _tenant(db: AsyncSession) -> tuple[Organization, User]:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    return organization, user


async def _conversation(
    db: AsyncSession, organization: Organization, user: User, *, age_days: int
) -> Conversation:
    conversation = Conversation(organization_id=organization.id, user_id=user.id, title="A thread")
    db.add(conversation)
    await db.flush()
    db.add(Message(conversation_id=conversation.id, ordinal=1, role="user", content="hello"))
    await db.flush()
    # Written after the insert, because `updated_at` is maintained on write.
    conversation.updated_at = NOW - timedelta(days=age_days)
    await db.flush()
    return conversation


async def _run(
    db: AsyncSession, organization: Organization, user: User, *, age_days: int, cost: str
) -> AgentRun:
    agent = Agent(
        organization_id=organization.id,
        name="Support",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    run = AgentRun(
        organization_id=organization.id,
        agent_id=agent.id,
        user_id=user.id,
        surface=RunSurface.API.value,
        status=RunStatus.COMPLETED,
        started_at=NOW - timedelta(days=age_days),
        cost_usd=Decimal(cost),
    )
    db.add(run)
    await db.flush()
    db.add(RunManifest(run_id=run.id, organization_id=organization.id, payload={"steps": []}))
    await db.flush()
    return run


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


class TestWhatLeaves:
    async def test_an_expired_conversation_takes_its_messages_with_it(self, db: AsyncSession):
        organization, user = await _tenant(db)
        old = await _conversation(db, organization, user, age_days=120)
        recent = await _conversation(db, organization, user, age_days=3)
        organization.retention_days = {"conversations": 30}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        remaining = (await db.execute(select(Conversation.id))).scalars().all()
        assert list(remaining) == [recent.id]
        assert await _count(db, Message) == 1
        assert old.id not in remaining

    async def test_an_expired_run_takes_its_manifest_with_it(self, db: AsyncSession):
        organization, user = await _tenant(db)
        await _run(db, organization, user, age_days=120, cost="2.50")
        organization.retention_days = {"runs": 30}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        assert await _count(db, AgentRun) == 0
        assert await _count(db, RunManifest) == 0

    async def test_a_thread_still_being_used_is_not_old(self, db: AsyncSession):
        """`updated_at`, not `created_at`: a conversation somebody is returning
        to is not old however long ago it started."""
        organization, user = await _tenant(db)
        conversation = await _conversation(db, organization, user, age_days=400)
        conversation.updated_at = NOW - timedelta(days=1)
        organization.retention_days = {"conversations": 30}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        assert await _count(db, Conversation) == 1


class TestWhatSurvives:
    async def test_the_month_still_bills_for_a_purged_run(self, db: AsyncSession):
        """The whole reason `purged_run_spend` exists. An organization on a
        thirty-day run retention would otherwise watch its month-to-date fall to
        zero as the window passed, and a cap metered on that figure would stop
        enforcing for the rest of the month."""
        organization, user = await _tenant(db)
        month_start = NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        await _run(db, organization, user, age_days=11, cost="4.25")
        await _run(db, organization, user, age_days=1, cost="1.00")
        organization.retention_days = {"runs": 7}
        await db.flush()
        before = await organization_spend_since(db, organization.id, month_start)

        await RetentionService(db).sweep(now=NOW)

        assert await _count(db, AgentRun) == 1
        assert await organization_spend_since(db, organization.id, month_start) == before
        assert before == Decimal("5.25")

    async def test_a_second_sweep_adds_to_the_month_rather_than_replacing_it(
        self, db: AsyncSession
    ):
        """A month is reached by several batches and several sweeps; a replace
        would leave it holding whatever the last one happened to contain."""
        organization, user = await _tenant(db)
        month_start = NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        await _run(db, organization, user, age_days=11, cost="4.25")
        organization.retention_days = {"runs": 7}
        await db.flush()
        await RetentionService(db).sweep(now=NOW)

        await _run(db, organization, user, age_days=12, cost="0.75")
        await db.flush()
        await RetentionService(db).sweep(now=NOW)

        assert await organization_spend_since(db, organization.id, month_start) == Decimal("5.00")

    @pytest.mark.security
    async def test_another_tenants_rows_are_not_swept_by_this_policy(self, db: AsyncSession):
        """Retention is per organization, and a query that spanned tenants would
        be one mistake away from purging under the wrong policy."""
        mine, me = await _tenant(db)
        theirs, them = await _tenant(db)
        await _conversation(db, mine, me, age_days=120)
        await _conversation(db, theirs, them, age_days=120)
        mine.retention_days = {"conversations": 30}
        theirs.retention_days = {"conversations": None}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        rows = (await db.execute(select(Conversation.organization_id))).scalars().all()
        assert list(rows) == [theirs.id]


class TestTheOtherClasses:
    async def test_a_workspace_unused_past_its_window_goes(self, db: AsyncSession):
        organization, user = await _tenant(db)
        agent = Agent(
            organization_id=organization.id,
            name="Support",
            created_by_user_id=user.id,
            slug=f"a-{uuid.uuid4().hex[:8]}",
        )
        db.add(agent)
        await db.flush()
        for age in (120, 2):
            db.add(
                AgentWorkspace(
                    organization_id=organization.id,
                    agent_id=agent.id,
                    scope="agent",
                    scope_key=f"k-{uuid.uuid4().hex[:8]}",
                    backend="state",
                    files={},
                    last_used_at=NOW - timedelta(days=age),
                )
            )
        organization.retention_days = {"workspaces": 30}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        assert await _count(db, AgentWorkspace) == 1

    async def test_a_memory_file_untouched_past_its_window_goes(self, db: AsyncSession):
        """`updated_at` matters most here: a note is written once and read for
        months, so an age measured from creation would delete precisely what an
        agent relies on most."""
        organization, user = await _tenant(db)
        agent = Agent(
            organization_id=organization.id,
            name="Support",
            created_by_user_id=user.id,
            slug=f"a-{uuid.uuid4().hex[:8]}",
        )
        db.add(agent)
        await db.flush()
        stale = AgentMemoryFile(
            organization_id=organization.id, agent_id=agent.id, owner_key="user:1", name="old"
        )
        fresh = AgentMemoryFile(
            organization_id=organization.id, agent_id=agent.id, owner_key="user:1", name="new"
        )
        db.add_all([stale, fresh])
        await db.flush()
        stale.updated_at = NOW - timedelta(days=200)
        fresh.updated_at = NOW - timedelta(days=2)
        organization.retention_days = {"memory": 30}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        names = (await db.execute(select(AgentMemoryFile.name))).scalars().all()
        assert list(names) == ["new"]

    async def test_an_uploaded_document_goes_and_a_synced_one_does_not(self, db: AsyncSession):
        """A document a connector put there is that source's to remove: purging
        it here deletes a row the next `new_only` sync recreates from the same
        unchanged file, burning embedding spend to no effect."""
        organization, _ = await _tenant(db)
        uploaded = RAGDocument(
            organization_id=organization.id,
            collection_name="kb_main",
            filename="report.pdf",
            filetype="pdf",
            vector_document_id="vec-1",
            storage_path="uploads/report.pdf",
        )
        synced = RAGDocument(
            organization_id=organization.id,
            collection_name="kb_main",
            filename="synced.pdf",
            filetype="pdf",
            source_path="/drive/synced.pdf",
        )
        db.add_all([uploaded, synced])
        await db.flush()
        for row in (uploaded, synced):
            row.created_at = NOW - timedelta(days=200)
        organization.retention_days = {"knowledge_documents": 30}
        await db.flush()
        removed_vectors: list[tuple[str, str]] = []

        async def remove(collection: str, document_id: str) -> None:
            removed_vectors.append((collection, document_id))

        with patch("app.services.file_storage.delete_files_best_effort", new=AsyncMock()) as files:
            await RetentionService(db, remove_vectors=remove).sweep(now=NOW)

        remaining = (await db.execute(select(RAGDocument.filename))).scalars().all()
        assert list(remaining) == ["synced.pdf"]
        assert removed_vectors == [("kb_main", "vec-1")]
        files.assert_awaited_with(["uploads/report.pdf"])

    async def test_an_audit_entry_past_a_lowered_floor_goes(self, db: AsyncSession):
        """The floor is six years by default, so a deployment that retires audit
        sooner has said so with a number - which is what is exercised here."""
        organization, user = await _tenant(db)
        db.add(
            DeploymentSettings(singleton=True, signup_mode="open", audit_retention_floor_days=30)
        )
        # Written through `record_audit`, because the chain columns are its to
        # fill - a hand-built row cannot satisfy the hash chain's NOT NULLs.
        await record_audit(
            db,
            actor_user_id=user.id,
            organization_id=organization.id,
            action="agent.published",
        )
        await db.flush()
        entry = (await db.execute(select(AppAdminAuditLog))).scalars().one()
        entry.created_at = NOW - timedelta(days=400)
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        assert await _count(db, AppAdminAuditLog) == 1  # the sweep's own entry

    async def test_setting_a_period_is_stored_on_the_organization(self, db: AsyncSession):
        organization, user = await _tenant(db)
        db.add(
            OrganizationMember(
                organization_id=organization.id, user_id=user.id, role=OrgRoleName.OWNER
            )
        )
        await db.flush()

        read = await RetentionService(db).update(
            organization.id,
            RetentionUpdate(retention_days={"conversations": 45}),
            actor_user_id=user.id,
        )

        await db.refresh(organization)
        assert organization.retention_days == {"conversations": 45}
        assert read.effective["conversations"] == 45
