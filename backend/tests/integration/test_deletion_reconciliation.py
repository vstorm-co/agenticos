"""Deleting a user or an org no longer 500s on a cascade the schema forbids.

Three `ON DELETE SET NULL`/RESTRICT cascades each drove precisely the write a
CHECK constraint rejects, so the delete raised inside the database and surfaced
as a 500 (#9). Each is reconciled in the service before the row goes: a private
secret is promoted to the org, a personal org is removed with its owner, and an
org-scoped collection is deleted - table and all - rather than orphaned.

Integration rather than unit because the whole point is what the database does
to neighbouring rows when one is deleted, which a mock cannot show.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.background import discard_deferred, drain, start_deferred
from app.core.config import settings as app_settings
from app.core.exceptions import BadRequestError
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.rag_document import RAGDocument
from app.db.models.user import User
from app.repositories import (
    knowledge_base_repo,
    member_repo,
    user_repo,
)
from app.services.file_storage import get_file_storage
from app.services.organization import OrganizationService
from app.services.rag.vectorstore import PgVectorStore
from app.services.user import UserService

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _route_purge_dispatch_to_impl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the org-purge cleanup in-process instead of submitting it to Prefect.

    `OrganizationService.purge` hands its external cleanup to a durable Prefect
    deployment run (#1274); with no runner behind the test, `run_deployment`
    would fail on an unregistered deployment. Routing that submission straight to
    the cleanup it would have run keeps these tests exercising the real drop and
    unlink through the commit/rollback gate that defers them - the submission
    fires only after a committed teardown, so a rolled-back one still runs
    nothing.

    The parameter is an intent id, so this reads the row the purge committed and
    deletes it afterwards - which is what the flow does, and what makes these
    tests exercise the outbox rather than route around it (#1269).
    """
    from app.worker.tasks import teardown_tasks

    async def _run(*, name: str, parameters: dict[str, Any], timeout: float) -> None:
        del name, timeout
        await teardown_tasks.cleanup_external_state(**parameters)

    monkeypatch.setattr(teardown_tasks, "run_deployment", AsyncMock(side_effect=_run))


def _user(email: str | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )


async def _member(db, org_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org_id, user_id=user_id, role=role))
    await db.flush()


async def _org(db, creator: User, *, is_personal: bool = False) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        is_personal=is_personal,
        created_by_user_id=creator.id,
    )
    db.add(org)
    await db.flush()
    await _member(db, org.id, creator.id, "owner")
    return org


def _org_collection(org_id: uuid.UUID, collection_name: str) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name="Shared docs",
        scope=KBScope.ORG.value,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        organization_id=org_id,
        visibility="org",
    )


def _personal_kb(org_id: uuid.UUID, owner_id: uuid.UUID, collection_name: str) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name="My notes",
        scope=KBScope.PERSONAL.value,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        organization_id=org_id,
        owner_user_id=owner_id,
        visibility="private",
    )


def _kb_document(
    collection_name: str, kb_id: uuid.UUID, org_id: uuid.UUID, storage_path: str
) -> RAGDocument:
    return RAGDocument(
        id=uuid.uuid4(),
        collection_name=collection_name,
        filename="notes.txt",
        filesize=5,
        filetype="txt",
        storage_path=storage_path,
        status="completed",
        chunk_count=0,
        ingestion_config={},
        knowledge_base_id=kb_id,
        organization_id=org_id,
    )


def _private_secret(org_id: uuid.UUID, owner_id: uuid.UUID) -> OrganizationSecret:
    return OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="mine",
        purpose="openai",
        visibility="private",
        owner_user_id=owner_id,
        kind="api_key",
        sealed_secret="{}",
        hint="1234",
    )


