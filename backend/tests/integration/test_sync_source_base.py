"""A sync source belongs to the knowledge base it records, asked of a real Postgres (#2551).

A source used to record an organization and a collection name only, and every
reader resolved its base again from the name - which is not unique. So an
organization base newer than a member's personal base of the same name lost its
sources to it, `rag-source-add` checked one base and wrote into another, and a
deleted base's sources went on syncing into whichever base kept the name, or
unfiled into none. These seed the colliding names those failures need and
assert each against the rows Postgres holds: the foreign key, its `SET NULL`,
the scheduler's query and the upgrade's backfill are all things a mock cannot
show.
"""

import importlib.util
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import anyio
import pytest
from click.testing import CliRunner, Result
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import RAGDocument
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import knowledge_base_repo
from app.repositories import sync_source as sync_source_repo
from app.schemas.sync_source import SyncSourceCreate
from app.services.collection_access import CollectionAccessService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.sync_source import SyncSourceService
from app.worker.tasks import rag_tasks

pytestmark = [pytest.mark.anyio, pytest.mark.security]

NAME = "handbook"


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )


async def _org(db: AsyncSession, owner: User) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=organization.id, user_id=owner.id, role="owner"
        )
    )
    await db.flush()
    return organization


def _base(
    organization_id: uuid.UUID | None,
    *,
    scope: KBScope = KBScope.ORG,
    owner: uuid.UUID | None = None,
    name: str = NAME,
    age: timedelta = timedelta(0),
) -> KnowledgeBase:
    """A base on `name`, `age` older than now - `created_at` orders a shared name."""
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        scope=scope.value,
        collection_name=name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        organization_id=organization_id,
        owner_user_id=owner,
        visibility={KBScope.ORG: "org", KBScope.PERSONAL: "private"}.get(scope),
        created_at=datetime.now(UTC) - age,
    )


def _source(
    organization_id: uuid.UUID, *, kb: KnowledgeBase | None, name: str = NAME
) -> SyncSource:
    return SyncSource(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name="Drive",
        connector_type="gdrive",
        collection_name=name,
        knowledge_base_id=None if kb is None else kb.id,
        config={"folder_id": "abc"},
        is_active=True,
    )


def _owner(user: User, organization: Organization) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=organization.id, role=OrgRoleName.OWNER)


def _same_session(db: AsyncSession) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    return session


async def _documents(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(RAGDocument)) or 0)


class TestAnOrgBaseNewerThanAPersonalBaseOfTheName:
    """RR-c8n2: resolved by name, the organization's oldest base of the name took
    every source - here a member's personal base created before the org base."""

    async def _seed(self, db: AsyncSession) -> dict[str, object]:
        owner = _user()
        db.add(owner)
        await db.flush()
        organization = await _org(db, owner)
        personal = _base(
            organization.id, scope=KBScope.PERSONAL, owner=owner.id, age=timedelta(days=1)
        )
        org_base = _base(organization.id)
        db.add_all([personal, org_base])
        await db.flush()
        ctx = _owner(owner, organization)
        read = await SyncSourceService(db).create_source(
            SyncSourceCreate(
                name="Drive",
                connector_type="gdrive",
                collection_name=NAME,
                config={"folder_id": "a"},
            ),
            ctx=ctx,
            knowledge_base=org_base,
        )
        source = await sync_source_repo.get_by_id(db, uuid.UUID(read.id))
        assert source is not None
        return {"personal": personal, "org_base": org_base, "ctx": ctx, "source": source}

    async def test_the_org_base_lists_and_reaches_its_own_source(self, db: AsyncSession) -> None:
        seeded = await self._seed(db)
        access = CollectionAccessService(db)
        source, ctx = seeded["source"], seeded["ctx"]
        org_base, personal = seeded["org_base"], seeded["personal"]
        assert isinstance(source, SyncSource) and isinstance(ctx, AuthContext)
        assert isinstance(org_base, KnowledgeBase) and isinstance(personal, KnowledgeBase)

        assert source.knowledge_base_id == org_base.id
        assert [s.id for s in await access.kb_sync_sources(ctx, org_base)] == [source.id]
        assert await access.kb_sync_sources(ctx, personal) == []
        assert (await access.kb_sync_source(org_base, str(source.id))).id == source.id
        with pytest.raises(NotFoundError):
            await access.kb_sync_source(personal, str(source.id))
        logs = await access.readable_sync_log_scope(ctx, NAME)
        assert logs.sync_source_ids == [source.id]

    async def test_its_sync_writes_under_the_org_base(self, db: AsyncSession) -> None:
        """The content: the sync stamps and scopes every row by the base it reads here."""
        seeded = await self._seed(db)
        source, org_base = seeded["source"], seeded["org_base"]
        assert isinstance(source, SyncSource) and isinstance(org_base, KnowledgeBase)

        kb = await rag_tasks._source_knowledge_base(db, source)

        assert kb is not None and kb.id == org_base.id
        assert kb.vector_scope.knowledge_base_id == org_base.id


