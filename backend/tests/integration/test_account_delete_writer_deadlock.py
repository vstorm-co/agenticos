"""Deleting an account while its owner writes finishes both (#2682).

A write for the person being deleted takes their personal organization and their
user row `FOR KEY SHARE` through its foreign keys, in the order its table's
constraint triggers fire. That order is not the same for every table: on a
migrated database a knowledge base or a notification takes the organization
first, an agent or a vault secret the user first. A deletion that waits for one
of the two while holding the other deadlocks with one of those kinds, whichever
it picks, so it holds neither while it waits for the other - the lock phase on
`UserService._lock_account`.

The writers below take the two locks explicitly, in the production order, before
their insert: this schema is built by `create_all`, which creates the constraints
in another order than the migrations do, and an insert on its own would not show
the order a deployment has. Integration because the deadlock is two transactions
the database arbitrates, which a mock cannot show.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.db.locks import LockScope, hold_name
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User
from app.repositories import organization_repo, user_repo
from app.services import rag_document as rag_document_service
from app.services.rag_document import RAGDocumentService
from app.services.user import UserService
from tests.integration.test_deletion_reconciliation import (
    _kb_document,
    _member,
    _org,
    _personal_kb,
    _user,
)
from tests.integration.test_document_delete_mid_ingest import _until_a_statement_waits_on_a_lock

pytestmark = pytest.mark.anyio


class _Account:
    """A user, their personal organization and a personal base with one document."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.factory = async_sessionmaker(engine, expire_on_commit=False)

    async def open(self) -> None:
        collection = f"writerdeadlock{uuid.uuid4().hex[:12]}"
        async with self.factory() as s:
            user = _user()
            s.add(user)
            await s.flush()
            org = await _org(s, user, is_personal=True)
            base = _personal_kb(org.id, user.id, collection)
            s.add(base)
            await s.flush()
            document = _kb_document(collection, base.id, org.id, "")
            document.status = DocumentStatus.PROCESSING.value
            document.initiated_by_user_id = user.id
            s.add(document)
            await s.commit()
        self.user_id = user.id
        self.organization_id = org.id
        self.document_id = document.id

    async def delete(self) -> None:
        async with self.factory() as s:
            await UserService(s).delete(self.user_id)
            await s.commit()
            # The queued cleanup is the worker's; nothing here runs one.
            discard_deferred(s)

    async def gone(self) -> bool:
        async with self.factory() as s:
            return (
                await s.get(User, self.user_id) is None
                and await s.get(Organization, self.organization_id) is None
            )

    async def bases_named(self, name: str) -> list[KnowledgeBase]:
        async with self.factory() as s:
            found = await s.scalars(
                select(KnowledgeBase).where(KnowledgeBase.collection_name == name)
            )
            return list(found.all())


@pytest.fixture
async def account(engine: AsyncEngine) -> _Account:
    opened = _Account(engine)
    await opened.open()
    return opened


async def _create_a_base_while_the_account_is_deleted(
    account: _Account, *, locks: Callable[[AsyncSession], Awaitable[None]]
) -> str:
    """The owner's `POST /kb`: the name claimed, `locks` taken, then the deletion
    starts and queues on them, then the insert and the commit."""
    name = f"newbase{uuid.uuid4().hex[:12]}"
    async with account.factory() as writer:
        await hold_name(writer, LockScope.COLLECTION_TEARDOWN, name)
        await locks(writer)
        deleting = asyncio.create_task(account.delete())
        await _until_a_statement_waits_on_a_lock(account.factory)
        writer.add(_personal_kb(account.organization_id, account.user_id, name))
        await writer.flush()
        await writer.commit()
    await asyncio.wait_for(deleting, timeout=15)
    return name


async def test_a_base_the_owner_creates_organization_first_is_torn_down_with_the_account(
    account: _Account,
) -> None:
    """A base's foreign keys take the organization, then the user (the migrated
    schema's order). Before the fix the deletion held the user and waited for the
    organization while the insert held the organization and waited for the user:
    a 40P01 for one of the two. Now the deletion waits for the organization
    holding no user row, the base commits, and the deletion finds it under its
    locks and removes it with the account."""

    async def organization_then_user(writer: AsyncSession) -> None:
        await organization_repo.hold_key_share(writer, account.organization_id)

    name = await _create_a_base_while_the_account_is_deleted(account, locks=organization_then_user)

    assert await account.gone()
    assert await account.bases_named(name) == []


async def test_a_row_the_owner_creates_user_first_does_not_deadlock_either(
    account: _Account,
) -> None:
    """The other order, an agent's or a vault secret's in the migrated schema: the
    user first, then the organization. A deletion that simply took the
    organization before the user would deadlock with this one instead; it finds
    the user row taken, lets the organization go, waits for the user row holding
    nothing, and starts again."""

    async def user_first(writer: AsyncSession) -> None:
        await user_repo.hold_key_share(writer, [account.user_id])

    name = await _create_a_base_while_the_account_is_deleted(account, locks=user_first)

    assert await account.gone()
    assert await account.bases_named(name) == []


