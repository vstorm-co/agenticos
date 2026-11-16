"""A paused sync source is not run by hand, and a name's candidates keep one order (#2744).

`is_active` is how an operator pauses a source without deleting it
(`docs/howto/configure-sync-sources.md`), but only the scheduler's query read
it: a manual trigger, from the API or the CLI, ran a paused source all the same.
The service refuses it before queueing, and the worker checks again when the
job starts because a source can be paused after it was queued.

`created_at` is `now()`, the transaction's start, so two bases inserted together
tie on it; `list_by_collection_name` then has to break the tie on something
stable, or the base a name resolves to depends on what the database returns.
"""

import contextlib
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.routes.v1 import knowledge_bases as kb_routes
from app.api.routes.v1 import org_integrations as integration_routes
from app.api.routes.v1 import rag as rag_routes
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import knowledge_base_repo
from app.services.collection_access import CollectionAccessService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.sync_source import SyncSourceService
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio

PAUSED_SOURCE = "This source is paused; activate it to sync."


async def _org(db: AsyncSession) -> Organization:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Org",
        slug=f"org-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


def _kb(
    organization_id: uuid.UUID, kb_id: uuid.UUID, collection_name: str, tied_at: datetime | None
) -> KnowledgeBase:
    return KnowledgeBase(
        id=kb_id,
        name=f"Base {kb_id.hex[:6]}",
        scope=KBScope.ORG.value,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=organization_id,
        visibility="org",
        created_at=tied_at,
    )


async def _source(db: AsyncSession, organization: Organization, **fields: object) -> SyncSource:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": organization.id,
        "name": "Docs",
        "connector_type": "web",
        "config": {},
        "collection_name": "docs",
        "is_active": True,
    }
    values.update(fields)
    source = SyncSource(**values)
    db.add(source)
    await db.flush()
    return source


class TestBasesTiedOnCreatedAt:
    async def test_deleting_a_tied_sibling_only_detaches_sources_of_the_chosen_base(
        self, db: AsyncSession
    ) -> None:
        organization = await _org(db)
        older = _kb(organization.id, uuid.UUID(int=1), "tied", None)
        sibling = _kb(organization.id, uuid.UUID(int=2), "tied", None)
        db.add_all([sibling, older])
        await db.flush()
        source = await _source(db, organization, collection_name="tied")
        access = CollectionAccessService(db)

        await access.detach_sources_targeting(sibling)
        await db.refresh(source)
        assert source.collection_name == "tied"
        assert source.is_active

        await access.detach_sources_targeting(older)
        await db.refresh(source)
        assert source.collection_name is None
        assert not source.is_active

    async def test_the_same_base_is_first_whichever_was_inserted_first(
        self, db: AsyncSession
    ) -> None:
        organization = await _org(db)
        tied_at = None
        low = uuid.UUID(int=1)
        high = uuid.UUID(int=2)
        # The later id goes in first, so a query with no tie-breaker would
        # answer in insertion order and name `high`.
        db.add(_kb(organization.id, high, "tied", tied_at))
        db.add(_kb(organization.id, low, "tied", tied_at))
        await db.flush()

        listed = await knowledge_base_repo.list_by_collection_name(db, "tied")
        by_name = await knowledge_base_repo.list_by_collection_names(db, ["tied"])
        chosen = await knowledge_base_repo.get_for_collection(db, "tied", organization.id)

        assert listed[0].created_at == listed[1].created_at
        assert [kb.id for kb in listed] == [low, high]
        assert [kb.id for kb in by_name["tied"]] == [low, high]
        assert chosen is not None and chosen.id == low


