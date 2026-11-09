"""Deleting a user or an org no longer 500s on a cascade the schema forbids.

Three `ON DELETE SET NULL`/RESTRICT cascades each drove precisely the write a
CHECK constraint rejects, so the delete raised inside the database and surfaced
as a 500 (#9). Each is reconciled in the service before the row goes: a private
secret is promoted to the org, a personal org is removed with its owner, and an
org-scoped collection is deleted - table and all - rather than orphaned.

Integration rather than unit because the whole point is what the database does
to neighbouring rows when one is deleted, which a mock cannot show.
"""

import asyncio
import contextlib
import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred, drain, start_deferred
from app.core.config import settings as app_settings
from app.core.exceptions import AlreadyExistsError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_name
from app.db.models.conversation import Conversation
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User
from app.db.vector_tables import VectorScope
from app.repositories import (
    conversation_repo,
    knowledge_base_repo,
    member_repo,
    project_repo,
    user_repo,
)
from app.services.file_storage import get_file_storage
from app.services.knowledge_base import KnowledgeBaseService
from app.services.organization import OrganizationService
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionStatus,
)
from app.services.rag.vectorstore import KnowledgeBaseRemovedError, PgVectorStore
from app.services.user import UserService

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _run_queued_cleanups_after_the_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the queued cleanup jobs the moment the transaction that queued them commits.

    `OrganizationService.purge` and the KB delete paths queue their external
    cleanup as a job in their own transaction (#2219). With no worker behind the
    test, the queueing is left as it is - the job is really written - and the
    jobs are then claimed and run straight after the commit, the way a worker
    would: so these tests exercise the real drop and unlink, and a rolled-back
    teardown, whose job rolled back with it, still runs nothing.
    """
    from datetime import timedelta

    from app.core.background import spawn_after_commit
    from app.db.session import get_worker_db_context
    from app.repositories import background_job as job_repo
    from app.worker.jobs import CLEANUP_EXTERNAL_STATE
    from app.worker.tasks import teardown_tasks

    queue = teardown_tasks.queue_external_state_cleanup

    async def run_queued() -> None:
        async with get_worker_db_context() as db:
            while job := await job_repo.claim(
                db, pool="system", worker_id="test", lease=timedelta(minutes=5)
            ):
                await teardown_tasks.run_external_state_cleanup(
                    CLEANUP_EXTERNAL_STATE.load(job.payload)
                )
                await job_repo.complete(db, job.id, fence=job.attempts)

    async def queue_then_run(db, *args, **kwargs) -> None:
        await queue(db, *args, **kwargs)
        spawn_after_commit(db, run_queued(), name="test-run-queued-cleanups")

    monkeypatch.setattr(teardown_tasks, "queue_external_state_cleanup", queue_then_run)


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
    collection_name: str, kb_id: uuid.UUID | None, org_id: uuid.UUID | None, storage_path: str
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

    async def test_a_project_chat_the_user_started_stays_with_the_team(self, db):
        """Teammates read and continue a project's chat; the `users` cascade
        would have taken it with its starter. Their own chats still go."""
        creator = _user()
        db.add(creator)
        await db.flush()
        org = await _org(db, creator)
        leaver = _user()
        db.add(leaver)
        await db.flush()
        await _member(db, org.id, leaver.id, "member")
        project = await project_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=creator.id,
            name="Launch",
            description=None,
            instructions="",
            default_agent_id=None,
            backend="state",
        )
        shared = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=leaver.id, title="Plan", project_id=project.id
        )
        own = await conversation_repo.create_conversation(
            db, organization_id=org.id, user_id=leaver.id, title="Mine"
        )
        shared_id, own_id, project_id = shared.id, own.id, project.id

        await UserService(db).delete(leaver.id)

        db.expire_all()
        kept = await db.get(Conversation, shared_id)
        assert kept is not None and kept.user_id is None and kept.project_id == project_id
        assert await db.get(Conversation, own_id) is None

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

    async def test_purge_takes_the_teardown_lock_before_the_org_row_lock(
        self, engine: AsyncEngine
    ) -> None:
        """A concurrent claim holds a collection's teardown lock; purge must block on
        that lock BEFORE it takes the organizations row `FOR UPDATE`, so the two
        acquire {teardown, org} in one order and cannot deadlock (#1387).

        Claim takes the teardown lock and then the org FK; the old purge took the org
        row first and the teardown lock second - the inversion. Here, while a holder
        owns the teardown lock and purge waits on it, a `FOR UPDATE NOWAIT` probe of
        the org row must still succeed, because purge has not reached it. On the old
        order the same probe found the row already locked.
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

        async with factory() as holder, factory() as purger, factory() as probe:
            await hold_name(holder, LockScope.COLLECTION_TEARDOWN, collection)

            org = await purger.get(Organization, org_id)
            purge_task = asyncio.ensure_future(
                OrganizationService(purger, vector_store=store).purge(org)
            )
            try:
                await asyncio.sleep(0.25)
                assert not purge_task.done()  # blocked acquiring the teardown lock

                probed = await probe.execute(
                    select(Organization)
                    .where(Organization.id == org_id)
                    .with_for_update(nowait=True)
                )
                assert probed.scalar_one().id == org_id
                await probe.rollback()

                await holder.rollback()  # release the teardown lock
                await asyncio.wait_for(purge_task, timeout=5.0)
                assert purge_task.exception() is None
            finally:
                purge_task.cancel()

            await purger.commit()
            start_deferred(purger)
        await drain()

        async with factory() as s:
            assert await s.get(Organization, org_id) is None
            assert (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is None

    async def test_the_collection_drop_takes_the_teardown_lock_before_deleting_documents(
        self, engine: AsyncEngine
    ) -> None:
        """`DELETE /rag/collections/{name}` deletes a collection's document rows only
        after taking its teardown lock, so it and a concurrent org purge - which now
        takes that lock before touching the same rows - acquire {teardown, rag_documents}
        in one order and cannot deadlock (#1387).

        The old route deleted the rows first, holding their locks while it then waited
        on the teardown lock; here, while a holder owns the teardown lock and the drop
        waits on it, a `FOR UPDATE NOWAIT` probe of the document row must still succeed,
        because the drop has not reached its delete.
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
        stored = await get_file_storage().save("drop-order", "d.txt", b"x")
        async with factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user)
            kb = _org_collection(org.id, collection)
            s.add(kb)
            await s.flush()
            doc = _kb_document(collection, kb.id, org.id, stored)
            s.add(doc)
            await s.execute(text(f"CREATE TABLE {table} (id int, metadata jsonb)"))
            await s.commit()
            kb_id, doc_id = kb.id, doc.id

        async with factory() as holder, factory() as dropper, factory() as probe:
            await hold_name(holder, LockScope.COLLECTION_TEARDOWN, collection)

            kb = await dropper.get(KnowledgeBase, kb_id)

            drop_task = asyncio.ensure_future(
                KnowledgeBaseService(dropper).delete_for_rag_collection(kb)
            )
            try:
                await asyncio.sleep(0.25)
                assert not drop_task.done()  # blocked acquiring the teardown lock

                probed = await probe.execute(
                    select(RAGDocument).where(RAGDocument.id == doc_id).with_for_update(nowait=True)
                )
                assert probed.scalar_one().id == doc_id
                await probe.rollback()

                await holder.rollback()  # release the teardown lock
                await asyncio.wait_for(drop_task, timeout=5.0)
                assert drop_task.exception() is None
            finally:
                drop_task.cancel()

            await dropper.commit()
            start_deferred(dropper)
        await drain()

        async with factory() as s:
            assert await s.get(RAGDocument, doc_id) is None
            assert (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is None

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

        async def locking(db: Any, uid: uuid.UUID, *, nowait: bool = False) -> Any:
            nonlocal arrivals
            locked = await real_lock(db, uid, nowait=nowait)
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

        `_lock_user_rows` discovers heirs without a lock and locks them;
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
            with (
                patch.object(member_repo, "other_owner_id", moving_target),
                pytest.raises(BadRequestError) as refused,
            ):
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


async def _filed_table(s, table: str, chunks: dict[str, uuid.UUID]) -> None:
    """A runtime vector table holding one chunk per id, filed under the given base.

    Only `metadata` matters to the purge, so the table carries no embedding."""
    await s.execute(text(f"CREATE TABLE {table} (id text PRIMARY KEY, metadata jsonb)"))
    for chunk_id, kb_id in chunks.items():
        await s.execute(
            text(f"INSERT INTO {table} (id, metadata) VALUES (:id, CAST(:meta AS jsonb))"),  # noqa: S608
            {"id": chunk_id, "meta": json.dumps({"knowledge_base_id": str(kb_id)})},
        )


async def _document_chunk(
    s,
    table: str,
    chunk_id: str,
    parent_doc_id: str,
    kb_id: uuid.UUID | None,
    org_id: uuid.UUID | None = None,
) -> None:
    """One chunk of a document in a table `parent_doc_id` keys: filed under a
    base, or unfiled (`kb_id=None`) and tagged with its tenant."""
    meta = (
        {"knowledge_base_id": str(kb_id)}
        if kb_id
        else {"organization_id": str(org_id)}
        if org_id
        else {}
    )
    await s.execute(
        text(f"INSERT INTO {table} VALUES (:id, :doc, CAST(:meta AS jsonb))"),  # noqa: S608
        {"id": chunk_id, "doc": parent_doc_id, "meta": json.dumps(meta)},
    )


async def _chunk_ids(s, table: str) -> set[str]:
    return set((await s.execute(text(f"SELECT id FROM {table}"))).scalars())  # noqa: S608


_TEARDOWN_ROUTES = pytest.mark.parametrize("route", ["kb_delete", "rag_drop"])
"""Both teardown routes, which share one helper and so must leave the same state (#2568)."""


async def _tear_down(s: AsyncSession, route: str, kb_id: uuid.UUID, ctx: AuthContext) -> None:
    """Remove a non-default base the way `DELETE /kb/{id}` or `DELETE /rag/collections/{name}` does."""
    service = KnowledgeBaseService(s)
    if route == "kb_delete":
        await service.delete(kb_id, ctx=ctx)
    else:
        kb = await s.get(KnowledgeBase, kb_id)
        assert kb is not None
        await service.delete_for_rag_collection(kb)


class TestADeletedBasesChunksOnAKeptTable:
    """A base deleted while another base holds its collection name leaves the shared
    table standing (#913); the chunks filed under it are read by no scope any more,
    so the queued cleanup deletes them by the base's id and leaves the survivor's
    (#2537). The last holder's teardown, which drops the table, is checked against
    the same rows here too (#2568). These run the real job against a real table."""

    @_TEARDOWN_ROUTES
    async def test_deleting_a_knowledge_base_removes_its_chunks_only(
        self, engine: AsyncEngine, route: str
    ) -> None:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            await _filed_table(s, table, {"doomed-0": doomed.id, "kept-0": kept.id})
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            doomed_id = doomed.id

        try:
            async with factory() as s:
                await _tear_down(s, route, doomed_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await _chunk_ids(s, table) == {"kept-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_a_torn_down_base_takes_its_tenants_unfiled_documents_only(
        self, engine: AsyncEngine, route: str
    ) -> None:
        """Either teardown route, with another organization's base on the same name:
        a delete that removed only rows filed under the base left the unfiled
        legacy rows it took - its organization's - with their files and chunks,
        and they came back with the organization's next base on the name (#2560).
        Now they go with it, and the other organization's unfiled rows stay."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        storage = get_file_storage()
        ours_file = await storage.save("delete-unfiled", "ours.txt", b"ours")
        theirs_file = await storage.save("delete-unfiled", "theirs.txt", b"theirs")
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            ours = _kb_document(collection, None, org.id, ours_file)
            ours.vector_document_id = "ours-doc"
            theirs = _kb_document(collection, None, other_org.id, theirs_file)
            theirs.vector_document_id = "theirs-doc"
            s.add_all([ours, theirs])
            await s.execute(
                text(
                    f"CREATE TABLE {table} (id text PRIMARY KEY, parent_doc_id text, metadata jsonb)"
                )
            )
            await _document_chunk(s, table, "ours-0", "ours-doc", None, org.id)
            await _document_chunk(s, table, "theirs-0", "theirs-doc", None, other_org.id)
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            doomed_id, ours_id, theirs_id = doomed.id, ours.id, theirs.id

        try:
            async with factory() as s:
                await _tear_down(s, route, doomed_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, doomed_id) is None
                assert await s.get(RAGDocument, ours_id) is None
                assert await s.get(RAGDocument, theirs_id) is not None
                assert await _chunk_ids(s, table) == {"theirs-0"}
            assert not await storage.exists(ours_file)
            assert await storage.exists(theirs_file)
        finally:
            await storage.delete(ours_file)
            await storage.delete(theirs_file)
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    async def test_rag_drop_of_a_shared_name_keeps_the_other_organizations_table(
        self, engine: AsyncEngine
    ) -> None:
        """`rag-drop` dropped the table by name, whoever else held it (#2560).
        Unnamed, a shared name is refused; naming one base clears only it, on
        the real teardown lock taken twice in one transaction."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            await _filed_table(s, table, {"doomed-0": doomed.id, "kept-0": kept.id})
            await s.commit()
            doomed_id, kept_id = doomed.id, kept.id

        try:
            async with factory() as s:
                with pytest.raises(BadRequestError):
                    await KnowledgeBaseService(s).drop_collection_by_name(collection)
                await s.rollback()
            async with factory() as s:
                await KnowledgeBaseService(s).drop_collection_by_name(
                    collection, knowledge_base_id=doomed_id
                )
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, doomed_id) is None
                assert await s.get(KnowledgeBase, kept_id) is not None
                assert await _chunk_ids(s, table) == {"kept-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_a_torn_down_base_takes_its_own_documents_and_chunks_only(
        self, engine: AsyncEngine, route: str
    ) -> None:
        """Either teardown route, with another organization's base on the same name:
        the collection drop deleted every document row under the name and kept
        the dropped base's chunks in the shared table (#2560). Now both delete the
        base's own rows and files, and the queued cleanup purges its chunks."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        storage = get_file_storage()
        ours_file = await storage.save("drop-shared", "ours.txt", b"ours")
        theirs_file = await storage.save("drop-shared", "theirs.txt", b"theirs")
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            ours = _kb_document(collection, doomed.id, org.id, ours_file)
            theirs = _kb_document(collection, kept.id, other_org.id, theirs_file)
            s.add_all([ours, theirs])
            await _filed_table(s, table, {"doomed-0": doomed.id, "kept-0": kept.id})
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            doomed_id, kept_id, ours_id, theirs_id = doomed.id, kept.id, ours.id, theirs.id

        try:
            async with factory() as s:
                await _tear_down(s, route, doomed_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, doomed_id) is None
                assert await s.get(RAGDocument, ours_id) is None
                assert await s.get(KnowledgeBase, kept_id) is not None
                assert await s.get(RAGDocument, theirs_id) is not None
                assert await _chunk_ids(s, table) == {"kept-0"}
            assert not await storage.exists(ours_file)
            assert await storage.exists(theirs_file)
        finally:
            await storage.delete(ours_file)
            await storage.delete(theirs_file)
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    @pytest.mark.parametrize("holder", ["org", "app"])
    async def test_the_last_holder_takes_its_own_and_its_tenants_unfiled_rows_only(
        self, engine: AsyncEngine, route: str, holder: str
    ) -> None:
        """With no other base on the name the table is dropped, and both routes
        delete the same rows with their files: the base's own and the unfiled rows
        of its tenant - its organization's for an organization's base, the
        tenant-less ones `rag-ingest` writes for an app-scoped one. Another
        tenant's unfiled rows stay with their files, since the caller has no
        authority over them, but the table holds no chunk of theirs to keep it, so
        it goes: they are marked failed, so their next base lists them as failed
        rather than as indexed, and one still being ingested has its attempt
        superseded. `DELETE /kb/{id}` left the tenant's unfiled rows behind the
        dropped table, and the collection drop deleted every row under the name,
        in every organization (#2568)."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kblast{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        storage = get_file_storage()
        kinds = ("filed", "unfiled", "foreign", "tenantless", "failed")
        files = [await storage.save("last-holder", f"{kind}.txt", kind.encode()) for kind in kinds]
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            if holder == "app":
                doomed.scope = KBScope.APP.value
                doomed.organization_id = None
            s.add(doomed)
            await s.flush()
            documents = [
                _kb_document(collection, doomed.id, org.id, files[0]),
                _kb_document(collection, None, org.id, files[1]),
                _kb_document(collection, None, other_org.id, files[2]),
                _kb_document(collection, None, None, files[3]),
                _kb_document(collection, None, other_org.id, files[4]),
            ]
            documents[3].writer_kind = "operator"  # Explicit CLI origin, not a missing owner.
            for index, document in enumerate(documents):
                document.status = DocumentStatus.DONE.value
                document.vector_document_id = f"doc-{index}"
            # Another organization's ingest still in flight: kept, but failed with
            # its attempt superseded, so its settlement cannot mark it done.
            documents[2].status = DocumentStatus.PROCESSING.value
            documents[2].vector_document_id = None
            # Already failed, still naming the version an earlier attempt indexed:
            # its index metadata goes too, with no attempt to supersede.
            documents[4].status = DocumentStatus.ERROR.value
            documents[4].chunk_count = 3
            s.add_all(documents)
            await _filed_table(s, table, {"doomed-0": doomed.id})
            await s.commit()
            ctx = AuthContext(
                user_id=owner.id,
                organization_id=org.id,
                role=OrgRoleName.OWNER,
                is_app_admin=holder == "app",
            )
            doomed_id = doomed.id
            ours = (0, 1) if holder == "org" else (0, 3)
            taken = [documents[i].id for i in ours]
            spared = [document.id for i, document in enumerate(documents) if i not in ours]

        try:
            async with factory() as s:
                await _tear_down(s, route, doomed_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, doomed_id) is None
                for document_id in taken:
                    assert await s.get(RAGDocument, document_id) is None
                for document_id in spared:
                    kept = await s.get(RAGDocument, document_id)
                    assert kept is not None
                    assert kept.status == DocumentStatus.ERROR.value
                    assert kept.vector_document_id is None
                    assert kept.error_message
                    assert kept.chunk_count == 0
                    failed_before = document_id == documents[4].id
                    assert kept.ingestion_attempt == (1 if failed_before else 2)
                assert (
                    await s.execute(text("SELECT to_regclass(:t)"), {"t": table})
                ).scalar() is None
            for i, stored in enumerate(files):
                assert await storage.exists(stored) == (i not in ours)
        finally:
            for stored in files:
                await storage.delete(stored)
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    async def test_clearing_a_kept_default_spares_an_upload_made_after_the_drop(
        self, engine: AsyncEngine
    ) -> None:
        """A cleared default keeps its row, so it takes uploads again once the drop
        commits, filed under the same id. Its purge removes the chunks of the
        documents the drop deleted, not every chunk filed under the base - which
        would take an upload ingested before the cleanup job ran (#2560)."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            default = _org_collection(org.id, collection)
            default.is_default = True
            sibling = _org_collection(other_org.id, collection)
            s.add_all([default, sibling])
            await s.flush()
            old = _kb_document(collection, default.id, org.id, "drop-default/old.txt")
            old.vector_document_id = "old-doc"
            s.add(old)
            await s.execute(
                text(
                    f"CREATE TABLE {table} (id text PRIMARY KEY, parent_doc_id text, metadata jsonb)"
                )
            )
            await _document_chunk(s, table, "old-0", "old-doc", default.id)
            await _document_chunk(s, table, "sibling-0", "sibling-doc", sibling.id)
            await s.commit()
            default_id, old_id = default.id, old.id

        try:
            async with factory() as s:
                kb = await s.get(KnowledgeBase, default_id)
                await KnowledgeBaseService(s).delete_for_rag_collection(kb)
                await s.commit()
                # An upload into the kept default, ingested before the job runs.
                await _document_chunk(s, table, "new-0", "new-doc", default_id)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, default_id) is not None
                assert await s.get(RAGDocument, old_id) is None
                assert await _chunk_ids(s, table) == {"new-0", "sibling-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @pytest.mark.security
    @pytest.mark.parametrize("unfiled", [False, True], ids=["bound-worker", "unfiled-cli"])
    async def test_clearing_a_kept_default_purges_committed_chunks_before_settlement(
        self, engine: AsyncEngine, unfiled: bool
    ) -> None:
        """Chunks committed before tracking settlement still belong to the clear."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            default = _org_collection(org.id, collection)
            default.is_default = True
            if unfiled:
                default.scope = KBScope.APP.value
                default.organization_id = None
            sibling = _org_collection(other_org.id, collection)
            s.add_all([default, sibling])
            await s.flush()
            old = _kb_document(collection, default.id, org.id, "drop-default/old.txt")
            old.vector_document_id = None
            old.status = "processing"
            if unfiled:
                old.knowledge_base_id = None
                old.organization_id = None
                old.writer_kind = "operator"
            s.add(old)
            await s.execute(
                text(
                    f"CREATE TABLE {table} (id text PRIMARY KEY, parent_doc_id text, metadata jsonb)"
                )
            )
            await _document_chunk(s, table, "old-0", "old-doc", None if unfiled else default.id)
            if unfiled:
                await s.execute(
                    text(
                        f"UPDATE {table} SET metadata = metadata || '{{\"writer_kind\":\"operator\"}}'::jsonb WHERE id = 'old-0'"  # noqa: S608 - generated collection identifier
                    )
                )
            await _document_chunk(s, table, "sibling-0", "sibling-doc", sibling.id)
            await s.commit()
            default_id, old_id = default.id, old.id

        try:
            async with factory() as s:
                kb = await s.get(KnowledgeBase, default_id)
                await KnowledgeBaseService(s).delete_for_rag_collection(kb)
                await s.commit()
                # An upload into the kept default, ingested before the job runs.
                await _document_chunk(s, table, "new-0", "new-doc", default_id)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, default_id) is not None
                assert await s.get(RAGDocument, old_id) is None
                assert await _chunk_ids(s, table) == {"new-0", "sibling-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    async def test_clearing_a_kept_default_removes_its_tenants_unfiled_documents(
        self, engine: AsyncEngine
    ) -> None:
        """A kept default lists the unfiled rows its organization holds under the
        name - legacy uploads from before documents recorded their base. The drop
        deleted only rows filed under the base, so a cleared default still listed
        and served them and their chunks stayed searchable; the route's own delete
        by name used to take them. Now they go with the clear, files and chunks
        included, and another organization's unfiled rows under the name stay."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        storage = get_file_storage()
        ours_file = await storage.save("drop-unfiled", "ours.txt", b"ours")
        theirs_file = await storage.save("drop-unfiled", "theirs.txt", b"theirs")
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            default = _org_collection(org.id, collection)
            default.is_default = True
            sibling = _org_collection(other_org.id, collection)
            s.add_all([default, sibling])
            await s.flush()
            ours = _kb_document(collection, None, org.id, ours_file)
            ours.vector_document_id = "ours-doc"
            theirs = _kb_document(collection, None, other_org.id, theirs_file)
            theirs.vector_document_id = "theirs-doc"
            s.add_all([ours, theirs])
            await s.execute(
                text(
                    f"CREATE TABLE {table} (id text PRIMARY KEY, parent_doc_id text, metadata jsonb)"
                )
            )
            await _document_chunk(s, table, "ours-0", "ours-doc", None, org.id)
            await _document_chunk(s, table, "theirs-0", "theirs-doc", None, other_org.id)
            await s.commit()
            default_id, ours_id, theirs_id = default.id, ours.id, theirs.id

        try:
            async with factory() as s:
                kb = await s.get(KnowledgeBase, default_id)
                await KnowledgeBaseService(s).delete_for_rag_collection(kb)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, default_id) is not None
                assert await s.get(RAGDocument, ours_id) is None
                assert await s.get(RAGDocument, theirs_id) is not None
                assert await _chunk_ids(s, table) == {"theirs-0"}
            assert not await storage.exists(ours_file)
            assert await storage.exists(theirs_file)
        finally:
            await storage.delete(ours_file)
            await storage.delete(theirs_file)
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    async def test_clearing_a_default_leaves_unfiled_documents_to_a_same_tenant_base(
        self, engine: AsyncEngine
    ) -> None:
        """Another base of the same organization on the name still lists the
        unfiled rows, so clearing the default leaves them and their chunks to it,
        and removes only the default's own documents' chunks."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            default = _org_collection(org.id, collection)
            default.is_default = True
            sibling = _org_collection(org.id, collection)
            s.add_all([default, sibling])
            await s.flush()
            filed = _kb_document(collection, default.id, org.id, "drop-unfiled/filed.txt")
            filed.vector_document_id = "filed-doc"
            legacy = _kb_document(collection, None, org.id, "drop-unfiled/legacy.txt")
            legacy.vector_document_id = "legacy-doc"
            s.add_all([filed, legacy])
            await s.execute(
                text(
                    f"CREATE TABLE {table} (id text PRIMARY KEY, parent_doc_id text, metadata jsonb)"
                )
            )
            await _document_chunk(s, table, "filed-0", "filed-doc", default.id)
            await _document_chunk(s, table, "legacy-0", "legacy-doc", None, org.id)
            await s.commit()
            default_id, filed_id, legacy_id = default.id, filed.id, legacy.id

        try:
            async with factory() as s:
                kb = await s.get(KnowledgeBase, default_id)
                await KnowledgeBaseService(s).delete_for_rag_collection(kb)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(RAGDocument, filed_id) is None
                assert await s.get(RAGDocument, legacy_id) is not None
                assert await _chunk_ids(s, table) == {"legacy-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    async def test_purging_an_organization_removes_its_bases_chunks_only(
        self, engine: AsyncEngine
    ) -> None:
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            await _filed_table(s, table, {"doomed-0": doomed.id, "kept-0": kept.id})
            await s.commit()
            org_id = org.id

        try:
            async with factory() as s:
                org = await s.get(Organization, org_id)
                await OrganizationService(s, vector_store=store).purge(org)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await _chunk_ids(s, table) == {"kept-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    async def test_deleting_a_user_removes_their_personal_bases_chunks_only(
        self, engine: AsyncEngine
    ) -> None:
        store = PgVectorStore(
            settings=app_settings.rag,
            embedding_service=MagicMock(),
            resolver=MagicMock(),
            engine=engine,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbshare{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            leaver, keeper = _user(), _user()
            s.add_all([leaver, keeper])
            await s.flush()
            leaver_org = await _org(s, leaver, is_personal=True)
            keeper_org = await _org(s, keeper, is_personal=True)
            doomed = _personal_kb(leaver_org.id, leaver.id, collection)
            kept = _personal_kb(keeper_org.id, keeper.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            await _filed_table(s, table, {"doomed-0": doomed.id, "kept-0": kept.id})
            await s.commit()
            leaver_id = leaver.id

        try:
            async with factory() as s:
                await UserService(s, vector_store=store).delete(leaver_id)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await _chunk_ids(s, table) == {"kept-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()


def _store_embedding_in_3d(engine: AsyncEngine) -> PgVectorStore:
    """A real store on the test database whose embedder answers with no provider."""
    store = PgVectorStore(
        settings=app_settings.rag,
        embedding_service=MagicMock(),
        resolver=MagicMock(),
        engine=engine,
    )
    embedder = MagicMock(
        embed_document=lambda document: [[0.1, 0.2, 0.3]] * len(document.chunked_pages)
    )
    store._for_collection = AsyncMock(return_value=(embedder, 3))  # type: ignore[method-assign]
    return store


def _parsed(content: str) -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content=content)],
        metadata=DocumentMetadata(
            filename=f"{content}.md", filesize=1, filetype="md", source_path=f"/{content}.md"
        ),
    )
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content=content,
            chunk_num=0,
            page_num=1,
            content=content,
            parent_doc_id=document.id,
        )
    ]
    return document


async def _filed_under(s, table: str, kb_id: uuid.UUID) -> int:
    return (
        await s.execute(
            text(f"SELECT count(*) FROM {table} WHERE (metadata->>'knowledge_base_id') = :kb"),  # noqa: S608
            {"kb": str(kb_id)},
        )
    ).scalar_one()


class TestAnIngestRacingItsBasesDelete:
    """An ingest that passed its `still_wanted` gate before its base was deleted
    beside a sibling that keeps the name, which reserves nothing the gate reads
    (#2561). `knowledge_base_repo.hold_key_share` has the reasoning."""

    async def test_a_base_deleted_after_the_parse_gets_no_chunks(self, engine: AsyncEngine) -> None:
        store = _store_embedding_in_3d(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbrace{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)

        async def deleted_between_the_parse_and_the_write() -> bool:
            # The gate answers yes, and the delete commits and its cleanup job
            # purges the base before the write starts: the window #2561 names.
            async with factory() as s:
                await KnowledgeBaseService(s).delete(doomed.id, ctx=ctx)
                await s.commit()
                start_deferred(s)
            await drain()
            return True

        processor = MagicMock(process_file=AsyncMock(return_value=_parsed("doomed")))
        ingester = IngestionService(processor, store, scope=doomed.vector_scope)

        try:
            await store.insert_document(collection, _parsed("kept"), kept.vector_scope)
            result = await ingester.ingest_file(
                Path("doomed.md"),
                collection,
                replace=False,
                still_wanted=deleted_between_the_parse_and_the_write,
            )

            assert result.status is IngestionStatus.ERROR
            assert result.error_message == (
                "The knowledge base was deleted while this file was being indexed"
            )
            # Refused, which the worker ends without a retry (RR3-c1a).
            assert result.refused is True
            async with factory() as s:
                assert await _filed_under(s, table, doomed.id) == 0
                assert await _filed_under(s, table, kept.id) == 1
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    async def test_a_default_cleared_after_the_gate_gets_no_stale_chunks(
        self, engine: AsyncEngine
    ) -> None:
        store = _store_embedding_in_3d(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbrace{uuid.uuid4().hex[:12]}"
        table = store._table(collection)
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            doomed = _org_collection(org.id, collection)
            doomed.is_default = True
            kept = _org_collection(other_org.id, collection)
            s.add_all([doomed, kept])
            await s.flush()
            tracking = _kb_document(collection, doomed.id, org.id, "")
            tracking.status = "processing"
            s.add(tracking)
            await s.commit()

        async def deleted_between_the_parse_and_the_write() -> bool:
            # The gate answers yes, and the delete commits and its cleanup job
            # purges the base before the write starts: the window #2561 names.
            async with factory() as s:
                current = await s.get(KnowledgeBase, doomed.id)
                await KnowledgeBaseService(s).delete_for_rag_collection(current)
                await s.commit()
                start_deferred(s)
            await drain()
            return True

        processor = MagicMock(process_file=AsyncMock(return_value=_parsed("doomed")))
        ingester = IngestionService(processor, store, scope=doomed.vector_scope)

        try:
            await store.insert_document(collection, _parsed("kept"), kept.vector_scope)
            result = await ingester.ingest_file(
                Path("doomed.md"),
                collection,
                replace=False,
                rag_document_id=tracking.id,
                still_wanted=deleted_between_the_parse_and_the_write,
            )

            assert result.status is IngestionStatus.ERROR
            assert result.error_message == (
                "The document was cleared while this file was being indexed"
            )
            # Refused, which the worker ends without a retry (RR3-c1a).
            assert result.refused is True
            async with factory() as s:
                assert await _filed_under(s, table, doomed.id) == 0
                assert await _filed_under(s, table, kept.id) == 1
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    async def test_a_delete_waits_for_a_write_in_flight(self, engine: AsyncEngine) -> None:
        """The other order: a write that has checked its base holds it until its
        chunks commit, so the delete - and the purge it queues - comes after them."""
        store = _store_embedding_in_3d(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbrace{uuid.uuid4().hex[:12]}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.commit()

        async with store.async_session() as writing:
            assert await knowledge_base_repo.hold_key_share(writing, base.id)
            async with factory() as deleting:
                await deleting.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    await knowledge_base_repo.lock(deleting, base.id)
            await writing.rollback()

    async def test_two_writes_into_one_base_do_not_wait_for_each_other(
        self, engine: AsyncEngine
    ) -> None:
        """The hold is the foreign key's own share lock, not an exclusive one: a
        second ingest into the same base must not queue behind the first's insert."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, f"kbrace{uuid.uuid4().hex[:12]}")
            s.add(base)
            await s.commit()

        async with factory() as first, factory() as second:
            assert await knowledge_base_repo.hold_key_share(first, base.id)
            await second.execute(text("SET LOCAL lock_timeout = '200ms'"))
            assert await knowledge_base_repo.hold_key_share(second, base.id)
            await second.rollback()
            await first.rollback()


@pytest.mark.security
async def test_a_last_base_deleted_after_the_gate_does_not_recreate_its_table(
    engine: AsyncEngine,
) -> None:
    store = _store_embedding_in_3d(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    collection = f"lastbase{uuid.uuid4().hex[:12]}"
    async with factory() as session:
        owner = _user()
        session.add(owner)
        await session.flush()
        org = await _org(session, owner)
        base = _org_collection(org.id, collection)
        session.add(base)
        await session.commit()
        ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)

    async def removed_after_gate() -> bool:
        async with factory() as session:
            await KnowledgeBaseService(session).delete(base.id, ctx=ctx)
            await session.commit()
            start_deferred(session)
        await drain()
        assert not await store._collection_exists(collection)
        return True

    processor = MagicMock(process_file=AsyncMock(return_value=_parsed("stale")))
    ingester = IngestionService(processor, store, scope=base.vector_scope)
    try:
        await store.insert_document(collection, _parsed("before"), base.vector_scope)
        result = await ingester.ingest_file(
            Path("stale.md"), collection, replace=False, still_wanted=removed_after_gate
        )
        assert result.refused
        assert not await store._collection_exists(collection)
    finally:
        async with factory() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS rag_{collection}"))
            await session.commit()


@pytest.mark.security
@pytest.mark.parametrize("reserved", [False, True])
async def test_cli_ingestion_refuses_a_reserved_collection_name(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reserved: bool
) -> None:
    from collections.abc import AsyncIterator

    from app.commands import rag as rag_command
    from app.repositories import collection_teardown_repo
    from app.services.rag.models import IngestionResult

    factory = async_sessionmaker(engine, expire_on_commit=False)
    collection = f"reserved{uuid.uuid4().hex[:12]}"
    (tmp_path / "notes.md").write_text("body")
    async with factory() as db:
        if reserved:
            await collection_teardown_repo.reserve(db, collection)
        await db.commit()

    @contextlib.asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            yield db
            await db.commit()

    logs = MagicMock(
        create_sync_log=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        complete_sync=AsyncMock(),
    )
    monkeypatch.setattr(rag_command, "get_db_context", session)
    monkeypatch.setattr(rag_command, "RAGSyncService", lambda _db: logs)
    ingestion = MagicMock(
        ingest_file=AsyncMock(
            return_value=IngestionResult(
                status=IngestionStatus.DONE, document_id="new-vector", chunk_count=1
            )
        )
    )
    await rag_command.ingest_path_async(
        str(tmp_path), collection, True, MagicMock(), MagicMock(), ingestion
    )
    assert ingestion.ingest_file.await_count == (0 if reserved else 1)
    async with factory() as db:
        docs = list(
            await db.scalars(select(RAGDocument).where(RAGDocument.collection_name == collection))
        )
        assert len(docs) == (0 if reserved else 1)
        if docs:
            assert docs[0].vector_document_id == "new-vector"
        await collection_teardown_repo.release(db, collection)
        await db.commit()


@pytest.mark.security
@pytest.mark.parametrize("operation", ["delete", "rag_drop", "keep_default", "delete_other"])
async def test_removing_a_source_target_never_reassigns_it_by_name(
    db: AsyncSession, operation: str
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.models.sync_source import SyncSource

    owner, other_owner = _user(), _user()
    db.add_all([owner, other_owner])
    await db.flush()
    org = await _org(db, owner)
    other_org = await _org(db, other_owner)
    name = f"target{uuid.uuid4().hex[:12]}"
    selected = _org_collection(org.id, name)
    selected.created_at = datetime.now(UTC) - timedelta(days=1)
    same_org_fallback = _org_collection(org.id, name)
    other_base = _org_collection(other_org.id, name)
    selected.is_default = operation == "keep_default"
    db.add_all([selected, same_org_fallback, other_base])
    source = SyncSource(
        organization_id=org.id,
        name="Private connector",
        connector_type="web",
        collection_name=name,
        config={},
        is_active=True,
    )
    other_source = SyncSource(
        organization_id=other_org.id,
        name="Other connector",
        connector_type="web",
        collection_name=name,
        config={},
        is_active=True,
    )
    db.add_all([source, other_source])
    await db.flush()
    service = KnowledgeBaseService(db)
    if operation in {"delete", "delete_other"}:
        ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
        await service.delete(
            same_org_fallback.id if operation == "delete_other" else selected.id, ctx=ctx
        )
    else:
        await service.delete_for_rag_collection(selected)
    await db.refresh(source)
    await db.refresh(other_source)
    if operation in {"keep_default", "delete_other"}:
        assert source.collection_name == name and source.is_active
    else:
        assert source.collection_name is None and not source.is_active
    assert other_source.collection_name == name and other_source.is_active


@pytest.mark.security
@pytest.mark.parametrize("reassign", [False, True])
async def test_a_queued_sync_refreshes_its_target_after_waiting_for_deletion(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, reassign: bool
) -> None:
    from collections.abc import AsyncIterator

    from app.db.models.sync_source import SyncSource
    from app.worker.tasks import rag_tasks

    factory = async_sessionmaker(engine, expire_on_commit=False)
    name = f"queued{uuid.uuid4().hex[:12]}"
    async with factory() as db:
        owner = _user()
        db.add(owner)
        await db.flush()
        org = await _org(db, owner)
        selected, fallback = _org_collection(org.id, name), _org_collection(org.id, name)
        db.add_all([selected, fallback])
        await db.flush()
        source = SyncSource(
            organization_id=org.id,
            name="Queued connector",
            connector_type="web",
            collection_name=name,
            config={},
            is_active=True,
        )
        db.add(source)
        await db.commit()
        selected_id, source_id = selected.id, str(source.id)

    @contextlib.asynccontextmanager
    async def worker_db() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            yield db
            await db.commit()

    async def delete_before_lock(db: AsyncSession, scope: LockScope, collection: str) -> None:
        async with factory() as deleting:
            kb = await deleting.get(KnowledgeBase, selected_id)
            assert kb is not None
            await KnowledgeBaseService(deleting).delete_for_rag_collection(kb)
            if reassign:
                moved = await deleting.get(SyncSource, uuid.UUID(source_id))
                assert moved is not None
                moved.collection_name = "different_collection"
            await deleting.commit()
            discard_deferred(deleting)
        await hold_name(db, scope, collection)

    resolve = AsyncMock()
    monkeypatch.setattr(rag_tasks, "get_worker_db_context", worker_db)
    monkeypatch.setattr(rag_tasks, "hold_name", delete_before_lock)
    monkeypatch.setattr(rag_tasks, "_knowledge_base_for", resolve)
    monkeypatch.setattr(rag_tasks, "_notify_sync_start_failure", AsyncMock())
    answer = await rag_tasks._sync_source(source_id, None)
    assert answer == {
        "status": "error",
        "message": (
            "Source collection changed before this sync started. Run it again."
            if reassign
            else "Source has no assigned collection."
        ),
    }
    resolve.assert_not_awaited()


@pytest.mark.security
async def test_personal_purge_locks_all_names_before_detaching_sources(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.sync_source import SyncSource
    from app.services import user as user_service

    factory = async_sessionmaker(engine, expire_on_commit=False)
    prefix = f"order{uuid.uuid4().hex[:12]}"
    async with factory() as db:
        owner = _user()
        db.add(owner)
        await db.flush()
        org = await _org(db, owner)
        first = _personal_kb(org.id, owner.id, prefix + "a")
        second = _personal_kb(org.id, owner.id, prefix + "b")
        source = SyncSource(
            organization_id=org.id,
            name="Moving source",
            connector_type="web",
            collection_name=first.collection_name,
            config={},
            is_active=True,
        )
        db.add_all([first, second, source])
        await db.commit()
        owner_id, source_id = owner.id, source.id

    waiting_for_second = asyncio.Event()

    async def observed_hold(db: AsyncSession, scope: LockScope, name: str) -> None:
        if name == second.collection_name:
            waiting_for_second.set()
        await hold_name(db, scope, name)

    monkeypatch.setattr(user_service, "hold_name", observed_hold)

    async def purge() -> None:
        async with factory() as db:
            await UserService(db)._purge_personal_collections(owner_id)
            await db.commit()
            discard_deferred(db)

    async with factory() as editing:
        await hold_name(editing, LockScope.COLLECTION_TEARDOWN, second.collection_name)
        task = asyncio.create_task(purge())
        try:
            await asyncio.wait_for(waiting_for_second.wait(), timeout=5)
            # A source edit holds the new name before updating the existing row.
            # Purge must not hold that row while waiting for this name.
            await asyncio.wait_for(
                editing.execute(
                    select(SyncSource).where(SyncSource.id == source_id).with_for_update()
                ),
                timeout=2,
            )
            await editing.commit()
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def _chunked_table(s, table: str) -> None:
    """A runtime vector table with no chunks; only these columns matter to a teardown."""
    await s.execute(
        text(f"CREATE TABLE {table} (id text PRIMARY KEY, parent_doc_id text, metadata jsonb)")
    )


async def _operators_ingest(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    collection: str,
) -> None:
    """The real `rag-ingest` into `collection`, its embedding replaced by one chunk.

    The rows are the command's own: filed under no base and tagged with no
    organization, and so is the chunk, as a `VectorScope(tenant=None)` write is."""
    from collections.abc import AsyncIterator

    from app.commands import rag as rag_command
    from app.services.rag.models import IngestionResult

    @contextlib.asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            yield db
            await db.commit()

    async def write_chunk(**_: object) -> IngestionResult:
        async with factory() as db:
            await _document_chunk(db, f"rag_{collection}", "operator-0", "operator-doc", None)
            await db.commit()
        return IngestionResult(
            status=IngestionStatus.DONE, document_id="operator-doc", chunk_count=1
        )

    (tmp_path / "manual.md").write_text("body")
    logs = MagicMock(
        create_sync_log=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        complete_sync=AsyncMock(),
    )
    monkeypatch.setattr(rag_command, "get_db_context", session)
    monkeypatch.setattr(rag_command, "RAGSyncService", lambda _db: logs)
    await rag_command.ingest_path_async(
        str(tmp_path),
        collection,
        True,
        MagicMock(),
        MagicMock(),
        MagicMock(ingest_file=AsyncMock(side_effect=write_chunk)),
    )


async def _table_exists(s: AsyncSession, table: str) -> bool:
    return (await s.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar() is not None


class TestALastHolderLeavesContentThatIsNotItsOwn:
    """A base is the last holder of a name, and the table holds chunks no base owns.

    A claim is refused on a name that already holds such content, but the content
    can arrive after the claim: `rag-ingest` writes into a held name, and the
    last holder's teardown then dropped the table with it, so a member with
    ordinary `collections:edit` destroyed an operator's collection (#2747). The
    caller has no authority over those chunks: the table stays and only the
    base's own chunks are purged. These run the real job against a real table."""

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_an_operators_ingest_outlives_the_base_it_landed_beside(
        self,
        engine: AsyncEngine,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        route: str,
    ) -> None:
        """The exact sequence, from the claim on: a member creates a base, the
        operator ingests into its name, the member deletes the base. The operator's
        collection is then what `rag-ingest` left: its row, its chunk and no base,
        which a member still cannot claim and `rag-drop` still removes whole."""
        from app.repositories import collection_teardown_repo
        from app.services.collection_access import CollectionAccessService

        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            await CollectionAccessService(s).claim(ctx, collection)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.flush()
            filed = _kb_document(collection, base.id, org.id, "")
            filed.vector_document_id = "member-doc"
            s.add(filed)
            await _chunked_table(s, table)
            await _document_chunk(s, table, "member-0", "member-doc", base.id)
            await s.commit()
            base_id, filed_id = base.id, filed.id

        try:
            await _operators_ingest(factory, monkeypatch, tmp_path, collection)

            async with factory() as s:
                await _tear_down(s, route, base_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, base_id) is None
                assert await s.get(RAGDocument, filed_id) is None
                assert await _chunk_ids(s, table) == {"operator-0"}
                rows = list(
                    await s.scalars(
                        select(RAGDocument).where(RAGDocument.collection_name == collection)
                    )
                )
                assert [(row.status, row.vector_document_id) for row in rows] == [
                    (DocumentStatus.DONE.value, "operator-doc")
                ]
                assert not await collection_teardown_repo.is_reserved(s, collection)
                with pytest.raises(AlreadyExistsError):
                    await CollectionAccessService(s).claim(ctx, collection)
                await s.rollback()

            async with factory() as s:
                assert await KnowledgeBaseService(s).drop_collection_by_name(collection) is None
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert not await _table_exists(s, table)
                assert (
                    await s.scalar(
                        select(RAGDocument.id).where(RAGDocument.collection_name == collection)
                    )
                ) is None
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_chunks_no_row_describes_keep_the_table_too(
        self, engine: AsyncEngine, route: str
    ) -> None:
        """`rag-sync-gdrive` and `rag-sync-s3` write chunks with no tracking row, so
        the table is what is asked, not the rows."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.flush()
            await _chunked_table(s, table)
            await _document_chunk(s, table, "member-0", "member-doc", base.id)
            await _document_chunk(s, table, "synced-0", "synced-doc", None)
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            base_id = base.id

        try:
            async with factory() as s:
                await _tear_down(s, route, base_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await _chunk_ids(s, table) == {"synced-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_another_tenants_unfiled_chunks_keep_their_table_and_their_rows(
        self, engine: AsyncEngine, route: str
    ) -> None:
        """The caller holds no authority over them, so they are not dropped and
        their row is not failed: nothing behind it went. The caller's own tenant's
        unfiled row goes with the base, its chunk purged by document id."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner, other = _user(), _user()
            s.add_all([owner, other])
            await s.flush()
            org = await _org(s, owner)
            other_org = await _org(s, other)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.flush()
            ours = _kb_document(collection, None, org.id, "")
            ours.vector_document_id = "ours-doc"
            theirs = _kb_document(collection, None, other_org.id, "")
            theirs.status = DocumentStatus.DONE.value
            theirs.vector_document_id = "theirs-doc"
            s.add_all([ours, theirs])
            await _chunked_table(s, table)
            await _document_chunk(s, table, "ours-0", "ours-doc", None, org.id)
            await _document_chunk(s, table, "theirs-0", "theirs-doc", None, other_org.id)
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            base_id, ours_id, theirs_id = base.id, ours.id, theirs.id

        try:
            async with factory() as s:
                await _tear_down(s, route, base_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(RAGDocument, ours_id) is None
                kept = await s.get(RAGDocument, theirs_id)
                assert kept is not None
                assert kept.status == DocumentStatus.DONE.value
                assert kept.vector_document_id == "theirs-doc"
                assert await _chunk_ids(s, table) == {"theirs-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_a_kept_table_loses_everything_the_base_takes(
        self, engine: AsyncEngine, route: str
    ) -> None:
        """The drop this replaces took every chunk of the base's, so the keep has to:
        a chunk no row names, and a filed row's chunk that was never stamped with
        the base, stayed behind and came back with the tenant's next base."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.flush()
            filed = _kb_document(collection, base.id, org.id, "")
            filed.vector_document_id = "filed-doc"
            s.add(filed)
            await _chunked_table(s, table)
            await _document_chunk(s, table, "filed-0", "filed-doc", base.id)
            await _document_chunk(s, table, "unstamped-0", "filed-doc", None, org.id)
            await _document_chunk(s, table, "rowless-0", "rowless-doc", None, org.id)
            await _document_chunk(s, table, "operator-0", "operator-doc", None)
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            base_id = base.id

        try:
            async with factory() as s:
                await _tear_down(s, route, base_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await _chunk_ids(s, table) == {"operator-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    @_TEARDOWN_ROUTES
    async def test_a_personal_bases_row_names_its_unstamped_chunk(
        self, engine: AsyncEngine, route: str
    ) -> None:
        """A personal base outside an organization takes no unfiled chunk, but a chunk
        its own row names is its own, stamped or not, as `delete_document` holds
        (#2537). Left in the kept table, it would be the app scope's to read."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            base = _personal_kb(uuid.uuid4(), owner.id, collection)
            base.organization_id = None
            s.add(base)
            await s.flush()
            filed = _kb_document(collection, base.id, None, "")
            filed.vector_document_id = "filed-doc"
            s.add(filed)
            await _chunked_table(s, table)
            await _document_chunk(s, table, "filed-0", "filed-doc", base.id)
            await _document_chunk(s, table, "unstamped-0", "filed-doc", None)
            await _document_chunk(s, table, "operator-0", "operator-doc", None)
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=None, role=OrgRoleName.OWNER)
            base_id = base.id

        try:
            async with factory() as s:
                await _tear_down(s, route, base_id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await _chunk_ids(s, table) == {"operator-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @_TEARDOWN_ROUTES
    @pytest.mark.parametrize("collection", ["documents", "Legacy_Upper"])
    async def test_a_name_the_store_refuses_can_still_be_deleted(
        self, engine: AsyncEngine, route: str, collection: str
    ) -> None:
        """A base from before a naming rule is documented as deletable. No chunk can
        reach it through the store, so the teardown does not ask, and asking would
        refuse the delete."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.commit()
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            base_id = base.id

        async with factory() as s:
            await _tear_down(s, route, base_id, ctx)
            await s.commit()
            discard_deferred(s)

        async with factory() as s:
            assert await s.get(KnowledgeBase, base_id) is None

    @pytest.mark.security
    async def test_clearing_a_last_default_keeps_the_operators_chunks(
        self, engine: AsyncEngine
    ) -> None:
        """A default keeps its row, so it holds the name after the clear as well:
        its documents' chunks go and the operator's stay."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            default = _org_collection(org.id, collection)
            default.is_default = True
            s.add(default)
            await s.flush()
            filed = _kb_document(collection, default.id, org.id, "")
            filed.vector_document_id = "member-doc"
            s.add(filed)
            await _chunked_table(s, table)
            await _document_chunk(s, table, "member-0", "member-doc", default.id)
            await _document_chunk(s, table, "operator-0", "operator-doc", None)
            await s.commit()
            default_id = default.id

        try:
            async with factory() as s:
                kb = await s.get(KnowledgeBase, default_id)
                await KnowledgeBaseService(s).delete_for_rag_collection(kb)
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, default_id) is not None
                assert await _chunk_ids(s, table) == {"operator-0"}
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    async def test_an_operators_rag_drop_still_drops_the_whole_table(
        self, engine: AsyncEngine
    ) -> None:
        """Only the operator's explicit `rag-drop` overrules it: they own what the
        table holds, and it is the one way to remove a held name's table. The rows
        left are failed, as the last holder's rules say of a dropped table (#2568)."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kboper{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.flush()
            operators = _kb_document(collection, None, None, "")
            operators.status = DocumentStatus.DONE.value
            operators.vector_document_id = "operator-doc"
            s.add(operators)
            await _chunked_table(s, table)
            await _document_chunk(s, table, "member-0", "member-doc", base.id)
            await _document_chunk(s, table, "operator-0", "operator-doc", None)
            await s.commit()
            base_id, operators_id = base.id, operators.id

        try:
            async with factory() as s:
                cleared = await KnowledgeBaseService(s).drop_collection_by_name(collection)
                assert cleared is not None
                assert cleared.id == base_id
                await s.commit()
                start_deferred(s)
            await drain()

            async with factory() as s:
                assert await s.get(KnowledgeBase, base_id) is None
                assert not await _table_exists(s, table)
                left = await s.get(RAGDocument, operators_id)
                assert left is not None
                assert left.status == DocumentStatus.ERROR.value
                assert left.vector_document_id is None
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()


async def _chunk_count(s: AsyncSession, table: str) -> int:
    return (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608


async def _waiting_on_a_lock_or_done(engine: AsyncEngine, task: asyncio.Task[None]) -> None:
    """Return once `task` has ended or a session of this database waits on a lock."""
    while not task.done():
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.02)


class TestAnUnfiledWriteInFlightAtTheTeardown:
    """The last holder's probe reads committed chunks, so a write still open when it
    ran was invisible to it: the teardown chose the drop, and the job dropped the
    chunks that committed a moment later. An unfiled write holds the name through its
    commit, so the probe waits for it, and one that comes after a drop is decided is
    refused rather than written into a table about to go (#2747)."""

    @pytest.mark.security
    @pytest.mark.parametrize("tracked", [True, False], ids=["rag-ingest", "rag-sync"])
    async def test_the_teardown_waits_for_it_and_keeps_its_table(
        self, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tracked: bool
    ) -> None:
        from app.repositories import collection_teardown_repo

        store = _store_embedding_in_3d(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbflight{uuid.uuid4().hex[:12]}"
        table = f"rag_{collection}"
        async with factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
            base = _org_collection(org.id, collection)
            s.add(base)
            await s.flush()
            row = _kb_document(collection, None, None, "")
            row.status = DocumentStatus.PROCESSING.value
            if tracked:
                s.add(row)
            await s.commit()

        writing, resume = asyncio.Event(), asyncio.Event()
        ensure = store._ensure_collection

        async def ensure_then_pause(name: str) -> None:
            await ensure(name)
            writing.set()
            await resume.wait()

        operators = _parsed("operator")
        operators.metadata.rag_document_id = row.id if tracked else None

        async def tear_down() -> None:
            async with factory() as s:
                await _tear_down(s, "kb_delete", base.id, ctx)
                await s.commit()
                start_deferred(s)
            await drain()

        try:
            await store.insert_document(collection, _parsed("member"), base.vector_scope)
            monkeypatch.setattr(store, "_ensure_collection", ensure_then_pause)
            write = asyncio.create_task(
                store.insert_document(collection, operators, VectorScope(tenant=None))
            )
            await asyncio.wait_for(writing.wait(), 10)
            teardown = asyncio.create_task(tear_down())
            await asyncio.wait_for(_waiting_on_a_lock_or_done(engine, teardown), 10)
            resume.set()
            await asyncio.wait_for(asyncio.gather(write, teardown), 30)

            async with factory() as s:
                assert await _table_exists(s, table)
                assert (await s.execute(text(f"SELECT content FROM {table}"))).scalars().all() == [  # noqa: S608
                    "operator"
                ]
                assert not await collection_teardown_repo.is_reserved(s, collection)
                if tracked:
                    kept = await s.get(RAGDocument, row.id)
                    assert kept is not None
                    assert kept.status == DocumentStatus.PROCESSING.value
        finally:
            resume.set()
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await s.commit()

    @pytest.mark.security
    async def test_a_write_after_the_drop_was_decided_is_refused(self, engine: AsyncEngine) -> None:
        """Between the commit and the job the name is reserved, and a write with no
        row to refuse it would land in the table the job then drops, reported done."""
        from app.repositories import collection_teardown_repo

        store = _store_embedding_in_3d(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbflight{uuid.uuid4().hex[:12]}"
        async with factory() as s:
            await collection_teardown_repo.reserve(s, collection)
            await s.commit()

        try:
            with pytest.raises(KnowledgeBaseRemovedError, match="being deleted"):
                await store.insert_document(collection, _parsed("late"), VectorScope(tenant=None))
            assert not await store._collection_exists(collection)
        finally:
            async with factory() as s:
                await collection_teardown_repo.release(s, collection)
                await s.execute(text(f"DROP TABLE IF EXISTS rag_{collection}"))
                await s.commit()

    @pytest.mark.security
    async def test_a_rerun_of_the_job_leaves_a_write_made_after_its_drop(
        self, engine: AsyncEngine
    ) -> None:
        """The first attempt released the name, so the write was rightly let through;
        a job failing later, or a lost lease, then runs the same drop again."""
        from app.repositories import collection_teardown_repo
        from app.worker.tasks.teardown_tasks import cleanup_external_state

        store = _store_embedding_in_3d(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        collection = f"kbflight{uuid.uuid4().hex[:12]}"
        async with factory() as s:
            await collection_teardown_repo.reserve(s, collection)
            await s.commit()

        try:
            assert (await cleanup_external_state([], [collection]))["dropped"] == 1
            await store.insert_document(collection, _parsed("after"), VectorScope(tenant=None))

            assert (await cleanup_external_state([], [collection]))["dropped"] == 0

            async with factory() as s:
                assert await _chunk_count(s, f"rag_{collection}") == 1
        finally:
            async with factory() as s:
                await s.execute(text(f"DROP TABLE IF EXISTS rag_{collection}"))
                await s.commit()
