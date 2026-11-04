"""Deleting an account while an ingest records its spend finishes both (#2638).

The lock order is explained on `UserService._lock_account`.
Integration because the deadlock is two transactions the database arbitrates,
which a mock cannot show.
"""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.budget import SpendLedger
from app.core.background import discard_deferred
from app.core.exceptions import ConcurrentChangeError
from app.db.locks import LockScope, hold_name
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.rag_document import RAGDocument
from app.db.models.user import User
from app.repositories import sync_source_repo
from app.services import user as user_service
from app.services.user import UserService
from app.worker.tasks import rag_tasks
from tests.integration.test_deletion_reconciliation import (
    _kb_document,
    _org,
    _org_collection,
    _personal_kb,
    _user,
)
from tests.integration.test_document_delete_mid_ingest import _until_a_statement_waits_on_a_lock

pytestmark = pytest.mark.anyio

_MODEL = "text-embedding-3-small"


class _Account:
    """A user, their personal organization, and a personal base with one document."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.factory = async_sessionmaker(engine, expire_on_commit=False)

    async def open(self) -> None:
        collection = f"spenddeadlock{uuid.uuid4().hex[:12]}"
        async with self.factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user, is_personal=True)
            base = _personal_kb(org.id, user.id, collection)
            s.add(base)
            await s.flush()
            document = _kb_document(collection, base.id, org.id, "")
            s.add(document)
            await s.commit()
        self.user_id = user.id
        self.organization_id = org.id
        self.base_id = base.id
        self.document_id = document.id

    async def delete(self) -> None:
        async with self.factory() as s:
            await UserService(s).delete(self.user_id)
            await s.commit()
            # The queued cleanup is the worker's; nothing here runs one.
            discard_deferred(s)

    async def record_spend(self) -> None:
        """What `ingest_document` books for the document once its window closes."""
        ledger = SpendLedger(organization_id=self.organization_id)
        ledger.record_cost(_MODEL, Decimal("0.0002"))
        await rag_tasks._record_embedding_spend(
            ledger, organization_id=self.organization_id, rag_document_id=self.document_id
        )

    async def gone(self) -> bool:
        async with self.factory() as s:
            return (
                await s.get(User, self.user_id) is None
                and await s.get(Organization, self.organization_id) is None
                and await s.get(KnowledgeBase, self.base_id) is None
                and await s.get(RAGDocument, self.document_id) is None
            )

    async def spend(self) -> list[tuple[uuid.UUID | None, uuid.UUID | None]]:
        async with self.factory() as s:
            rows = await s.execute(
                select(IngestionSpend.organization_id, IngestionSpend.rag_document_id)
            )
            return [(org_id, doc_id) for org_id, doc_id in rows.all()]


@pytest.fixture
async def account(engine: AsyncEngine) -> _Account:
    opened = _Account(engine)
    await opened.open()
    return opened


async def test_a_spend_recorded_while_the_account_deletes_its_documents_lets_both_finish(
    account: _Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spend arrives just after the deletion removed the personal documents.

    Before the fix it took the organization `KEY SHARE` and waited for the
    deleted document, and the deletion then waited for the organization `FOR
    UPDATE`: a 40P01 for one of the two. Now the deletion holds the
    organization by then, so the spend waits for it, and once the account is
    gone it finds no organization to bill and writes nothing - the cascade would
    have removed the row anyway.
    """
    recording: list[asyncio.Task[None]] = []
    delete_documents = user_service.rag_document_repo.delete_by_knowledge_base

    async def delete_then_let_the_spend_in(
        db: AsyncSession, knowledge_base_id: uuid.UUID
    ) -> list[str]:
        deleted = await delete_documents(db, knowledge_base_id)
        recording.append(asyncio.create_task(account.record_spend()))
        await _until_a_statement_waits_on_a_lock(account.factory)
        return deleted

    monkeypatch.setattr(
        user_service.rag_document_repo, "delete_by_knowledge_base", delete_then_let_the_spend_in
    )

    await asyncio.wait_for(account.delete(), timeout=10)
    await asyncio.wait_for(recording[0], timeout=10)

    assert await account.gone()
    assert await account.spend() == []