class TestASourceOnlyGoesWhereItsCallerMayWrite:
    """RR-s7n1: the API checks write access to the base a source records, and the
    CLI records the organization base it checked - not whichever base the name
    resolves to later."""

    async def test_the_api_refuses_a_base_the_member_cannot_write(self, db: AsyncSession) -> None:
        owner, member = _user(), _user()
        db.add_all([owner, member])
        await db.flush()
        organization = await _org(db, owner)
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=organization.id, user_id=member.id, role="member"
            )
        )
        private = _base(organization.id, owner=owner.id)
        private.visibility = "private"
        db.add(private)
        await db.flush()
        ctx = AuthContext(
            user_id=member.id, organization_id=organization.id, role=OrgRoleName.MEMBER
        )

        with pytest.raises(NotFoundError):
            await CollectionAccessService(db).source_target(ctx, NAME)
        with pytest.raises(NotFoundError):
            await KnowledgeBaseService(db).get_for_write(private.id, ctx=ctx)
        with pytest.raises(BadRequestError):
            # Named, with no base resolved for it, the service refuses too.
            await SyncSourceService(db).create_source(
                SyncSourceCreate(
                    name="Drive",
                    connector_type="gdrive",
                    collection_name=NAME,
                    config={"folder_id": "a"},
                ),
                ctx=ctx,
            )
        assert await sync_source_repo.get_all(db, organization_id=organization.id) == []

    @staticmethod
    async def _cli(schema_url: str, *args: str) -> Result:
        """`rag-source-add` as an operator runs it: its own loop, its own session."""
        from app.commands import rag as rag_command

        @asynccontextmanager
        async def session() -> AsyncIterator[AsyncSession]:
            engine = create_async_engine(schema_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    yield db
                    await db.commit()
            finally:
                await engine.dispose()

        def invoke() -> Result:
            return CliRunner().invoke(rag_command.rag_source_add, list(args))

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(rag_command, "get_db_context", session)
            return await anyio.to_thread.run_sync(invoke)

    @staticmethod
    def _args(organization: Organization) -> list[str]:
        return [
            "--name",
            "Drive",
            "--type",
            "gdrive",
            "--org",
            str(organization.id),
            "--collection",
            NAME,
            "--config",
            '{"folder_id": "abc"}',
        ]

    async def test_the_cli_records_the_org_base_not_an_older_personal_one(
        self, engine: AsyncEngine, schema_url: str
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            owner = _user()
            db.add(owner)
            await db.flush()
            organization = await _org(db, owner)
            personal = _base(
                organization.id, scope=KBScope.PERSONAL, owner=owner.id, age=timedelta(days=1)
            )
            org_base = _base(organization.id)
            db.add_all([personal, org_base])
            await db.commit()

        result = await self._cli(schema_url, *self._args(organization))

        assert result.exit_code == 0, result.output
        async with factory() as db:
            [source] = await sync_source_repo.get_all(db, organization_id=organization.id)
            assert source.knowledge_base_id == org_base.id
            kb = await rag_tasks._source_knowledge_base(db, source)
            assert kb is not None and kb.id == org_base.id

    async def test_the_cli_refuses_a_name_only_a_personal_base_holds(
        self, engine: AsyncEngine, schema_url: str
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            owner = _user()
            db.add(owner)
            await db.flush()
            organization = await _org(db, owner)
            db.add(_base(organization.id, scope=KBScope.PERSONAL, owner=owner.id))
            await db.commit()

        result = await self._cli(schema_url, *self._args(organization))

        assert result.exit_code != 0
        async with factory() as db:
            assert await sync_source_repo.get_all(db, organization_id=organization.id) == []


class TestADeletedBasesSourcesStop:
    """Section 4: a deleted or dropped base's sources were left active while
    another base - another organization's, or an app-scoped one - kept the name,
    and synced into that base or unfiled into none."""

    async def _seed(self, db: AsyncSession, neighbour: str) -> dict[str, object]:
        owner_a, owner_b = _user(), _user()
        db.add_all([owner_a, owner_b])
        await db.flush()
        org_a, org_b = await _org(db, owner_a), await _org(db, owner_b)
        kb_a = _base(org_a.id)
        kept = _base(org_b.id) if neighbour == "org_b" else _base(None, scope=KBScope.APP)
        db.add_all([kb_a, kept])
        await db.flush()
        mine, theirs = _source(org_a.id, kb=kb_a), _source(org_b.id, kb=kept)
        db.add_all([mine, theirs])
        await db.flush()
        return {"kb_a": kb_a, "ctx": _owner(owner_a, org_a), "mine": mine, "theirs": theirs}

    @pytest.mark.parametrize("neighbour", ["org_b", "app"])
    @pytest.mark.parametrize("path", ["delete", "rag_drop"])
    async def test_exactly_its_sources_are_detached_and_write_nothing(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, neighbour: str, path: str
    ) -> None:
        seeded = await self._seed(db, neighbour)
        kb_a, ctx = seeded["kb_a"], seeded["ctx"]
        mine, theirs = seeded["mine"], seeded["theirs"]
        assert isinstance(kb_a, KnowledgeBase) and isinstance(ctx, AuthContext)
        assert isinstance(mine, SyncSource) and isinstance(theirs, SyncSource)
        kept_id = theirs.knowledge_base_id
        before = await _documents(db)

        if path == "delete":
            await KnowledgeBaseService(db).delete(kb_a.id, ctx=ctx)
        else:
            await KnowledgeBaseService(db).delete_for_rag_collection(kb_a)
        await db.refresh(mine)
        await db.refresh(theirs)

        assert (mine.collection_name, mine.knowledge_base_id, mine.is_active) == (
            None,
            None,
            False,
        )
        assert theirs.is_active and theirs.knowledge_base_id == kept_id
        with pytest.raises(BadRequestError):
            await SyncSourceService(db).trigger_sync(str(mine.id))
        monkeypatch.setattr(rag_tasks, "get_worker_db_context", _same_session(db))
        answer = await rag_tasks._sync_source(str(mine.id), None)
        assert answer["status"] == "error"
        assert await _documents(db) == before

    @pytest.mark.parametrize("path", ["delete_for_rag_collection", "rag_drop"])
    async def test_a_cleared_default_bases_sources_are_detached_too(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, path: str
    ) -> None:
        """A default base keeps its row when it is dropped, and its sources kept it:
        due again on the schedule, they refilled the collection just dropped, or -
        a connector whose remote version had not moved - ran clean over the stale
        sync state and left it empty for good. The drop stops them like any other."""
        seeded = await self._seed(db, "org_b")
        kb_a, mine, theirs = seeded["kb_a"], seeded["mine"], seeded["theirs"]
        assert isinstance(kb_a, KnowledgeBase)
        assert isinstance(mine, SyncSource) and isinstance(theirs, SyncSource)
        kb_a.is_default = True
        mine.schedule_minutes = 60
        mine.sync_state = {"version": "v1", "fingerprint": "f"}
        await db.flush()
        kept_id = theirs.knowledge_base_id

        if path == "delete_for_rag_collection":
            await KnowledgeBaseService(db).delete_for_rag_collection(kb_a)
        else:
            await KnowledgeBaseService(db).drop_collection_by_name(NAME, knowledge_base_id=kb_a.id)
        await db.refresh(mine)
        await db.refresh(theirs)

        assert await knowledge_base_repo.get_by_id(db, kb_a.id) is not None
        assert (mine.collection_name, mine.knowledge_base_id, mine.is_active) == (
            None,
            None,
            False,
        )
        assert theirs.is_active and theirs.knowledge_base_id == kept_id
        assert mine.id not in {s.id for s in await sync_source_repo.get_due_for_sync(db)}
        monkeypatch.setattr(rag_tasks, "get_worker_db_context", _same_session(db))
        answer = await rag_tasks._sync_source(str(mine.id), None)
        assert answer["status"] == "error"
        assert await _documents(db) == 0

    async def test_a_base_gone_without_the_teardown_leaves_a_source_that_writes_nothing(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The foreign key's `SET NULL` is the backstop behind the teardown: a source
        whose base vanished keeps its name, and is neither due nor synced by it."""
        seeded = await self._seed(db, "app")
        kb_a, mine = seeded["kb_a"], seeded["mine"]
        assert isinstance(kb_a, KnowledgeBase) and isinstance(mine, SyncSource)
        mine.schedule_minutes = 60
        await db.flush()
        await db.execute(text("DELETE FROM knowledge_bases WHERE id = :id"), {"id": kb_a.id})
        await db.refresh(mine)
        assert mine.knowledge_base_id is None and mine.collection_name == NAME and mine.is_active

        assert mine.id not in {s.id for s in await sync_source_repo.get_due_for_sync(db)}
        monkeypatch.setattr(rag_tasks, "get_worker_db_context", _same_session(db))
        answer = await rag_tasks._sync_source(str(mine.id), None)

        assert answer == {
            "status": "error",
            "message": "Source has no knowledge base. Assign it to one before syncing it again.",
        }
        assert await _documents(db) == 0


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0257_sync_source_knowledge_base.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0256_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheUpgradesBackfill:
    async def test_every_existing_source_gets_the_base_its_sync_resolved_to(
        self, db: AsyncSession
    ) -> None:
        """Today's choice, `choose_for_collection`, for every source naming a
        collection; a source no base of its organization or the deployment claims
        is deactivated and reported rather than attributed."""
        owner = _user()
        db.add(owner)
        await db.flush()
        org_1, org_2, org_3, org_4 = [await _org(db, owner) for _ in range(4)]
        personal = _base(org_1.id, scope=KBScope.PERSONAL, owner=owner.id, age=timedelta(days=3))
        org_1_base = _base(org_1.id, age=timedelta(days=1))
        app_base = _base(None, scope=KBScope.APP, age=timedelta(days=5))
        elsewhere = _base(org_1.id, name="manuals")
        # Two of org 4's bases share `created_at`, as a single transaction makes them.
        tied_a = _base(org_4.id, name="tied")
        tied_b = _base(org_4.id, name="tied")
        tied_b.created_at = tied_a.created_at
        db.add_all([personal, org_1_base, app_base, elsewhere, tied_a, tied_b])
        await db.flush()
        oldest_of_org = _source(org_1.id, kb=None)
        app_fallback = _source(org_2.id, kb=None)
        unattributable = _source(org_3.id, kb=None, name="manuals")
        # Already off: left unattributed, but not reported as deactivated by the upgrade.
        paused = _source(org_3.id, kb=None, name="manuals")
        paused.is_active = False
        template = _source(org_1.id, kb=None)
        template.collection_name = None
        already = _source(org_1.id, kb=org_1_base)
        tie = _source(org_4.id, kb=None, name="tied")
        db.add_all([oldest_of_org, app_fallback, unattributable, paused, template, already, tie])
        await db.flush()
        expected = {}
        for source in (oldest_of_org, app_fallback, unattributable):
            assert source.collection_name is not None
            chosen = knowledge_base_repo.choose_for_collection(
                await knowledge_base_repo.list_by_collection_name(db, source.collection_name),
                source.organization_id,
            )
            expected[source.id] = None if chosen is None else chosen.id

        migration = _migration()
        reported = await db.run_sync(lambda session: migration.backfill(session.connection()))
        on_personal = await db.run_sync(
            lambda session: migration.on_a_personal_base(session.connection())
        )
        for source in (oldest_of_org, app_fallback, unattributable, paused, template, already, tie):
            await db.refresh(source)

        assert expected == {
            oldest_of_org.id: personal.id,
            app_fallback.id: app_base.id,
            unattributable.id: None,
        }
        for source in (oldest_of_org, app_fallback, unattributable):
            assert source.knowledge_base_id == expected[source.id]
        assert oldest_of_org.is_active and app_fallback.is_active
        assert not unattributable.is_active and unattributable.collection_name == "manuals"
        assert sorted(reported) == sorted(
            [
                (str(unattributable.id), str(org_3.id), "manuals", False),
                # The earlier code ordered by `created_at` alone: no defined winner.
                (str(tie.id), str(org_4.id), "tied", True),
            ]
        )
        assert tie.knowledge_base_id is None and not tie.is_active
        assert paused.knowledge_base_id is None and not paused.is_active
        # Kept where it synced, and reported: org 1 also has an org base of the name.
        assert on_personal == [(str(oldest_of_org.id), str(org_1.id), NAME)]
        assert template.knowledge_base_id is None and template.is_active
        assert already.knowledge_base_id == org_1_base.id


class TestTheDowngrade:
    async def test_a_source_on_a_base_its_name_does_not_resolve_to_is_stopped(
        self, db: AsyncSession
    ) -> None:
        """The column is the only record of a source's base. Dropped, the earlier
        code resolves the name to the oldest base, so a source pinned to another
        one would sync there - into another audience - unless it is stopped."""
        owner = _user()
        db.add(owner)
        await db.flush()
        organization = await _org(db, owner)
        # #2551's own case: a member's older personal base, the organization's newer one.
        oldest = _base(
            organization.id, scope=KBScope.PERSONAL, owner=owner.id, age=timedelta(days=2)
        )
        newer = _base(organization.id, age=timedelta(days=1))
        db.add_all([oldest, newer])
        await db.flush()
        tied_a = _base(organization.id, name="tied")
        tied_b = _base(organization.id, name="tied")
        tied_b.created_at = tied_a.created_at
        db.add_all([tied_a, tied_b])
        await db.flush()
        on_newer = _source(organization.id, kb=newer)
        on_oldest = _source(organization.id, kb=oldest)
        paused = _source(organization.id, kb=newer)
        paused.is_active = False
        on_a_tie = _source(organization.id, kb=tied_a, name="tied")
        # Its base went without the teardown: the foreign key set it to NULL.
        unpinned = _source(organization.id, kb=None)
        template = _source(organization.id, kb=None)
        template.collection_name = None
        db.add_all([on_newer, on_oldest, paused, on_a_tie, unpinned, template])
        await db.flush()

        migration = _migration()
        reported = await db.run_sync(
            lambda session: migration.deactivate_diverging(session.connection())
        )
        for source in (on_newer, on_oldest, paused, on_a_tie, unpinned, template):
            await db.refresh(source)

        assert sorted(reported) == sorted(
            [
                (str(on_newer.id), str(organization.id), NAME),
                # No single base the earlier code would pick: stopped as well.
                (str(on_a_tie.id), str(organization.id), "tied"),
                # This revision never syncs it; the earlier code would, by name.
                (str(unpinned.id), str(organization.id), NAME),
            ]
        )
        assert not on_a_tie.is_active and not unpinned.is_active
        assert template.is_active
        assert not on_newer.is_active
        assert on_oldest.is_active
        assert not paused.is_active
