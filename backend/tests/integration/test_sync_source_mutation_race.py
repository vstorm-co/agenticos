"""Authorizing a change to a sync source holds the source until the change lands (#2745).

A source's `collection_name` decides which base it feeds, and so whose write
access a change to it takes. Read without a lock, that name can be moved between
the check and the write: a caller allowed on the old base then reconfigures,
deletes or runs a source now feeding a base they cannot write. The check and the
change are therefore made under a row lock, taken through the routes here because
it is each route's choice of resolver and the order of its locks that decide this.

Integration because a race is two transactions the database arbitrates, which a
mock cannot show.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.routes.v1 import knowledge_bases as kb_routes
from app.api.routes.v1 import rag as rag_routes
from app.core.background import discard_deferred
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_name
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import organization_repo, sync_source_repo, user_repo
from app.schemas.sync_source import SyncSourceUpdate
from app.services.access import COLLECTION
from app.services.collection_access import CollectionAccessService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.sharing import SharingService
from app.services.sync_source import SyncSourceService
from tests.integration.test_document_delete_mid_ingest import _until_a_statement_waits_on_a_lock

pytestmark = pytest.mark.anyio

_RENAMED = "Renamed by the member"
_SETTLED = 10


@dataclass
class _Estate:
    """Two bases of one organization, a member who writes only the first, and its source."""

    factory: async_sessionmaker[AsyncSession]
    owner: AuthContext
    member: AuthContext
    kb_id: uuid.UUID
    collection: str
    other_collection: str
    source_id: uuid.UUID

    async def stored(self) -> SyncSource | None:
        async with self.factory() as s:
            return await s.get(SyncSource, self.source_id)

    async def runs(self) -> int:
        async with self.factory() as s:
            return await s.scalar(select(func.count()).select_from(SyncLog)) or 0


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )


def _base(organization_id: uuid.UUID, collection: str) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection,
        scope="org",
        collection_name=collection,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=organization_id,
        visibility="private",
    )


@pytest.fixture
async def estate(engine: AsyncEngine) -> _Estate:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:12]
    async with factory() as s:
        owner, member = _user(), _user()
        s.add_all([owner, member])
        await s.flush()
        org = Organization(
            id=uuid.uuid4(),
            name="Acme",
            slug=f"acme-{suffix}",
            created_by_user_id=owner.id,
        )
        s.add(org)
        await s.flush()
        s.add_all(
            [
                OrganizationMember(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    user_id=owner.id,
                    role=OrgRoleName.OWNER.value,
                ),
                OrganizationMember(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    user_id=member.id,
                    role=OrgRoleName.VIEWER.value,
                ),
            ]
        )
        base, other = _base(org.id, f"race_a_{suffix}"), _base(org.id, f"race_b_{suffix}")
        s.add_all([base, other])
        await s.flush()
        owner_ctx = AuthContext(
            user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER.value
        )
        await SharingService(s).share(
            owner_ctx,
            base,
            resource_type=COLLECTION,
            subject_user_id=member.id,
            level=GrantLevel.EDIT,
        )
        source = SyncSource(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Drive",
            connector_type="gdrive",
            collection_name=base.collection_name,
            config={"folder_id": "abc"},
        )
        s.add(source)
        await s.commit()
    return _Estate(
        factory=factory,
        owner=owner_ctx,
        member=AuthContext(
            user_id=member.id, organization_id=org.id, role=OrgRoleName.VIEWER.value
        ),
        kb_id=base.id,
        collection=base.collection_name,
        other_collection=other.collection_name,
        source_id=source.id,
    )


type _Act = Callable[[_Estate, AuthContext], Awaitable[object]]


async def _committed(estate: _Estate, call: Callable[[AsyncSession], Awaitable[Any]]) -> object:
    """A route's handler on a session of its own, committed as `DBSession` would."""
    async with estate.factory() as s:
        result = await call(s)
        await s.commit()
        discard_deferred(s)
        return result