async def test_a_spend_holding_its_locks_first_is_kept_and_then_deleted_with_the_account(
    account: _Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other order: the spend holds the organization and the document when the
    deletion starts. The deletion waits for the spend's commit, and the row then
    goes with the organization it was billed to. This order finished before the
    fix too; it pins that the new lock does not break it."""
    record = rag_tasks.ingestion_spend_repo.record
    deleting: list[asyncio.Task[None]] = []

    async def record_then_let_the_deletion_in(
        db: AsyncSession, **kwargs: Any
    ) -> IngestionSpend | None:
        spend = await record(db, **kwargs)
        deleting.append(asyncio.create_task(account.delete()))
        await _until_a_statement_waits_on_a_lock(account.factory)
        return spend

    monkeypatch.setattr(rag_tasks.ingestion_spend_repo, "record", record_then_let_the_deletion_in)

    await asyncio.wait_for(account.record_spend(), timeout=10)
    await asyncio.wait_for(deleting[0], timeout=10)

    assert await account.gone()
    assert await account.spend() == []


class _BaseCreatedDuringTheDeletion:
    """An org-scoped base in the personal organization, inserted but not yet
    committed when the deletion reads what it tears down.

    It references the organization only - no user - so the deleting user's row
    lock does not hold it back, and the deletion's `FOR UPDATE` on the
    organization waits for its commit. The deletion's first read never saw it.
    """

    def __init__(self, account: _Account) -> None:
        self.account = account
        self.name = f"lateclaim{uuid.uuid4().hex[:12]}"

    async def delete_while_it_commits(self) -> asyncio.Task[None]:
        account = self.account
        claim = account.factory()
        claim.add(_org_collection(account.organization_id, self.name))
        await claim.flush()
        deleting = asyncio.create_task(account.delete())
        await _until_a_statement_waits_on_a_lock(account.factory)
        await claim.commit()
        await claim.close()
        return deleting


async def test_a_base_created_while_the_organization_lock_waits_is_torn_down_without_a_deadlock(
    account: _Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source added to that base holds its name and then needs the organization.

    Had the deletion found the name only at the purge, with the organization
    already held, it would have waited for the name while the source waited for
    the organization. It is found under the lock and taken first, so the source
    waits for the deletion and then finds no organization to belong to.
    """
    late = _BaseCreatedDuringTheDeletion(account)
    adding: list[asyncio.Task[None]] = []

    async def add_a_source() -> None:
        async with account.factory() as s:
            await hold_name(s, LockScope.COLLECTION_TEARDOWN, late.name)
            await sync_source_repo.create(
                s,
                name="drive",
                connector_type="s3",
                config={},
                organization_id=account.organization_id,
                collection_name=late.name,
            )
            await s.commit()

    purge_personal = UserService._purge_personal_collections

    async def purge_then_add_a_source(self: UserService, user_id: uuid.UUID) -> None:
        await purge_personal(self, user_id)
        adding.append(asyncio.create_task(add_a_source()))
        await _until_a_statement_waits_on_a_lock(account.factory)

    monkeypatch.setattr(UserService, "_purge_personal_collections", purge_then_add_a_source)

    deleting = await late.delete_while_it_commits()
    await asyncio.wait_for(deleting, timeout=10)
    with pytest.raises(DBAPIError) as refused:
        await asyncio.wait_for(adding[0], timeout=10)

    # The source's own insert, refused by the organization's foreign key - not a
    # deadlock breaking the cycle.
    assert getattr(refused.value.orig, "sqlstate", None) == "23503"
    assert "sync_sources" in str(refused.value)
    assert await account.gone()


async def test_a_base_created_while_the_organization_lock_waits_on_a_busy_name_refuses(
    account: _Account,
) -> None:
    """The name of that late base is held by something else: waiting for it with
    the organization held could close a cycle, so the deletion refuses whole."""
    late = _BaseCreatedDuringTheDeletion(account)

    async with account.factory() as busy:
        await hold_name(busy, LockScope.COLLECTION_TEARDOWN, late.name)
        deleting = await late.delete_while_it_commits()
        with pytest.raises(ConcurrentChangeError):
            await asyncio.wait_for(deleting, timeout=10)
        await busy.rollback()

    async with account.factory() as s:
        assert await s.get(User, account.user_id) is not None
        assert await s.get(Organization, account.organization_id) is not None
        assert await s.get(RAGDocument, account.document_id) is not None
