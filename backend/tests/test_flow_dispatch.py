"""The three services that hand a flow work it can only do after the commit.

#417. Each of these writes a row and dispatches a Prefect flow whose first act
is to read that row back by id, on a session of its own. Started when it was
created, the flow looked for a row no other transaction could see yet and gave
up: an upload that answered `{"status": "processing"}` and stayed that way, a
sync log that never moved off `running`.

`tests/integration/test_flow_starts_after_commit.py` proves the ordering
against a real database. These pin the three call sites to it - that the work
is *queued on the session* and not started, and that it runs when the session
says the transaction landed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core import background
from app.core.config import settings
from app.core.permissions import AuthContext
from app.repositories import rag_document_repo
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo
from app.services import rag_sync
from app.services.ingestion_config import IngestionConfig, IngestionConfigService
from app.services.rag_document import RAGDocumentService
from app.services.rag_sync import RAGSyncService
from app.services.sync_source import SyncSourceService
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def no_leftovers():
    """Module state, so a task one test starts is not drained by the next."""
    background._running.clear()
    yield
    background._running.clear()


@pytest.fixture
def session():
    """A session with no bind: only its `info` is in play here."""
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession()


def _nothing_started(what: str) -> str:
    """Why an empty task set is the assertion rather than an empty result list.

    A task created with `spawn` has not *run* when the call returns either - the
    loop starts it at the next suspension point, and there is none between the
    service returning and the assertion. What separates the two handoffs at that
    instant is whether a task exists at all.
    """
    return f"{what} was handed to the event loop before the commit (#417)"


async def _run_deferred(session) -> None:
    """What `_managed_session` does the instant its commit returns."""
    background.start_deferred(session)
    await background.drain(timeout=5.0)


async def test_a_local_sync_starts_after_its_log_row_is_committed(session, monkeypatch) -> None:
    dispatched: list[str] = []
    sync_log = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(sync_log_repo, "create", AsyncMock(return_value=sync_log))

    async def flow(*, sync_log_id: str, **_: Any) -> None:
        dispatched.append(sync_log_id)

    monkeypatch.setattr(rag_sync, "sync_collection_flow", flow)

    await RAGSyncService(session).start_local_sync(
        collection_name="handbooks", mode="full", path="/srv/docs"
    )

    assert not background._running, _nothing_started("the local sync")
    assert dispatched == []

    await _run_deferred(session)
    assert dispatched == [str(sync_log.id)]


async def test_a_triggered_source_sync_starts_after_its_log_row_is_committed(
    session, monkeypatch
) -> None:
    dispatched: list[tuple[str, str]] = []
    source = SimpleNamespace(
        id=uuid4(),
        connector_type="google_drive",
        collection_name="handbooks",
        sync_mode="full",
    )
    sync_log = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(sync_source_repo, "get_by_id", AsyncMock(return_value=source))
    monkeypatch.setattr(sync_log_repo, "create", AsyncMock(return_value=sync_log))

    async def flow(source_id: str, sync_log_id: str) -> None:
        dispatched.append((source_id, sync_log_id))

    monkeypatch.setattr(rag_tasks, "sync_single_source_flow", flow)

    await SyncSourceService(session).trigger_sync(str(source.id))

    assert not background._running, _nothing_started("the source sync")
    assert dispatched == []

    await _run_deferred(session)
    assert dispatched == [(str(source.id), str(sync_log.id))]


async def test_an_uploaded_document_is_parsed_after_its_row_is_committed(
    session, monkeypatch, tmp_path: Path
) -> None:
    """The upload path, which is where #417 was actually noticed."""
    dispatched: list[str] = []
    document = SimpleNamespace(id=uuid4())
    collection = SimpleNamespace(
        collection_name="handbooks",
        embedding_model="text-embedding-3-small",
        ingestion_config=IngestionConfig().model_dump(mode="json"),
    )

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(rag_document_repo, "create", AsyncMock(return_value=document))
    monkeypatch.setattr(
        IngestionConfigService, "resolved_image_model", AsyncMock(return_value=None)
    )
    storage = SimpleNamespace(save=AsyncMock(return_value="rag/handbooks/policy.txt"))
    monkeypatch.setattr("app.services.rag_document.get_file_storage", lambda: storage)

    async def flow(*, rag_document_id: str, **_: Any) -> None:
        dispatched.append(rag_document_id)

    monkeypatch.setattr(rag_tasks, "ingest_document_flow", flow)

    accepted = await RAGDocumentService(session).dispatch_upload(
        ctx=AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        collection=collection,
        file_data=b"a policy nobody reads",
        filename="policy.txt",
        replace=False,
        vector_store=SimpleNamespace(create_collection=AsyncMock()),
    )

    assert accepted.status == "processing"
    assert not background._running, (
        "the parse was started before the commit, so it looks for this document "
        "by id and finds nothing - and the upload it answered `processing` stays "
        "that way forever (#417)"
    )
    assert dispatched == []

    await _run_deferred(session)
    assert dispatched == [str(document.id)]
