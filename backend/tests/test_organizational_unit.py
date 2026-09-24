"""Where `organizational_unit` comes from (#1777).

It was one of the four FA-039 filter dimensions #1656 shipped: `ingest_file`
accepted it and stamped it on every chunk, `PgVectorStore` filtered on it, an
index served that filter and `/rag/collections/{name}/filters` reported the
distinct values a collection holds. Nothing wrote it. So the filter matched
nothing - a chunk with no value for a filtered dimension fails closed, by design
- and the facet answered with an empty list for every collection in every
deployment, correct and with no data behind it.

Two writers now, and these pin both: a per-source default every document a sync
brings in inherits, and a per-upload value recorded on the `rag_documents` row
the worker reads back. What each of them must *not* do is turn a blank into a
unit named `""`, which would be offered in the facet and match only the
documents nobody filed.

This module is template-inherited and outside the coverage gate, which is why
the behaviour is pinned by name rather than trusted to a percentage.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.sync_source import SyncSourceCreate, SyncSourceUpdate
from app.services.rag.connectors import RemoteFile, RemoteListing
from app.services.rag.models import IngestionStatus
from app.services.rag_document import RAGDocumentService
from app.worker.tasks import rag_tasks
from app.worker.tasks.rag_tasks import _run_ingestion

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("sole_source_run")]


def _create(**overrides: object) -> SyncSourceCreate:
    fields: dict[str, object] = {
        "name": "Handbook drive",
        "connector_type": "gdrive",
        "collection_name": "handbook",
        "config": {"folder_id": "1AbC"},
    }
    return SyncSourceCreate.model_validate({**fields, **overrides})


class TestABlankUnitIsNoUnitAtAll:
    """An empty string reaches the chunk metadata and then the facet endpoint,
    where it is a unit named `""` offered in the filter - matching only the
    documents whose field was left blank. Clearing the field in a form sends
    `""` rather than omitting the key, so this is what makes that a clear."""

    def test_an_absent_unit_stays_absent(self):
        assert _create().organizational_unit is None

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_a_blank_one_is_recorded_as_none(self, blank: str):
        assert _create(organizational_unit=blank).organizational_unit is None

    def test_a_real_one_is_kept_and_trimmed(self):
        assert _create(organizational_unit="  Legal  ").organizational_unit == "Legal"

    def test_clearing_it_through_an_update_is_a_clear_and_not_a_value(self):
        update = SyncSourceUpdate(organizational_unit="  ")

        assert update.organizational_unit is None
        # Still *set*, so `writable` carries it to the column rather than
        # leaving the source's old unit in place.
        assert "organizational_unit" in update.model_dump(exclude_unset=True)


class TestWhatAnUploadRecords:
    """The value is stored on the `rag_documents` row rather than passed to the
    flow, for the same reason the resolved ingestion configuration is: the
    worker reads what this upload decided, and a parameter added to the flow
    signature is lost by a run queued before it existed."""

    @staticmethod
    def _dispatching() -> tuple[MagicMock, AsyncMock]:
        created = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        collection = MagicMock(
            collection_name="handbook",
            id=uuid.uuid4(),
            ingestion_config={},
            embedding_model="openai:text-embedding-3-small",
        )
        return collection, created

    async def _dispatch(self, unit: str | None) -> dict[str, object]:
        collection, created = self._dispatching()
        service = RAGDocumentService(MagicMock())
        service.create_document = created  # type: ignore[method-assign]
        service._queue_parse = AsyncMock()  # type: ignore[method-assign]

        with (
            patch("app.services.rag_document.assert_organization_within_budget", new=AsyncMock()),
            patch("app.services.rag_document.IngestionConfigService") as config_service,
            patch(
                "app.services.rag_document.collection_teardown_repo.is_reserved",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.rag_document.get_file_storage",
                return_value=MagicMock(save=AsyncMock(return_value="rag/handbook/a.pdf")),
            ),
        ):
            config_service.return_value.check_embedding_model = MagicMock()
            config_service.return_value.resolved_image_model = AsyncMock(return_value=None)
            await service.dispatch_upload(
                ctx=MagicMock(organization_id=uuid.uuid4(), user_id=uuid.uuid4()),
                collection=collection,
                file_data=b"%PDF-1.4",
                filename="a.pdf",
                replace=False,
                vector_store=MagicMock(create_collection=AsyncMock()),
                organizational_unit=unit,
            )
        return created.await_args.kwargs

    async def test_the_unit_reaches_the_row(self):
        assert (await self._dispatch("Legal"))["organizational_unit"] == "Legal"

    async def test_a_blank_multipart_field_is_recorded_as_none(self):
        """The field is not a schema, so it arrives exactly as the browser sent
        it - and a form that clears the input sends an empty string."""
        assert (await self._dispatch("   "))["organizational_unit"] is None

    async def test_an_upload_that_named_none_records_none(self):
        assert (await self._dispatch(None))["organizational_unit"] is None


class TestWhatTheWorkerStampsOnAnUploadsChunks:
    async def test_it_is_the_unit_the_row_carries(self):
        """Read off the row inside the worker's own session, not handed to the
        flow: a run queued before this existed still binds."""
        record = MagicMock(
            organization_id=uuid.uuid4(),
            ingestion_config={},
            knowledge_base_id=None,
            organizational_unit="Legal",
        )
        documents = MagicMock(
            get_document=AsyncMock(return_value=record), complete_ingestion=AsyncMock()
        )
        ingestion = MagicMock(
            ingest_file=AsyncMock(
                return_value=MagicMock(
                    status=IngestionStatus.DONE,
                    document_id="vector-doc",
                    chunk_count=1,
                    replaced_document_id=None,
                )
            )
        )

        @asynccontextmanager
        async def _worker_db() -> AsyncIterator[MagicMock]:
            yield MagicMock()

        @asynccontextmanager
        async def _pipeline(**_kwargs: object) -> AsyncIterator[MagicMock]:
            yield ingestion

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", _worker_db),
            patch("app.services.rag_document.RAGDocumentService", return_value=documents),
            patch("app.worker.tasks.rag_tasks.assert_organization_within_budget", new=AsyncMock()),
            patch("app.worker.tasks.rag_tasks._ingestion_service", new=_pipeline),
            patch("app.worker.tasks.rag_tasks._record_embedding_spend", new=AsyncMock()),
        ):
            await _run_ingestion(str(uuid.uuid4()), "handbook", "queued/a.pdf", "a.pdf", False, 1)

        assert ingestion.ingest_file.await_args.kwargs["organizational_unit"] == "Legal"


@asynccontextmanager
async def _connector_sync(
    *, organizational_unit: str | None
) -> AsyncIterator[tuple[AsyncMock, MagicMock]]:
    """`_run_source_sync` with its store, connector, database and ingest replaced.

    Narrower than `tests/test_connector_sync_modes.py`'s harness, which compares
    the two flows against a real `IngestionService`: the question here is only
    which value two calls are handed.
    """

    async def download(remote_file: RemoteFile, dest_dir: Path, **_: object) -> Path:
        dest = dest_dir / remote_file.name
        dest.write_bytes(b"the handbook")
        return dest

    connector = MagicMock(
        list_files=AsyncMock(
            return_value=RemoteListing(
                files=[RemoteFile(id="f1", name="handbook.md", source_path="gdrive://f1")]
            )
        ),
        download_file=AsyncMock(side_effect=download),
    )
    store = MagicMock(get_documents=AsyncMock(return_value=[]))
    store.find_existing_document = AsyncMock(return_value=None)
    source = MagicMock(
        connector_type="gdrive",
        config={"folder_id": "1AbC"},
        collection_name="handbook",
        sync_mode="full",
        organization_id=uuid.uuid4(),
        secret_id=None,
        organizational_unit=organizational_unit,
    )
    sources = MagicMock(
        get_source=AsyncMock(return_value=source),
        update_after_sync=AsyncMock(),
    )
    ingest = AsyncMock(
        return_value=MagicMock(
            status=IngestionStatus.DONE,
            document_id="vector-doc",
            chunk_count=1,
            replaced_document_id=None,
            error_message=None,
        )
    )
    documents = MagicMock(
        create_document=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        complete_ingestion=AsyncMock(),
        fail_ingestion=AsyncMock(),
        unlisted_by_source=AsyncMock(return_value=[]),
    )

    @asynccontextmanager
    async def _worker_db() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    with (
        patch.object(rag_tasks, "VectorStore", return_value=store),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_worker_db),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
        patch.object(rag_tasks, "SyncSourceService", return_value=sources),
        patch.object(
            rag_tasks,
            "_knowledge_base_for",
            new=AsyncMock(
                return_value=MagicMock(
                    id=uuid.uuid4(),
                    ingestion_config={},
                    embedding_model="openai:text-embedding-3-small",
                )
            ),
        ),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest),
        patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
        patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
        patch("app.services.rag_document.RAGDocumentService", return_value=documents),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        config_service.return_value.resolved_image_model = AsyncMock(return_value=None)
        yield ingest, documents


class TestWhatASyncStampsOnEveryFileItBringsIn:
    """A shared folder is a department's, and nobody labels a thousand synced
    files one at a time - so the source carries the default and every document
    it brings in inherits it, on the chunks and on the tracked row alike."""

    async def test_the_sources_unit_reaches_the_ingest_and_the_row(self):
        async with _connector_sync(organizational_unit="Legal") as (ingest, documents):
            await rag_tasks._run_source_sync(str(uuid.uuid4()), sync_log_id=str(uuid.uuid4()))

        assert ingest.await_args.kwargs["organizational_unit"] == "Legal"
        assert documents.create_document.await_args.kwargs["organizational_unit"] == "Legal"

    async def test_a_source_with_no_unit_leaves_the_dimension_absent(self):
        """Which is what every chunk in every deployment carried before this,
        and what a document ingested before it still carries."""
        async with _connector_sync(organizational_unit=None) as (ingest, documents):
            await rag_tasks._run_source_sync(str(uuid.uuid4()), sync_log_id=str(uuid.uuid4()))

        assert ingest.await_args.kwargs["organizational_unit"] is None
        assert documents.create_document.await_args.kwargs["organizational_unit"] is None
