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
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import background
from app.repositories import rag_document_repo
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_leftover_tasks():
    """A deferred unlink one test starts must not be drained by the next."""
    background._running.clear()
    yield
    background._running.clear()


def _deferring_db() -> MagicMock:
    """A session stand-in whose `info` is a real dict, so `spawn_after_commit`
    queues on it the way a live session's does."""
    db = MagicMock()
    db.info = {}
    return db


async def _run_deferred(db: MagicMock) -> None:
    """What `_managed_session` does the instant its commit returns."""
    background.start_deferred(db)
    await background.drain(timeout=5.0)


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

    async def test_the_stored_file_is_unlinked_after_the_commit(self, monkeypatch):
        """The row and its vectors go in the transaction; the file is unlinked only
        once it commits, so a rollback keeps it beside the restored row (#1293)."""
        row = _row(vector_document_id="vector-doc-1", storage_path="rag/docs/report.pdf")
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=row))
        monkeypatch.setattr(rag_document_repo, "delete", AsyncMock(return_value=True))
        storage = MagicMock(delete=AsyncMock())
        monkeypatch.setattr("app.services.file_storage.get_file_storage", lambda: storage)
        ingestion = MagicMock(remove_document=AsyncMock(return_value=True))
        db = _deferring_db()

        await RAGDocumentService(db).delete_document(str(row.id), ingestion)
        storage.delete.assert_not_awaited()

        await _run_deferred(db)
        storage.delete.assert_awaited_once_with("rag/docs/report.pdf")

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
        monkeypatch.setattr(rag_document_repo, "discard_failed", discard)
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

    async def test_an_upload_retires_nothing(self, monkeypatch):
        """An upload's only name is a basename, which is not an address: two
        people can upload different `report.pdf`s and, with `replace=false`, mean
        both to exist. Retiring by that name would delete the first one's failed
        row - its diagnosis, its retry and its stored file - for a caller who
        asked for no such thing."""
        discard = AsyncMock()
        monkeypatch.setattr(rag_document_repo, "discard_failed", discard)
        monkeypatch.setattr(rag_document_repo, "create", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(
            "app.services.rag_document.get_file_storage",
            lambda: MagicMock(save=AsyncMock(return_value="rag/docs/report.pdf")),
        )

        await RAGDocumentService(MagicMock()).create_document(
            collection_name="docs",
            filename="report.pdf",
            filesize=4,
            filetype="pdf",
            storage_path="rag/docs/report.pdf",
        )

        discard.assert_not_awaited()

    async def test_a_row_with_no_address_discards_nothing(self, monkeypatch):
        """One written before the column existed, or by a path that has no
        address to give. Guessing an address from its filename is the guess the
        column exists to avoid."""
        discard = AsyncMock()
        monkeypatch.setattr(rag_document_repo, "discard_failed", discard)
        monkeypatch.setattr(rag_document_repo, "create", AsyncMock(return_value=MagicMock()))

        await RAGDocumentService(MagicMock()).create_document(
            collection_name="docs", filename="readme.md", filesize=4, filetype="md"
        )

        discard.assert_not_awaited()

    async def test_the_address_is_recorded_on_the_row(self, monkeypatch):
        monkeypatch.setattr(rag_document_repo, "discard_failed", AsyncMock(return_value=0))
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


class TestTheCLISync:
    """`agenticos cmd rag-ingest` is the third ingest path, and it was the one
    left out. Its rows got `NULL` for an address, so a file failing there
    repeatedly kept inflating the collection's count - the defect #996 fixed for
    the two worker flows (found reviewing #1001)."""

    async def test_it_records_the_address_it_already_looks_documents_up_by(
        self, monkeypatch, tmp_path
    ):
        from app.commands import rag as rag_command

        (tmp_path / "handbook.md").write_text("body")
        created = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        documents = MagicMock(
            create_document=created,
            complete_ingestion=AsyncMock(),
            fail_ingestion=AsyncMock(),
        )
        ingestion = MagicMock(
            existing_document=AsyncMock(
                return_value=MagicMock(document_id=None, content_hash=None)
            ),
            ingest_file=AsyncMock(
                return_value=MagicMock(
                    status=MagicMock(value="done"),
                    document_id="vector-doc-1",
                    chunk_count=2,
                    replaced_document_id=None,
                    message="Successfully ingested 'handbook.md'",
                    error_message=None,
                )
            ),
        )

        @asynccontextmanager
        async def _db() -> Any:
            yield MagicMock()

        monkeypatch.setattr(rag_command, "get_db_context", _db)
        monkeypatch.setattr(rag_command, "RAGDocumentService", lambda _db: documents)
        monkeypatch.setattr(
            rag_command,
            "RAGSyncService",
            lambda _db: MagicMock(
                create_sync_log=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
                complete_sync=AsyncMock(),
            ),
        )

        await rag_command.ingest_path_async(
            path=str(tmp_path),
            collection="docs",
            recursive=True,
            vector_store=MagicMock(create_collection=AsyncMock()),
            processor=MagicMock(),
            ingestion=ingestion,
        )

        expected = str((tmp_path / "handbook.md").resolve())
        assert created.await_args.kwargs["source_path"] == expected
        # And the stored document identifies itself the same way, so the row and
        # the vector agree on which file this is.
        assert ingestion.ingest_file.await_args.kwargs["source_path"] == expected


class TestDroppingACollection:
    async def test_it_unlinks_the_stored_uploads_after_the_commit(self, monkeypatch):
        """The bulk row delete returns the storage paths, and the unlink is deferred
        past the commit so a rollback keeps the files (#1265, #1293)."""
        monkeypatch.setattr(
            rag_document_repo,
            "delete_by_collection",
            AsyncMock(return_value=["rag/docs/a.pdf", "rag/docs/b.md"]),
        )
        storage = MagicMock(delete=AsyncMock())
        monkeypatch.setattr("app.services.file_storage.get_file_storage", lambda: storage)
        db = _deferring_db()

        await RAGDocumentService(db).delete_by_collection("docs")
        storage.delete.assert_not_awaited()

        await _run_deferred(db)
        assert storage.delete.await_count == 2
        storage.delete.assert_any_await("rag/docs/a.pdf")
        storage.delete.assert_any_await("rag/docs/b.md")

    async def test_a_rolled_back_drop_keeps_the_files(self, monkeypatch):
        """The unlink is discarded when the transaction that removed the rows did
        not commit, so the restored rows still point at their files (#1293)."""
        monkeypatch.setattr(
            rag_document_repo,
            "delete_by_collection",
            AsyncMock(return_value=["rag/docs/a.pdf"]),
        )
        storage = MagicMock(delete=AsyncMock())
        monkeypatch.setattr("app.services.file_storage.get_file_storage", lambda: storage)
        db = _deferring_db()

        await RAGDocumentService(db).delete_by_collection("docs")
        background.discard_deferred(db)
        await background.drain(timeout=5.0)

        storage.delete.assert_not_awaited()

    async def test_a_failed_unlink_does_not_raise(self, monkeypatch):
        """A file already gone is not a reason for the deferred unlink to fail."""
        monkeypatch.setattr(
            rag_document_repo,
            "delete_by_collection",
            AsyncMock(return_value=["rag/docs/gone.pdf"]),
        )
        storage = MagicMock(delete=AsyncMock(side_effect=FileNotFoundError()))
        monkeypatch.setattr("app.services.file_storage.get_file_storage", lambda: storage)
        db = _deferring_db()

        await RAGDocumentService(db).delete_by_collection("docs")
        await _run_deferred(db)

        storage.delete.assert_awaited_once()
