"""A retry replaces what its own failed attempt left, never another upload's copy.

A retry is a replacing ingest, and the replace looks the stored document up by
the file's path and content. Another upload of the same file is a document a
second row tracks - one somebody can see in the list - and a retry used to
replace its chunks and retire its row, so the list lost an entry nobody touched.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.rag.ingestion import IngestionService, StoredDocument
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionStatus,
)
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio


def _document() -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(filename="img.jpg", filesize=10, filetype="jpg"),
    )
    document.chunked_pages = [
        DocumentPageChunk(chunk_content="body", chunk_num=0, page_num=1, content="body")
    ]
    return document


def _service(found: str | None) -> tuple[IngestionService, MagicMock]:
    store = MagicMock(insert_document=AsyncMock(), delete_document=AsyncMock())
    processor = MagicMock(process_file=AsyncMock(return_value=_document()))
    service = IngestionService(processor=processor, vector_store=store)
    patch.object(
        service, "existing_document", AsyncMock(return_value=StoredDocument(document_id=found))
    ).start()
    return service, store


@pytest.mark.parametrize(("allowed", "replaced"), [(False, None), (True, "vec-other")])
async def test_a_retry_replaces_only_what_no_other_row_tracks(
    allowed: bool, replaced: str | None
) -> None:
    service, store = _service(found="vec-other")
    may_replace = AsyncMock(return_value=allowed)

    result = await service.ingest_file(
        filepath=Path("img.jpg"), collection_name="docs", replace=True, may_replace=may_replace
    )

    assert result.status is IngestionStatus.DONE
    may_replace.assert_awaited_once_with("vec-other")
    assert result.replaced_document_id == replaced
    assert store.delete_document.await_count == (1 if allowed else 0)


async def test_an_upload_that_asks_to_replace_still_replaces_any_copy() -> None:
    service, store = _service(found="vec-other")

    result = await service.ingest_file(
        filepath=Path("img.jpg"), collection_name="docs", replace=True
    )

    assert result.replaced_document_id == "vec-other"
    store.delete_document.assert_awaited_once()


@asynccontextmanager
async def _session() -> AsyncIterator[MagicMock]:
    yield MagicMock()


@pytest.mark.parametrize(("others", "allowed"), [([], True), ([MagicMock()], False)])
async def test_a_stored_document_another_row_tracks_is_not_the_retrys_to_replace(
    others: list[MagicMock], allowed: bool
) -> None:
    doc_id = uuid4()
    with (
        patch.object(rag_tasks, "get_worker_db_context", _session),
        patch.object(
            rag_tasks.rag_document_repo, "get_superseded", AsyncMock(return_value=others)
        ) as superseded,
    ):
        answer = await rag_tasks._untracked_by_others("vec-1", str(doc_id), "docs")

    assert answer is allowed
    assert superseded.await_args.kwargs == {
        "collection_name": "docs",
        "vector_document_id": "vec-1",
        "keep_id": doc_id,
    }


async def test_a_lookup_that_fails_keeps_the_stored_document() -> None:
    """A duplicate is visible and removable; a deleted document is gone."""

    @asynccontextmanager
    async def broken() -> AsyncIterator[MagicMock]:
        raise RuntimeError("no database")
        yield MagicMock()  # pragma: no cover

    with patch.object(rag_tasks, "get_worker_db_context", broken):
        assert await rag_tasks._untracked_by_others("vec-1", str(uuid4()), "docs") is False
