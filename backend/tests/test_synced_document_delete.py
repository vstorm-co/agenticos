"""Deleting a tracked document removes its vectors, whichever route asked.

#992. `RAGDocumentService.delete_document` took `ingestion_service: Any = None`
and removed vectors only when a caller happened to pass one. `DELETE
/rag/documents/{doc_id}` did; `DELETE /kb/{kb_id}/documents/{doc_id}` - the one
the Documents tab uses - did not. So deleting a document from the tab removed its
row and left the content searchable, and for a *synced* document that was
permanent: the next `new_only` run matched its unchanged hash and skipped it, so
the row never came back. The document became searchable, invisible and
undeletable again, through the delete button.

The argument has no default now, which is the structural half: a third route
cannot repeat this without the type checker saying so. These are the behavioural
half.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import rag_document_repo
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio


def _row(*, vector_document_id: str | None, storage_path: str = "") -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        collection_name="docs",
        vector_document_id=vector_document_id,
        storage_path=storage_path,
    )


class TestDeletingATrackedDocument:
    async def test_the_vectors_go_with_the_row(self, monkeypatch):
        row = _row(vector_document_id="vector-doc-1")
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=row))
        monkeypatch.setattr(rag_document_repo, "delete", AsyncMock(return_value=True))
        ingestion = MagicMock(remove_document=AsyncMock(return_value=True))

        await RAGDocumentService(MagicMock()).delete_document(str(row.id), ingestion)

        ingestion.remove_document.assert_awaited_once_with("docs", "vector-doc-1")

    async def test_a_document_with_no_vectors_asks_for_nothing(self, monkeypatch):
        """One that failed to index. There is nothing in the store to remove, and
        asking would be a query about a document that was never written."""
        row = _row(vector_document_id=None)
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=row))
        monkeypatch.setattr(rag_document_repo, "delete", AsyncMock(return_value=True))
        ingestion = MagicMock(remove_document=AsyncMock())

        await RAGDocumentService(MagicMock()).delete_document(str(row.id), ingestion)

        ingestion.remove_document.assert_not_awaited()

    async def test_a_store_that_refuses_still_removes_the_row(self, monkeypatch):
        """The cleanup is best-effort by design: a row kept because the store was
        briefly unreachable is a document a reader cannot delete at all."""
        row = _row(vector_document_id="vector-doc-1")
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=row))
        deleted = AsyncMock(return_value=True)
        monkeypatch.setattr(rag_document_repo, "delete", deleted)
        ingestion = MagicMock(remove_document=AsyncMock(side_effect=RuntimeError("no such table")))

        await RAGDocumentService(MagicMock()).delete_document(str(row.id), ingestion)

        deleted.assert_awaited_once()


class TestTheRouteThatTheDocumentsTabUses:
    async def test_the_kb_delete_route_hands_over_an_ingestion_service(self):
        """The route signature is the fix, so this asserts on the wiring: a
        `DELETE` through the knowledge base reaches `delete_document` with a
        service that can remove vectors, not with `None`."""
        from app.api.routes.v1 import knowledge_bases

        kb = MagicMock(collection_name="docs")
        doc = MagicMock(id=uuid.uuid4(), collection_name="docs")
        service = MagicMock(get_for_write=AsyncMock(return_value=kb))
        documents = MagicMock(get_document=AsyncMock(return_value=doc), delete_document=AsyncMock())
        ingestion = MagicMock(remove_document=AsyncMock())

        await knowledge_bases.delete_kb_document(
            kb_id=uuid.uuid4(),
            doc_id=doc.id,
            service=service,
            rag_doc_service=documents,
            ingestion_service=ingestion,
            ctx=MagicMock(),
        )

        documents.delete_document.assert_awaited_once_with(str(doc.id), ingestion)

    async def test_a_document_from_another_knowledge_base_is_not_deleted(self):
        """The check that was already here, kept under test because the signature
        around it moved: without it a KB owner could pass any doc_id."""
        from app.api.routes.v1 import knowledge_bases
        from app.core.exceptions import NotFoundError

        doc = MagicMock(id=uuid.uuid4(), collection_name="somebody_elses")
        documents = MagicMock(get_document=AsyncMock(return_value=doc), delete_document=AsyncMock())

        with pytest.raises(NotFoundError):
            await knowledge_bases.delete_kb_document(
                kb_id=uuid.uuid4(),
                doc_id=doc.id,
                service=MagicMock(
                    get_for_write=AsyncMock(return_value=MagicMock(collection_name="docs"))
                ),
                rag_doc_service=documents,
                ingestion_service=MagicMock(),
                ctx=MagicMock(),
            )

        documents.delete_document.assert_not_awaited()


class TestRetiringAPreviousAttempt:
    """A file that failed one sync and succeeded the next left both rows (#996).

    `complete_ingestion`'s retirement matches on `vector_document_id`, and a
    failed parse writes none - so the succeeding run had nothing to name, both
    rows survived, and the collection's `document_count` was inflated for good by
    every repeated failure.

    It cannot be matched by filename instead, which is why `rag_documents` gained
    a `source_path`: `a/readme.md` and `b/readme.md` in one bucket share a
    basename, and matching by name would delete the other file's row - the
    collision #990 removed on the vector side.
    """

    async def test_a_previous_attempt_at_the_same_file_is_discarded(self, monkeypatch):
        discard = AsyncMock(return_value=1)
        monkeypatch.setattr(rag_document_repo, "discard_unindexed", discard)
        monkeypatch.setattr(rag_document_repo, "create", AsyncMock(return_value=MagicMock()))

        await RAGDocumentService(MagicMock()).create_document(
            collection_name="docs",
            filename="readme.md",
            filesize=4,
            filetype="md",
            source_path="s3://bucket/a/readme.md",
        )

        assert discard.await_args.kwargs == {
            "collection_name": "docs",
            "source_path": "s3://bucket/a/readme.md",
        }

    async def test_a_row_with_no_address_discards_nothing(self, monkeypatch):
        """One written before the column existed, or by a path that has no
        address to give. Guessing an address from its filename is the guess the
        column exists to avoid."""
        discard = AsyncMock()
        monkeypatch.setattr(rag_document_repo, "discard_unindexed", discard)
        monkeypatch.setattr(rag_document_repo, "create", AsyncMock(return_value=MagicMock()))

        await RAGDocumentService(MagicMock()).create_document(
            collection_name="docs", filename="readme.md", filesize=4, filetype="md"
        )

        discard.assert_not_awaited()

    async def test_the_address_is_recorded_on_the_row(self, monkeypatch):
        monkeypatch.setattr(rag_document_repo, "discard_unindexed", AsyncMock(return_value=0))
        created = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(rag_document_repo, "create", created)

        await RAGDocumentService(MagicMock()).create_document(
            collection_name="docs",
            filename="readme.md",
            filesize=4,
            filetype="md",
            source_path="gdrive://file-1",
        )

        assert created.await_args.kwargs["source_path"] == "gdrive://file-1"
