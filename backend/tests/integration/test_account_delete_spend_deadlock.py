"""Deleting an account while an ingest records its spend finishes both (#2638).

An ingest's spend row references the organization and the document, and
`ingestion_spend_repo.record` holds the two `FOR KEY SHARE` in that order - the
order `OrganizationService.purge` locks them in. Account deletion used to delete
the personal knowledge bases' documents first and only then reach the purge's
`FOR UPDATE` on the personal organization: the spend held the organization and
waited for the document, the deletion held the document and waited for the
organization, and Postgres aborted one of them. The deletion now locks the
personal organization before it deletes anything under it.

Integration because the deadlock is two transactions the database arbitrates,
which a mock cannot show.
"""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.agents.capabilities.budget import SpendLedger
from app.core.background import discard_deferred
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.rag_document import RAGDocument
from app.db.models.user import User
from app.services import user as user_service
from app.services.user import UserService
from app.worker.tasks import rag_tasks
from tests.integration.test_deletion_reconciliation import (
    _kb_document,
    _org,
    _personal_kb,
    _user,
)

pytestmark = pytest.mark.anyio

_MODEL = "text-embedding-3-small"


async def _until_a_statement_waits_on_a_lock(factory: async_sessionmaker[Any]) -> None:
    for _ in range(250):
        async with factory() as s:
            waiting = await s.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("No statement ever waited on a lock")


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

    async def delete_then_let_the_spend_in(db: Any, knowledge_base_id: uuid.UUID) -> list[str]:
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
    goes with the organization it was billed to."""
    record = rag_tasks.ingestion_spend_repo.record
    deleting: list[asyncio.Task[None]] = []

    async def record_then_let_the_deletion_in(db: Any, **kwargs: Any) -> object:
        spend = await record(db, **kwargs)
        deleting.append(asyncio.create_task(account.delete()))
        await _until_a_statement_waits_on_a_lock(account.factory)
        return spend

    monkeypatch.setattr(rag_tasks.ingestion_spend_repo, "record", record_then_let_the_deletion_in)

    await asyncio.wait_for(account.record_spend(), timeout=10)
    await asyncio.wait_for(deleting[0], timeout=10)

    assert await account.gone()
    assert await account.spend() == []
