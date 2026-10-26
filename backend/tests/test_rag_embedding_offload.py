"""Embedding HTTP must leave the event loop without losing the caller's ledger."""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.core.blocking import run_blocking_settled
from app.services.rag.config import RAGSettings
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.filters import TenantScope, compose
from app.services.rag.models import Document, DocumentMetadata, DocumentPageChunk
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("operation", ["search", "insert"])
async def test_embedding_http_runs_off_loop_and_books_the_request_ledger(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    loop_thread = threading.get_ident()
    request_scope = ContextVar("embedding_test_scope", default="missing")
    observed: list[tuple[int, str]] = []

    def respond(**kwargs: object) -> MagicMock:
        observed.append((threading.get_ident(), request_scope.get()))
        return MagicMock(data=[MagicMock(embedding=[0.1, 0.2])], usage=MagicMock(prompt_tokens=100))

    settings = RAGSettings()
    embedding = EmbeddingService(settings, api_key="test", expected_dim=2)
    embedding.provider._client = MagicMock(embeddings=MagicMock(create=respond))
    store = object.__new__(PgVectorStore)
    store.settings = settings
    monkeypatch.setattr(store, "_collection_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(store, "_ensure_collection", AsyncMock())
    monkeypatch.setattr(store, "_for_collection", AsyncMock(return_value=(embedding, 2)))
    monkeypatch.setattr(store, "_apply_search_tuning", AsyncMock())
    result = MagicMock()
    result.fetchall.return_value = []
    db = MagicMock(execute=AsyncMock(return_value=result), commit=AsyncMock())

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    monkeypatch.setattr(store, "async_session", session, raising=False)
    ledger = SpendLedger()
    token = request_scope.set("caller-tenant")
    try:
        with metered_by(ledger):
            if operation == "search":
                assert (
                    await store.search(
                        "audit", "hello", compose(TenantScope(organization_id=uuid4()), None)
                    )
                    == []
                )
            else:
                document = Document(
                    pages=[],
                    chunked_pages=[
                        DocumentPageChunk(page_num=0, content="hello", chunk_content="hello")
                    ],
                    metadata=DocumentMetadata(filename="test.txt", filesize=5, filetype="txt"),
                )
                await store.insert_document("audit", document)
    finally:
        request_scope.reset(token)
    assert observed == [(observed[0][0], "caller-tenant")]
    assert observed[0][0] != loop_thread
    assert len(ledger.entries) == 1
    assert ledger.input_tokens == 100
    assert ledger.total_usd > 0


async def test_cancellation_waits_for_started_embedding_accounting() -> None:
    entered = threading.Event()
    released = threading.Event()
    recorded: list[str] = []

    def finish_response() -> str:
        entered.set()
        assert released.wait(5)
        recorded.append("usage recorded")
        return "vectors"

    task = asyncio.create_task(run_blocking_settled(finish_response))
    try:
        async with asyncio.timeout(5):
            while not entered.is_set():  # noqa: ASYNC110
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert recorded == ["usage recorded"]
    finally:
        released.set()
        if not task.done():
            await task


@pytest.mark.parametrize("operation", ["settled", "create", "delete"])
async def test_a_failed_thread_after_cancellation_is_owned_and_drained(operation: str) -> None:
    from app.core.blocking import create_cancel_safe, delete_cancel_safe

    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    undone = []

    def work() -> None:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(3):
            raise TimeoutError("test did not release the worker")
        raise OSError("I/O failed after cancellation")

    if operation == "create":
        call = create_cancel_safe(work, lambda: undone.append(True))
    elif operation == "delete":
        call = delete_cancel_safe(work)
    else:
        call = run_blocking_settled(work)
    task = asyncio.create_task(call)
    try:
        async with asyncio.timeout(3):
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    assert undone == ([True] if operation == "create" else [])