class TestDeletingAUser:
    async def test_a_normally_registered_user_can_be_deleted(self, db):
        """Every signup creates a personal org whose creator FK is RESTRICT, so a
        bare `DELETE users` never worked for a real account (#9)."""
        user = _user()
        db.add(user)
        await db.flush()
        org = await _org(db, user, is_personal=True)

        await UserService(db).delete(user.id)

        assert await db.get(User, user.id) is None
        assert await db.get(Organization, org.id) is None

    async def test_deleting_a_member_promotes_their_private_secret_to_the_org(self, db):
        """`ck_secret_private_needs_owner` forbids the ownerless-private row the
        `SET NULL` would otherwise leave; the key stays reachable by the org."""
        creator = _user()
        db.add(creator)
        await db.flush()
        org = await _org(db, creator)

        leaver = _user()
        db.add(leaver)
        await db.flush()
        await _member(db, org.id, leaver.id, "member")
        secret = _private_secret(org.id, leaver.id)
        db.add(secret)
        await db.flush()

        await UserService(db).delete(leaver.id)

        await db.refresh(secret)
        assert secret.owner_user_id is None
        assert secret.visibility == "org"

    async def test_deleting_a_user_removes_an_org_scoped_collection_they_owned(self, db):
        """The personal-org teardown runs the same collection cleanup as an org
        delete, with no vector store wired in - the row still has to go."""
        user = _user()
        db.add(user)
        await db.flush()
        org = await _org(db, user, is_personal=True)
        kb = _org_collection(org.id, f"kbnine{uuid.uuid4().hex[:12]}")
        db.add(kb)
        await db.flush()

        await UserService(db).delete(user.id)

        assert await db.get(KnowledgeBase, kb.id) is None
        assert await db.get(Organization, org.id) is None

    async def test_the_sole_owner_of_a_shared_org_is_refused_not_500ed(self, db):
        """A shared org with no other owner has nobody to hand the creator FK to,
        so the delete is a clean refusal rather than a foreign-key 500."""
        owner = _user()
        db.add(owner)
        await db.flush()
        await _org(db, owner)  # shared: is_personal defaults to False

        with pytest.raises(BadRequestError):
            await UserService(db).delete(owner.id)

        assert await db.get(User, owner.id) is not None

    async def test_a_shared_org_is_handed_to_another_owner(self, db):
        """When a co-owner exists the org survives, reattributed to them."""
        creator = _user()
        heir = _user()
        db.add_all([creator, heir])
        await db.flush()
        org = await _org(db, creator)
        await _member(db, org.id, heir.id, "owner")

        await UserService(db).delete(creator.id)

        await db.refresh(org)
        assert org.created_by_user_id == heir.id
        assert await db.get(User, creator.id) is None

    async def test_deleting_a_user_removes_their_personal_knowledge_base_whole(
        self, engine: AsyncEngine
    ) -> None:
        """A personal-scoped KB the user owns is torn down whole - rows, files and
        vector table - rather than orphaned by the `SET NULL` cascade with its
        name still blocking reuse (#1131)."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = get_file_storage()
        stored_path = await storage.save("kb-owner", "notes.txt", b"hello")
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user, is_personal=True)
            kb = _personal_kb(org.id, user.id, collection)
            s.add(kb)
            await s.flush()
            s.add(_kb_document(collection, kb.id, org.id, stored_path))
            await s.execute(text(f"CREATE TABLE {table} (id int)"))
            await s.commit()
            user_id, kb_id = user.id, kb.id

        async with factory() as s:
            await UserService(s, vector_store=store).delete(user_id)
            await s.commit()
            # The personal-collection teardown is now deferred like the org purge's
            # (#1359): a real request starts it from `_managed_session` after the
            # commit; a raw session starts it here, then drains the run.
            start_deferred(s)
        await drain()

        async with factory() as s:
            assert await s.get(KnowledgeBase, kb_id) is None
            docs = await s.execute(
                select(RAGDocument).where(RAGDocument.knowledge_base_id == kb_id)
            )
            assert docs.scalars().all() == []
            assert (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is None
            assert await s.get(User, user_id) is None
            # The name is reusable: no surviving row claims it.
            assert await knowledge_base_repo.get_by_collection_name(s, collection) is None

        assert storage.get_full_path(stored_path) is None

    async def test_a_personal_kb_sharing_a_collection_keeps_the_table(
        self, engine: AsyncEngine
    ) -> None:
        """Two KBs can back onto one physical table (collection_name is not
        tenant-unique, #913), so deleting one owner's personal KB removes its rows
        but not the table the other still references (#1131)."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            leaver = _user()
            keeper = _user()
            s.add_all([leaver, keeper])
            await s.flush()
            leaver_org = await _org(s, leaver, is_personal=True)
            keeper_org = await _org(s, keeper, is_personal=True)
            s.add(_personal_kb(leaver_org.id, leaver.id, collection))
            keeper_kb = _personal_kb(keeper_org.id, keeper.id, collection)
            s.add(keeper_kb)
            await s.execute(text(f"CREATE TABLE {table} (id int)"))
            await s.commit()
            leaver_id, keeper_kb_id = leaver.id, keeper_kb.id

        async with factory() as s:
            await UserService(s, vector_store=store).delete(leaver_id)
            await s.commit()

        async with factory() as s:
            assert await s.get(KnowledgeBase, keeper_kb_id) is not None
            assert (
                await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
            ).scalar() is not None

    async def test_a_refused_delete_leaves_the_personal_kb_intact(
        self, engine: AsyncEngine
    ) -> None:
        """The sole-owner refusal is decided before any teardown, so a delete that
        refuses does not leave the user's personal KB's files or table gone while
        its row rolls back (#1131)."""
        from app.core.exceptions import BadRequestError

        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = get_file_storage()
        stored_path = await storage.save("kb-owner", "notes.txt", b"hello")
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            await _org(s, user)  # a shared org solely owned -> the delete refuses
            personal_org = await _org(s, user, is_personal=True)
            kb = _personal_kb(personal_org.id, user.id, collection)
            s.add(kb)
            await s.flush()
            s.add(_kb_document(collection, kb.id, personal_org.id, stored_path))
            await s.execute(text(f"CREATE TABLE {table} (id int)"))
            await s.commit()
            user_id, kb_id = user.id, kb.id

        async with factory() as s:
            with pytest.raises(BadRequestError):
                await UserService(s, vector_store=store).delete(user_id)
            await s.rollback()

        async with factory() as s:
            assert await s.get(KnowledgeBase, kb_id) is not None
            assert (
                await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
            ).scalar() is not None
        assert storage.get_full_path(stored_path) is not None
        await storage.delete(stored_path)


class TestDeletingAnOrg:
    async def test_it_drops_org_scoped_collections_and_their_vector_tables(
        self, engine: AsyncEngine
    ) -> None:
        """The org-scope check turns a `SET NULL` on delete into a 500; the row is
        removed explicitly, and the real vector table goes with it (#9)."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            s.add(_org_collection(org.id, collection))
            await s.execute(text(f"CREATE TABLE {table} (id int)"))
            await s.commit()
            org_id = org.id

        async with factory() as s:
            assert (
                await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
            ).scalar() is not None

        async with factory() as s:
            org = await s.get(Organization, org_id)
            await OrganizationService(s, vector_store=store).purge(org)
            await s.commit()
            # The table drop and file unlinks defer to after commit (#1137); a
            # real request runs this from `_managed_session`, a raw session runs
            # it here.
            start_deferred(s)
        await drain()

        async with factory() as s:
            remaining = await s.execute(
                select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
            )
            assert remaining.scalars().all() == []
            assert (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is None
            assert await s.get(Organization, org_id) is None

    async def test_a_failed_teardown_commit_leaves_the_vector_table(
        self, engine: AsyncEngine
    ) -> None:
        """The drop and the unlinks defer past the request commit (#1137).

        Before this, `purge` dropped the table and unlinked files inside the
        request, so a final commit that rolled back left the org, KB and doc rows
        alive but their vectors and uploads already gone. Deferring the external
        side effects means a rolled-back teardown discards them: the table, the
        rows and the org all survive together.
        """
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            s.add(_org_collection(org.id, collection))
            await s.execute(text(f"CREATE TABLE {table} (id int)"))
            await s.commit()
            org_id = org.id

        async with factory() as s:
            org = await s.get(Organization, org_id)
            await OrganizationService(s, vector_store=store).purge(org)
            # The request's final commit fails: mirror `_managed_session`'s
            # failure path - roll back, then discard the deferred cleanup unrun.
            await s.rollback()
            discard_deferred(s)
        await drain()

        async with factory() as s:
            assert (
                await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
            ).scalar() is not None
            assert await s.get(Organization, org_id) is not None

    async def test_a_committed_teardown_unlinks_the_stored_files(self, engine: AsyncEngine) -> None:
        """A document row goes in the transaction; its stored upload is unlinked
        by the post-commit cleanup once the teardown commits (#1137)."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = get_file_storage()
        stored_path = await storage.save("teardown-user", "doc.txt", b"payload")
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            kb = _org_collection(org.id, collection)
            s.add(kb)
            await s.flush()
            s.add(_kb_document(collection, kb.id, org.id, stored_path))
            await s.commit()
            org_id = org.id

        assert storage.get_full_path(stored_path) is not None

        async with factory() as s:
            org = await s.get(Organization, org_id)
            await OrganizationService(s, vector_store=store).purge(org)
            await s.commit()
            start_deferred(s)
        await drain()

        assert storage.get_full_path(stored_path) is None

    async def test_a_rolled_back_teardown_keeps_the_stored_files(self, engine: AsyncEngine) -> None:
        """The file unlink defers past the commit too, so a teardown that rolls
        back leaves the stored upload in place (#1137)."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        storage = get_file_storage()
        stored_path = await storage.save("teardown-user", "doc.txt", b"payload")
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            kb = _org_collection(org.id, collection)
            s.add(kb)
            await s.flush()
            s.add(_kb_document(collection, kb.id, org.id, stored_path))
            await s.commit()
            org_id = org.id

        async with factory() as s:
            org = await s.get(Organization, org_id)
            await OrganizationService(s, vector_store=store).purge(org)
            await s.rollback()
            discard_deferred(s)
        await drain()

        assert storage.get_full_path(stored_path) is not None
        await storage.delete(stored_path)

    async def test_a_reclaim_during_the_deferred_drop_is_refused_until_it_finishes(
        self, engine: AsyncEngine
    ) -> None:
        """The drop runs after the commit that frees the name, so between the two the
        name is reserved (#1362): a second org's claim is refused rather than adopting
        the victim's still-populated table, and once the cleanup drops it and releases
        the name a fresh claim succeeds against a table that is gone."""
        from app.core.exceptions import AlreadyExistsError
        from app.core.permissions import AuthContext, OrgRoleName
        from app.services.collection_access import CollectionAccessService

        def _ctx(user_id: uuid.UUID, org_id: uuid.UUID) -> AuthContext:
            return AuthContext(
                user_id=user_id,
                organization_id=org_id,
                role=OrgRoleName.OWNER.value,
                is_app_admin=False,
            )

        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            s.add(_org_collection(org.id, collection))
            await s.execute(text(f"CREATE TABLE {table} (id int)"))
            await s.commit()
            org_id = org.id

        async with factory() as s:
            org = await s.get(Organization, org_id)
            await OrganizationService(s, vector_store=store).purge(org)
            await s.commit()
            # The name is reserved until the drop runs, so a second org's claim of it
            # in the window is refused - it cannot adopt the lingering populated table.
            async with factory() as claimant:
                other = _user()
                claimant.add(other)
                await claimant.flush()
                other_org = await _org(claimant, other)
                with pytest.raises(AlreadyExistsError):
                    await CollectionAccessService(claimant).claim(
                        _ctx(other.id, other_org.id), collection
                    )
                await claimant.rollback()
            start_deferred(s)
        await drain()

        # The cleanup dropped the table and released the name, so it is now claimable
        # afresh against a table that no longer holds the first org's chunks.
        async with factory() as s:
            assert (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is None
            user2 = _user()
            s.add(user2)
            await s.flush()
            org2 = await _org(s, user2)
            await CollectionAccessService(s).claim(_ctx(user2.id, org2.id), collection)

    async def test_a_personal_collection_survives_its_orgs_deletion(
        self, engine: AsyncEngine
    ) -> None:
        """A personal collection merely carrying the org's id is detached by the
        `SET NULL`, not deleted - its scope permits an absent org."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            personal = KnowledgeBase(
                id=uuid.uuid4(),
                name="My notes",
                scope=KBScope.PERSONAL.value,
                collection_name=f"kbnine{uuid.uuid4().hex[:12]}",
                embedding_model="text-embedding-3-small",
                embedding_dim=1536,
                organization_id=org.id,
                owner_user_id=user.id,
                visibility="private",
            )
            s.add(personal)
            await s.commit()
            org_id, kb_id = org.id, personal.id

        async with factory() as s:
            org = await s.get(Organization, org_id)
            await OrganizationService(s, vector_store=store).purge(org)
            await s.commit()

        async with factory() as s:
            surviving = await s.get(KnowledgeBase, kb_id)
            assert surviving is not None
            assert surviving.organization_id is None


_RENDEZVOUS_SECONDS = 1.0
"""How long one request waits for the other to take a user lock before carrying on.

Long enough that two live transactions always meet inside it - pre-fix they meet
in milliseconds - and short enough that the post-fix path, where only one ever
arrives, pays it once and the suite does not notice.
"""


class TestConcurrentSelfDeletes:
    async def test_mutual_co_owners_deleting_at_once_never_deadlock(
        self, engine: AsyncEngine
    ) -> None:
        """Two users who each solely own a shared org the other co-owns, deleting
        their own accounts at the same moment.

        `delete` reassigns each solely-created shared org to its heir, taking FOR
        KEY SHARE on the heir's user row through the FK while holding FOR UPDATE on
        its own. Before #1134 the two requests took those locks in opposite orders
        - each holding its own row and waiting for the other's - so Postgres broke
        the cycle by aborting one with a 40P01, surfacing as a 500. Locking every
        user row in ascending id order serialises the two on the lower id, so one
        completes and the other, now the sole owner of its org, gets a clean domain
        refusal - never a DeadlockDetected. Integration because the deadlock is a
        property of two transactions the database arbitrates, which a mock cannot
        show.
        """
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as setup:
            a = _user()
            b = _user()
            setup.add_all([a, b])
            await setup.flush()
            org_a = await _org(setup, a)
            await _member(setup, org_a.id, b.id, "owner")
            org_b = await _org(setup, b)
            await _member(setup, org_b.id, a.id, "owner")
            await setup.commit()
            a_id, b_id = a.id, b.id

        # Without this the test passes against the code it exists to fail
        # against: `gather` alone gives no guarantee both transactions reach the
        # conflicting sequence, and the pre-fix implementation answers one
        # success and one refusal too - measured, five runs out of five (#1268).
        #
        # A plain `Barrier` cannot express it, because the fix's whole purpose is
        # that one side *does not arrive*: ordering ascending, the request whose
        # own id is the higher blocks on the lower id before reaching its own
        # lock. So this is a rendezvous with a deadline. Each request pauses
        # after taking a user lock until the other has taken one too, or until
        # the deadline passes. Pre-fix both arrive in milliseconds, both then
        # hold their own row and reach for the other's, and Postgres aborts one
        # with a 40P01. Post-fix only one arrives, waits out the deadline once
        # and completes; the second is queued in the database, not deadlocked.
        both_hold_one = asyncio.Event()
        arrivals = 0
        real_lock = user_repo.get_by_id_for_update

        async def locking(db: Any, uid: uuid.UUID) -> Any:
            nonlocal arrivals
            locked = await real_lock(db, uid)
            arrivals += 1
            if arrivals >= 2:
                both_hold_one.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(both_hold_one.wait(), _RENDEZVOUS_SECONDS)
            return locked

        async def run_delete(user_id: uuid.UUID) -> object:
            async with factory() as session:
                user = await UserService(session).delete(user_id)
                await session.commit()
                return user

        with patch.object(user_repo, "get_by_id_for_update", locking):
            results = await asyncio.gather(
                run_delete(a_id), run_delete(b_id), return_exceptions=True
            )

        for result in results:
            assert not isinstance(result, (OperationalError, DBAPIError)), result

        deleted = [r for r in results if isinstance(r, User)]
        refused = [r for r in results if isinstance(r, BadRequestError)]
        assert len(deleted) == 1
        assert len(refused) == 1

        async with factory() as check:
            assert await check.get(User, deleted[0].id) is None
            survivor = a_id if deleted[0].id == b_id else b_id
            assert await check.get(User, survivor) is not None

    async def test_an_heir_named_after_the_locks_were_taken_is_refused(
        self, engine: AsyncEngine
    ) -> None:
        """Memberships are not locked, so the two heir reads can disagree.

        `_lock_for_delete` discovers heirs without a lock and locks them;
        `_release_owned_rows` re-reads authoritatively. An owner promoted between
        the two names an heir whose row was never locked, and `reassign_creator`
        would take their FK lock outside the ascending sequence - the cycle
        #1134 closed, by another door. Refusing is safe and the caller retries
        (#1268).
        """
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as setup:
            owner, first_heir, latecomer = _user(), _user(), _user()
            setup.add_all([owner, first_heir, latecomer])
            await setup.flush()
            org = await _org(setup, owner)
            await _member(setup, org.id, first_heir.id, "owner")
            await setup.commit()
            owner_id, latecomer_id = owner.id, latecomer.id

        # The second read answers somebody the lock pass never saw. Patched at
        # the boundary rather than raced, because the interleaving is the
        # premise here and not the thing under test.
        real = member_repo.other_owner_id
        calls = 0

        async def moving_target(db: Any, **kwargs: Any) -> uuid.UUID | None:
            nonlocal calls
            calls += 1
            return await real(db, **kwargs) if calls == 1 else latecomer_id

        async with factory() as session:
            with patch.object(member_repo, "other_owner_id", moving_target):
                with pytest.raises(BadRequestError) as refused:
                    await UserService(session).delete(owner_id)

        assert "changed while" in refused.value.message

        async with factory() as check:
            assert await check.get(User, owner_id) is not None

    async def test_a_delete_does_not_block_an_ordinary_write_against_its_heir(
        self, engine: AsyncEngine
    ) -> None:
        """The heir lock is `FOR NO KEY UPDATE`, and that is load-bearing.

        `FOR UPDATE` conflicts with the `FOR KEY SHARE` any foreign-key write
        takes - a channel identity relinked to the heir, say - so ordering the
        locks with the strongest mode would have traded one deadlock for a
        conflict class that did not exist before (#1268). This holds an FK lock
        on the heir open across the delete and asserts neither side errors.
        """
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as setup:
            owner, heir = _user(), _user()
            setup.add_all([owner, heir])
            await setup.flush()
            org = await _org(setup, owner)
            await _member(setup, org.id, heir.id, "owner")
            await setup.commit()
            owner_id, heir_id = owner.id, heir.id

        async with factory() as holder:
            # What an FK write against the heir takes, and nothing stronger.
            await holder.execute(
                text("SELECT 1 FROM users WHERE id = :id FOR KEY SHARE"), {"id": heir_id}
            )

            async with factory() as session:
                deleted = await UserService(session).delete(owner_id)
                await session.commit()

            await holder.commit()

        assert deleted.id == owner_id