def _services(s: AsyncSession) -> dict[str, Any]:
    return {"sync_source_svc": SyncSourceService(s), "access": CollectionAccessService(s)}


def _kb_services(s: AsyncSession) -> dict[str, Any]:
    return {**_services(s), "service": KnowledgeBaseService(s)}


async def _rag_update(estate: _Estate, ctx: AuthContext) -> object:
    return await _committed(
        estate,
        lambda s: rag_routes.update_sync_source(
            source_id=str(estate.source_id),
            data=SyncSourceUpdate(name=_RENAMED),
            ctx=ctx,
            **_services(s),
        ),
    )


async def _rag_delete(estate: _Estate, ctx: AuthContext) -> object:
    return await _committed(
        estate,
        lambda s: rag_routes.delete_sync_source(
            source_id=str(estate.source_id), ctx=ctx, **_services(s)
        ),
    )


async def _rag_trigger(estate: _Estate, ctx: AuthContext) -> object:
    return await _committed(
        estate,
        lambda s: rag_routes.trigger_sync_source(
            source_id=str(estate.source_id), ctx=ctx, **_services(s)
        ),
    )


async def _kb_update(estate: _Estate, ctx: AuthContext) -> object:
    return await _committed(
        estate,
        lambda s: kb_routes.update_kb_sync_source(
            kb_id=estate.kb_id,
            source_id=estate.source_id,
            data=SyncSourceUpdate(name=_RENAMED),
            ctx=ctx,
            **_kb_services(s),
        ),
    )


async def _kb_delete(estate: _Estate, ctx: AuthContext) -> object:
    return await _committed(
        estate,
        lambda s: kb_routes.delete_kb_sync_source(
            kb_id=estate.kb_id, source_id=estate.source_id, ctx=ctx, **_kb_services(s)
        ),
    )


async def _kb_trigger(estate: _Estate, ctx: AuthContext) -> object:
    return await _committed(
        estate,
        lambda s: kb_routes.trigger_kb_sync_source(
            kb_id=estate.kb_id, source_id=estate.source_id, ctx=ctx, **_kb_services(s)
        ),
    )


_EVERY_MUTATION = pytest.mark.parametrize(
    "act",
    [_rag_update, _rag_delete, _rag_trigger, _kb_update, _kb_delete, _kb_trigger],
    ids=["rag-patch", "rag-delete", "rag-trigger", "kb-patch", "kb-delete", "kb-trigger"],
)


async def _until_it_waits_or_finishes(estate: _Estate, task: asyncio.Task[object]) -> None:
    """Back from the moment `task` is parked on a lock, or has already run its course.

    Finishing is an answer too: an action that took no lock never waits, and it
    is what the assertions after the competing commit have to catch.
    """
    waiting = asyncio.ensure_future(_until_a_statement_waits_on_a_lock(estate.factory))
    await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
    if waiting.done():
        # Neither parked nor finished is a test that raced nothing.
        waiting.result()
        return
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)


async def _while_committing(
    estate: _Estate, holder: AsyncSession, act: Callable[[], Awaitable[object]]
) -> object:
    """Run `act` against `holder`'s open transaction, then commit it and take the result."""
    task = asyncio.ensure_future(act())
    await _until_it_waits_or_finishes(estate, task)
    await holder.commit()
    return await asyncio.wait_for(task, timeout=_SETTLED)


