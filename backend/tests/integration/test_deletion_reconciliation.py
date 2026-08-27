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
from app.repositories import knowledge_base_repo
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

        async with factory() as s:
            remaining = await s.execute(
                select(KnowledgeBase).where(KnowledgeBase.organization_id == org_id)
            )
            assert remaining.scalars().all() == []
            assert (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is None
            assert await s.get(Organization, org_id) is None

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
