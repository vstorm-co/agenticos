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
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings as app_settings
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.rag_document import RAGDocument
from app.db.models.user import User
from app.repositories import rag_document_repo
from app.services.file_storage import get_file_storage
from app.services.organization import OrganizationService
from app.services.rag.vectorstore import PgVectorStore
from app.services.user import UserService

pytestmark = pytest.mark.anyio


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
        from app.core.exceptions import BadRequestError

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
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        try:
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

            async with factory() as s:
                remaining = await s.execute(
                    select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
                )
                assert remaining.scalars().all() == []
                assert (
                    await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
                ).scalar() is None
                assert await s.get(Organization, org_id) is None
        finally:
            await store.aclose()

    async def test_a_personal_collection_survives_its_orgs_deletion(
        self, engine: AsyncEngine
    ) -> None:
        """A personal collection merely carrying the org's id is detached by the
        `SET NULL`, not deleted - its scope permits an absent org."""
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
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
        finally:
            await store.aclose()

    async def test_it_purges_the_collections_documents_and_their_files(
        self, engine: AsyncEngine
    ) -> None:
        """`rag_documents` authorize on collection_name, so a row left behind is
        readable by a later collection permitted the same name. The org delete
        removes the KB's document rows and stored uploads before its identifiers
        go (#1116)."""
        store = PgVectorStore(
            settings=app_settings.rag, embedding_service=MagicMock(), resolver=MagicMock()
        )
        storage = get_file_storage()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"
        try:
            async with factory() as s:
                user = _user()
                s.add(user)
                await s.flush()
                org = await _org(s, user)
                kb = _org_collection(org.id, collection)
                s.add(kb)
                await s.flush()
                path = await storage.save("rag-test", "secret.txt", b"tenant contents")
                doc = await rag_document_repo.create(
                    s,
                    collection_name=collection,
                    filename="secret.txt",
                    filesize=15,
                    filetype="txt",
                    storage_path=path,
                    organization_id=org.id,
                    knowledge_base_id=kb.id,
                )
                await s.commit()
                org_id, doc_id = org.id, doc.id

            stored = storage.get_full_path(path)
            assert stored is not None and stored.exists()

            async with factory() as s:
                org = await s.get(Organization, org_id)
                await OrganizationService(s, vector_store=store).purge(org)
                await s.commit()

            async with factory() as s:
                assert await s.get(RAGDocument, doc_id) is None  # the row is gone
                by_name = await s.execute(
                    select(RAGDocument).where(RAGDocument.collection_name == collection)
                )
                assert by_name.scalars().all() == []  # not reachable by the name any more

            full = storage.get_full_path(path)
            assert full is None or not full.exists()  # the stored upload is gone too
        finally:
            await store.aclose()

    async def test_a_shared_collection_table_survives_for_a_co_tenant(
        self, engine: AsyncEngine
    ) -> None:
        """collection_name is not tenant-unique (#913), so two orgs can back onto
        one physical table. Deleting one must not drop the table out from under the
        other (#1116)."""
        store = PgVectorStore(
            settings=app_settings.rag, embedding_service=MagicMock(), resolver=MagicMock()
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbnine{uuid.uuid4().hex[:12]}"  # the same name in both orgs
        table = store._table(collection)
        try:
            async with factory() as s:
                user_a = _user()
                user_b = _user()
                s.add_all([user_a, user_b])
                await s.flush()
                org_a = await _org(s, user_a)
                org_b = await _org(s, user_b)
                s.add(_org_collection(org_a.id, collection))
                kb_b = _org_collection(org_b.id, collection)
                s.add(kb_b)
                await s.execute(text(f"CREATE TABLE {table} (id int)"))
                await s.commit()
                org_a_id, kb_b_id = org_a.id, kb_b.id

            async with factory() as s:
                org_a = await s.get(Organization, org_a_id)
                await OrganizationService(s, vector_store=store).purge(org_a)
                await s.commit()

            async with factory() as s:
                # org B still references the collection, so its table must survive
                assert (
                    await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
                ).scalar() is not None
                assert await s.get(KnowledgeBase, kb_b_id) is not None
        finally:
            await store.aclose()


class TestConcurrentInsertsDuringDeletion:
    """The reconcile is check-then-act; a row inserted between the two would 500.

    #9 reconciled the FK/CHECK cascades in the service, but listing (or promoting)
    and then deleting is a check-then-act with no row lock, so a concurrent insert
    reopens the exact 500 #9 closed. The teardown now takes FOR UPDATE on the row
    it is about, so a concurrent insert - which takes FOR KEY SHARE on the same
    row through its own FK - waits, and the reconcile sees every child there is
    (#1115). Deterministic on purpose: the insert is held open (uncommitted) so
    the delete blocks on the lock rather than racing it.
    """

    async def test_an_org_scoped_collection_inserted_during_an_org_delete(
        self, engine: AsyncEngine
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            user = _user()
            setup.add(user)
            await setup.flush()
            org = await _org(setup, user)
            await setup.commit()
            org_id = org.id

        session_a = factory()
        delete_task: asyncio.Task[None] | None = None
        try:
            # A member inserts a new org-scoped collection and holds it open:
            # FOR KEY SHARE on the org row, uncommitted.
            session_a.add(_org_collection(org_id, f"kbrace{uuid.uuid4().hex[:12]}"))
            await session_a.flush()

            async def purge_org() -> None:
                async with factory() as session_b:
                    org = await session_b.get(Organization, org_id)
                    await OrganizationService(session_b).purge(org)
                    await session_b.commit()

            delete_task = asyncio.create_task(purge_org())
            await asyncio.sleep(0.4)
            assert not delete_task.done()  # A's uncommitted insert holds the delete off

            await session_a.commit()

            await delete_task  # succeeds rather than a ck_knowledge_bases_org_scope_has_org 500
            delete_task = None
        finally:
            if delete_task is not None:
                delete_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await delete_task
            await session_a.close()

        async with factory() as s:
            assert await s.get(Organization, org_id) is None
            remaining = await s.execute(
                select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
            )
            assert remaining.scalars().all() == []  # the raced-in collection went too

    async def test_a_private_secret_inserted_during_a_user_delete(
        self, engine: AsyncEngine
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as setup:
            creator = _user()
            setup.add(creator)
            await setup.flush()
            org = await _org(setup, creator)
            leaver = _user()
            setup.add(leaver)
            await setup.flush()
            await _member(setup, org.id, leaver.id, "member")
            await setup.commit()
            org_id, leaver_id = org.id, leaver.id

        session_a = factory()
        delete_task: asyncio.Task[None] | None = None
        try:
            # A private secret for the leaver, held open: FOR KEY SHARE on the
            # leaver's user row through its owner FK, uncommitted.
            session_a.add(_private_secret(org_id, leaver_id))
            await session_a.flush()

            async def delete_leaver() -> None:
                async with factory() as session_b:
                    await UserService(session_b).delete(leaver_id)
                    await session_b.commit()

            delete_task = asyncio.create_task(delete_leaver())
            await asyncio.sleep(0.4)
            assert not delete_task.done()  # A's uncommitted insert holds the delete off

            await session_a.commit()

            await delete_task  # succeeds rather than a ck_secret_private_needs_owner 500
            delete_task = None
        finally:
            if delete_task is not None:
                delete_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await delete_task
            await session_a.close()

        async with factory() as s:
            assert await s.get(User, leaver_id) is None
            secrets = (
                (
                    await s.execute(
                        select(OrganizationSecret).where(
                            OrganizationSecret.organization_id == org_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert secrets  # the raced-in secret survived, promoted rather than orphaned
            for secret in secrets:
                assert secret.owner_user_id is None
                assert secret.visibility == "org"