class TestAManualTriggerOfAPausedSource:
    """Each route that triggers a run refuses a paused source and queues nothing."""

    async def _estate(
        self, db: AsyncSession, *, is_active: bool
    ) -> tuple[AuthContext, KnowledgeBase, SyncSource]:
        organization = await _org(db)
        owner = organization.created_by_user_id
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=organization.id,
                user_id=owner,
                role=OrgRoleName.OWNER.value,
            )
        )
        kb = _kb(organization.id, uuid.uuid4(), "docs", datetime(2026, 1, 1, tzinfo=UTC))
        db.add(kb)
        await db.flush()
        source = await _source(db, organization, is_active=is_active)
        ctx = AuthContext(
            user_id=owner, organization_id=organization.id, role=OrgRoleName.OWNER.value
        )
        return ctx, kb, source

    async def _trigger(
        self, db: AsyncSession, route: str, ctx: AuthContext, kb: KnowledgeBase, source: SyncSource
    ) -> object:
        sync_source_svc, access = SyncSourceService(db), CollectionAccessService(db)
        if route == "rag":
            return await rag_routes.trigger_sync_source(
                source_id=str(source.id), sync_source_svc=sync_source_svc, access=access, ctx=ctx
            )
        if route == "integration":
            return await integration_routes.trigger_org_integration(
                source_id=source.id, sync_source_svc=sync_source_svc, access=access, ctx=ctx
            )
        return await kb_routes.trigger_kb_sync_source(
            kb_id=kb.id,
            source_id=source.id,
            service=KnowledgeBaseService(db),
            sync_source_svc=sync_source_svc,
            access=access,
            ctx=ctx,
        )

    @pytest.mark.parametrize("route", ["rag", "integration", "kb"])
    async def test_is_refused_and_leaves_no_log(self, db: AsyncSession, route: str) -> None:
        ctx, kb, source = await self._estate(db, is_active=False)

        with pytest.raises(BadRequestError) as refused:
            await self._trigger(db, route, ctx, kb, source)

        assert refused.value.message == PAUSED_SOURCE
        assert await db.scalar(_count_logs(source.id)) == 0

    @pytest.mark.parametrize("route", ["rag", "integration", "kb"])
    async def test_an_active_source_is_still_triggered(self, db: AsyncSession, route: str) -> None:
        ctx, kb, source = await self._estate(db, is_active=True)

        await self._trigger(db, route, ctx, kb, source)

        assert await db.scalar(_count_logs(source.id)) == 1


def _count_logs(source_id: uuid.UUID) -> Select[int]:
    return select(func.count()).select_from(SyncLog).where(SyncLog.sync_source_id == source_id)


@pytest.mark.parametrize("has_log", [False, True])
async def test_a_job_that_finds_its_source_paused_ends_without_syncing(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, has_log: bool
) -> None:
    """Paused between the trigger and the job: the log is finished as an error."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        organization = await _org(db)
        source = await _source(db, organization)
        log = await SyncSourceService(db).trigger_sync(str(source.id)) if has_log else None
        source.is_active = False
        await db.commit()
        source_id, log_id = str(source.id), str(log.id) if log is not None else None

    @contextlib.asynccontextmanager
    async def worker_db() -> AsyncGenerator[AsyncSession]:
        async with factory() as db:
            yield db
            await db.commit()

    credential = AsyncMock()
    monkeypatch.setattr(rag_tasks, "get_worker_db_context", worker_db)
    monkeypatch.setattr(rag_tasks, "_connector_credential", credential)
    monkeypatch.setattr(rag_tasks, "_knowledge_base_for", AsyncMock(return_value=None))
    monkeypatch.setattr(rag_tasks.NotificationService, "sync_failed", AsyncMock())

    answer = await rag_tasks._sync_source(source_id, log_id)

    assert answer == {"status": "error", "message": PAUSED_SOURCE}
    credential.assert_not_awaited()
    async with factory() as db:
        paused = await db.get(SyncSource, uuid.UUID(source_id))
        assert paused is not None
        assert paused.last_sync_status == "error"
        assert paused.last_error == PAUSED_SOURCE
        assert await db.scalar(_count_logs(paused.id)) == int(has_log)
        if log_id is not None:
            finished = await db.get(SyncLog, uuid.UUID(log_id))
            assert finished is not None
            assert finished.status == "error"
            assert finished.error_message == PAUSED_SOURCE
            assert finished.completed_at is not None