def _then_let_the_deletion_in[**P, R](
    write: Callable[P, Awaitable[R]], account: _Account, deleting: list[asyncio.Task[None]]
) -> Callable[P, Awaitable[R]]:
    """`write`, then the account's deletion started and waiting on a lock."""

    async def written(*args: P.args, **kwargs: P.kwargs) -> R:
        result = await write(*args, **kwargs)
        deleting.append(asyncio.create_task(account.delete()))
        await _until_a_statement_waits_on_a_lock(account.factory)
        return result

    return written


class _FailedIngest:
    """A failed ingest settling for the account's document, paused right after
    its status write until the deletion is waiting on a lock."""

    def __init__(self, account: _Account, monkeypatch: pytest.MonkeyPatch) -> None:
        self.account = account
        self.deleting: list[asyncio.Task[None]] = []
        monkeypatch.setattr(
            rag_document_service.rag_document_repo,
            "update_status",
            _then_let_the_deletion_in(
                rag_document_service.rag_document_repo.update_status, account, self.deleting
            ),
        )

    async def settle(self, document_id: uuid.UUID) -> None:
        async with self.account.factory() as s:
            await RAGDocumentService(s).fail_ingestion(str(document_id), "parse error", attempt=1)
            await s.commit()
        await asyncio.wait_for(self.deleting[0], timeout=15)


async def test_a_failed_ingest_of_a_personal_document_settles_and_the_account_goes(
    account: _Account, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The settlement wrote the document's status and then the notification,
    whose keys take the organization and the user. The deletion, holding both,
    deleted the document and waited for the settlement's row lock: a 40P01. The
    settlement now takes the organization and the uploader first, so the
    deletion queues behind it and finds the document settled."""
    failed = _FailedIngest(account, monkeypatch)

    with caplog.at_level(logging.ERROR, logger=rag_document_service.logger.name):
        await failed.settle(account.document_id)

    assert await account.gone()
    async with account.factory() as s:
        assert await s.get(RAGDocument, account.document_id) is None
    assert not [r for r in caplog.records if "Failed to notify" in r.getMessage()]


async def test_a_failed_ingest_the_person_uploaded_to_a_shared_organization_settles(
    account: _Account, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The user-row path the issue names: a document the person uploaded to a
    team's organization. The deletion does not touch that organization, but
    removing the user sets the document's `initiated_by_user_id` to null, which
    waits for the settlement's row lock while the settlement's notification
    waited for the user row. The settlement holds the uploader first now."""
    async with account.factory() as s:
        founder = _user()
        s.add(founder)
        await s.flush()
        team = await _org(s, founder)
        await _member(s, team.id, account.user_id, "member")
        document = _kb_document("teamdocs", None, team.id, "")
        document.status = DocumentStatus.PROCESSING.value
        document.initiated_by_user_id = account.user_id
        s.add(document)
        await s.commit()
    failed = _FailedIngest(account, monkeypatch)

    with caplog.at_level(logging.ERROR, logger=rag_document_service.logger.name):
        await failed.settle(document.id)

    assert await account.gone()
    async with account.factory() as s:
        settled = await s.get(RAGDocument, document.id)
        assert settled is not None
        assert settled.status == DocumentStatus.ERROR.value
        assert settled.initiated_by_user_id is None
    assert not [r for r in caplog.records if "Failed to notify" in r.getMessage()]


async def test_writes_for_an_administrator_do_not_refuse_an_unrelated_deletion(
    account: _Account,
) -> None:
    """`admin_delete` locks the app-admin set (#1208) without waiting, so it must
    not take it in a mode every write referencing an administrator conflicts
    with: back-to-back writes for one admin would refuse every deletion."""
    async with account.factory() as s:
        administrator = _user()
        administrator.is_app_admin = True
        s.add(administrator)
        await s.commit()
    stop = asyncio.Event()

    async def write_for_the_administrator() -> None:
        while not stop.is_set():
            async with account.factory() as writer:
                await user_repo.hold_key_share(writer, [administrator.id])
                await asyncio.sleep(0.03)
                await writer.commit()

    writers = [asyncio.create_task(write_for_the_administrator()) for _ in range(3)]
    try:
        await asyncio.sleep(0.05)
        async with account.factory() as s:
            await asyncio.wait_for(
                UserService(s).admin_delete(account.user_id, acting_admin_id=administrator.id),
                timeout=15,
            )
            await s.commit()
            discard_deferred(s)
    finally:
        stop.set()
        await asyncio.gather(*writers)

    assert await account.gone()