class TestAMoveDuringTheCheck:
    """The check answers for where the source is when the change lands."""

    @pytest.mark.security
    @_EVERY_MUTATION
    async def test_a_source_moved_out_of_the_callers_reach_is_refused(
        self, estate: _Estate, act: _Act
    ) -> None:
        async with estate.factory() as mover:
            await sync_source_repo.update(
                mover, estate.source_id, collection_name=estate.other_collection
            )
            with pytest.raises(NotFoundError):
                await _while_committing(estate, mover, lambda: act(estate, estate.member))

        stored = await estate.stored()
        assert stored is not None
        assert stored.name == "Drive"
        assert stored.collection_name == estate.other_collection
        assert await estate.runs() == 0

    @pytest.mark.security
    @_EVERY_MUTATION
    async def test_a_source_deleted_during_the_wait_is_not_found(
        self, estate: _Estate, act: _Act
    ) -> None:
        async with estate.factory() as deleter:
            await sync_source_repo.delete(deleter, estate.source_id)
            with pytest.raises(NotFoundError):
                await _while_committing(estate, deleter, lambda: act(estate, estate.owner))

    async def test_a_source_moved_into_a_base_the_caller_writes_is_still_theirs(
        self, estate: _Estate
    ) -> None:
        """The wait re-reads the row; it refuses nothing the new base would allow."""
        async with estate.factory() as mover:
            await sync_source_repo.update(
                mover, estate.source_id, collection_name=estate.other_collection
            )
            await _while_committing(estate, mover, lambda: _rag_update(estate, estate.owner))

        stored = await estate.stored()
        assert stored is not None
        assert stored.name == _RENAMED
        assert stored.collection_name == estate.other_collection


class TestTheLockOrder:
    """The row lock comes after every lock another transaction holds while reaching for it."""

    async def test_a_move_takes_the_name_before_the_row(self, estate: _Estate) -> None:
        """A base's deletion detaches its sources under the name: name, then rows.

        A move holding the row while waiting for the name would be the other
        order, and the two would deadlock.
        """

        async def repoint() -> object:
            return await _committed(
                estate,
                lambda s: rag_routes.update_sync_source(
                    source_id=str(estate.source_id),
                    data=SyncSourceUpdate(collection_name=estate.collection),
                    ctx=estate.owner,
                    **_services(s),
                ),
            )

        async with estate.factory() as teardown:
            await hold_name(teardown, LockScope.COLLECTION_TEARDOWN, estate.collection)
            task = asyncio.ensure_future(repoint())
            await _until_a_statement_waits_on_a_lock(estate.factory)
            kb = await teardown.get(KnowledgeBase, estate.kb_id)
            assert kb is not None
            await CollectionAccessService(teardown).detach_sources_targeting(kb)
            await teardown.commit()
        await asyncio.wait_for(task, timeout=_SETTLED)

    @pytest.mark.parametrize("act", [_rag_trigger, _kb_trigger], ids=["rag", "kb"])
    @pytest.mark.parametrize("held", ["organization", "user"])
    async def test_a_run_takes_what_it_references_before_the_row(
        self, estate: _Estate, act: _Act, held: str
    ) -> None:
        """An organization purge or an account deletion locks those rows, then the source.

        A run inserts rows referencing both, so holding the source while its
        foreign keys wait for them would be the other order (#2682).
        """
        async with estate.factory() as deletion:
            if held == "organization":
                await organization_repo.get_by_id_for_update(deletion, estate.owner.organization_id)
            else:
                assert estate.owner.user_id is not None
                await user_repo.get_by_id_for_update(deletion, estate.owner.user_id)
            task = asyncio.ensure_future(act(estate, estate.owner))
            await _until_a_statement_waits_on_a_lock(estate.factory)
            # Refused at once if the run had taken the row before it started to wait.
            await deletion.execute(
                select(SyncSource.id)
                .where(SyncSource.id == estate.source_id)
                .with_for_update(nowait=True)
            )
            await deletion.commit()
        await asyncio.wait_for(task, timeout=_SETTLED)
        assert await estate.runs() == 1


class TestAReadDoesNotWait:
    async def test_reading_a_sources_runs_does_not_wait_for_a_change_to_it(
        self, estate: _Estate
    ) -> None:
        async with estate.factory() as writer:
            await sync_source_repo.update(writer, estate.source_id, name="Being renamed")
            async with estate.factory() as s:
                await asyncio.wait_for(
                    kb_routes.list_kb_sync_source_logs(
                        kb_id=estate.kb_id,
                        source_id=estate.source_id,
                        ctx=estate.member,
                        limit=20,
                        **_kb_services(s),
                    ),
                    timeout=_SETTLED,
                )
