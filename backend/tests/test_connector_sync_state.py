"""What a connector sync remembers, what it removes, and what it says when it stops (#987).

Three behaviours `_run_source_sync` gained for connectors that can answer them:

- **An unchanged source stops early.** A connector's `remote_version`, stored
  after a clean run with a fingerprint of the configuration, lets the next run
  that finds the same pair skip listing entirely - for a repository, one
  `ls-remote` instead of a clone.
- **A file the source no longer lists is removed**, vectors then row, but only
  after a listing that completed and only under the connector's `listing_root`.
- **A sync that stopped says why.** It used to record "1 files failed" about a
  run that never reached a file.

The connector here is a real `BaseSyncConnector` subclass, so the hooks it does
not override are the base's own answers rather than a mock's.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import StorableSecret
from app.db.models.rag_document import DocumentStatus
from app.services.rag.connectors import BaseSyncConnector, ConnectorConfig, RemoteFile
from app.services.rag.models import IngestionStatus
from app.services.sync_source import SyncState, sync_fingerprint
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio

CONFIG = {"repository_url": "https://git.test/acme/handbook.git"}
ROOT = "fake://handbook@main/"
KB_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()


class _Connector(BaseSyncConnector):
    """A source whose version, listing and failures a test decides."""

    CONNECTOR_TYPE = "fake"

    def __init__(
        self,
        *,
        files: list[str],
        version: str | None = "sha-2",
        root: str | None = ROOT,
        listing_error: Exception | None = None,
    ) -> None:
        self.files = files
        self.version = version
        self.root = root
        self.listing_error = listing_error
        self.listed = 0
        self.closed = 0

    async def remote_version(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> str | None:
        return self.version

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        self.listed += 1
        if self.listing_error is not None:
            raise self.listing_error
        return [RemoteFile(id=name, name=name, source_path=f"{ROOT}{name}") for name in self.files]

    def listing_root(self, config: ConnectorConfig) -> str | None:
        return self.root

    async def aclose(self) -> None:
        self.closed += 1

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        dest_path.write_text(f"contents of {file.id}")


def _row(
    name: str, *, vector_id: str | None = "vec", status: str = DocumentStatus.DONE
) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        source_path=f"{ROOT}{name}",
        vector_document_id=f"{vector_id}-{name}" if vector_id else None,
        status=status,
    )


@dataclass
class _Run:
    answer: dict[str, Any]
    connector: _Connector
    ingest: AsyncMock
    complete: AsyncMock
    after: AsyncMock
    removed_vectors: list[str] = field(default_factory=list)
    deleted_rows: list[uuid.UUID] = field(default_factory=list)
    listed_rows_scope: dict[str, Any] | None = None

    @property
    def stored_state(self) -> dict[str, str] | None:
        state = self.after.await_args.kwargs["sync_state"]
        return None if state is None else state.model_dump()


def _state(
    version: str, *, mode: str = "new_only", config: dict[str, object] = CONFIG
) -> dict[str, str]:
    return SyncState(
        version=version,
        fingerprint=sync_fingerprint(config, collection_name="docs", sync_mode=mode),
    ).model_dump()


async def _sync(
    connector: _Connector,
    *,
    mode: str = "new_only",
    stored_state: dict[str, str] | None = None,
    rows: list[MagicMock] | None = None,
    vector_delete_fails: set[str] | None = None,
    ingest_status: IngestionStatus = IngestionStatus.DONE,
) -> _Run:
    source = MagicMock(
        connector_type="fake",
        config=dict(CONFIG),
        collection_name="docs",
        sync_mode=mode,
        organization_id=ORG_ID,
        secret_id=None,
        organizational_unit=None,
        sync_state=stored_state,
    )
    after = AsyncMock()
    sources = MagicMock(get_source=AsyncMock(return_value=source), update_after_sync=after)
    complete = AsyncMock(return_value=None)
    store = MagicMock(find_existing_document=AsyncMock(return_value=None))
    ingest = AsyncMock(
        return_value=MagicMock(
            status=ingest_status,
            document_id="vector-doc",
            chunk_count=1,
            replaced_document_id=None,
            error_message=None if ingest_status is IngestionStatus.DONE else "parse failed",
        )
    )
    run = _Run(answer={}, connector=connector, ingest=ingest, complete=complete, after=after)
    failing = vector_delete_fails or set()

    async def remove_document(_self: Any, _collection: str, document_id: str, *_: Any) -> bool:
        if document_id in failing:
            return False
        run.removed_vectors.append(document_id)
        return True

    async def delete_row(_db: Any, row_id: uuid.UUID) -> bool:
        run.deleted_rows.append(row_id)
        return True

    @asynccontextmanager
    async def _db() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    with (
        patch.object(rag_tasks, "VectorStore", return_value=store),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_db),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
        patch.object(rag_tasks, "SyncSourceService", return_value=sources),
        patch.object(
            rag_tasks,
            "_knowledge_base_for",
            new=AsyncMock(
                return_value=MagicMock(
                    id=KB_ID, ingestion_config={}, embedding_model="openai:text-embedding-3-small"
                )
            ),
        ),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest),
        patch.object(rag_tasks.IngestionService, "remove_document", new=remove_document),
        patch.object(
            rag_tasks.rag_document_repo,
            "list_settled_under",
            new=AsyncMock(return_value=rows or []),
        ) as listed_rows,
        patch.object(rag_tasks.rag_document_repo, "delete", new=delete_row),
        patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"fake": lambda: connector}),
        patch(
            "app.services.rag_sync.RAGSyncService", return_value=MagicMock(complete_sync=complete)
        ),
        patch(
            "app.services.rag_document.RAGDocumentService",
            return_value=MagicMock(
                create_document=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
                complete_ingestion=AsyncMock(),
                fail_ingestion=AsyncMock(),
            ),
        ),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        config_service.return_value.resolved_image_model = AsyncMock(return_value=None)
        run.answer = await rag_tasks._run_source_sync(
            str(uuid.uuid4()), sync_log_id=str(uuid.uuid4())
        )
        run.listed_rows_scope = listed_rows.await_args.kwargs if listed_rows.await_args else None
    return run


class TestAnUnchangedSourceStopsEarly:
    async def test_the_same_version_under_the_same_configuration_lists_nothing(self) -> None:
        connector = _Connector(files=["a.md"], version="sha-1")

        run = await _sync(connector, stored_state=_state("sha-1"))

        assert connector.listed == 0
        run.ingest.assert_not_awaited()
        assert run.answer["status"] == "done"

    async def test_a_new_version_lists_and_records_itself(self) -> None:
        connector = _Connector(files=["a.md"], version="sha-2")

        run = await _sync(connector, stored_state=_state("sha-1"))

        assert connector.listed == 1
        assert run.answer["ingested"] == 1
        assert run.stored_state == _state("sha-2")

    async def test_the_same_version_under_another_configuration_lists_again(self) -> None:
        """A changed include pattern reads different files from the same commit."""
        connector = _Connector(files=["a.md"], version="sha-1")
        other = {**CONFIG, "include": ["**/*.rst"]}

        await _sync(connector, stored_state=_state("sha-1", config=other))

        assert connector.listed == 1

    async def test_full_mode_never_stops_early(self) -> None:
        connector = _Connector(files=["a.md"], version="sha-1")

        await _sync(connector, mode="full", stored_state=_state("sha-1", mode="full"))

        assert connector.listed == 1

    async def test_a_run_with_a_failed_file_records_no_state(self) -> None:
        """Otherwise the next run would stop early and never retry that file."""
        connector = _Connector(files=["a.md"], version="sha-2")

        run = await _sync(
            connector, stored_state=_state("sha-1"), ingest_status=IngestionStatus.ERROR
        )

        assert run.answer["status"] == "error"
        assert run.stored_state is None

    async def test_a_connector_with_no_version_always_lists_and_stores_nothing(self) -> None:
        connector = _Connector(files=["a.md"], version=None)

        run = await _sync(connector)

        assert connector.listed == 1
        assert run.stored_state is None


class TestAFileTheSourceNoLongerListsIsRemoved:
    async def test_an_unlisted_document_loses_its_vectors_and_its_row(self) -> None:
        kept, gone = _row("kept.md"), _row("gone.md")
        connector = _Connector(files=["kept.md"])

        run = await _sync(connector, rows=[kept, gone])

        assert run.removed_vectors == ["vec-gone.md"]
        assert run.deleted_rows == [gone.id]
        assert run.answer["removed"] == 1
        assert run.complete.await_args.kwargs["removed"] == 1

    async def test_the_rows_read_are_this_sources_own(self) -> None:
        run = await _sync(_Connector(files=[]), rows=[])

        assert run.listed_rows_scope == {
            "collection_name": "docs",
            "knowledge_base_id": KB_ID,
            "organization_id": ORG_ID,
            "source_root": ROOT,
        }

    async def test_a_row_whose_vectors_would_not_delete_is_kept_for_the_next_run(self) -> None:
        gone = _row("gone.md")

        run = await _sync(_Connector(files=[]), rows=[gone], vector_delete_fails={"vec-gone.md"})

        assert run.deleted_rows == []
        assert run.answer["removed"] == 0

    async def test_a_failed_attempt_with_no_vectors_is_removed_as_a_row(self) -> None:
        failed = _row("broken.md", vector_id=None, status=DocumentStatus.ERROR)

        run = await _sync(_Connector(files=[]), rows=[failed])

        assert run.removed_vectors == []
        assert run.deleted_rows == [failed.id]

    async def test_a_listing_that_raised_removes_nothing(self) -> None:
        """A network blip is not evidence the repository was emptied."""
        connector = _Connector(files=[], listing_error=RuntimeError("connection reset"))

        run = await _sync(connector, rows=[_row("a.md")])

        assert run.deleted_rows == []
        assert run.answer["removed"] == 0

    async def test_an_unchanged_source_removes_nothing(self) -> None:
        connector = _Connector(files=[], version="sha-1")

        run = await _sync(connector, stored_state=_state("sha-1"), rows=[_row("a.md")])

        assert run.deleted_rows == []

    async def test_a_connector_with_no_root_never_deletes(self) -> None:
        """Drive and S3 answer no root, and keep every document they ever ingested."""
        run = await _sync(_Connector(files=[], root=None), rows=[_row("a.md")])

        assert run.deleted_rows == []


class TestASyncThatStoppedSaysWhy:
    async def test_our_refusal_reaches_the_log_and_the_source_whole(self) -> None:
        refusal = BadRequestError(message="The repository refused the source's token.")
        connector = _Connector(files=[], listing_error=refusal)

        run = await _sync(connector)

        assert run.answer["status"] == "error"
        assert run.complete.await_args.kwargs["error_message"] == refusal.message
        assert run.after.await_args.kwargs["error"] == refusal.message

    async def test_a_foreign_error_is_stored_as_its_class_and_never_its_text(self) -> None:
        connector = _Connector(
            files=[], listing_error=RuntimeError("https://user:pw@internal/x failed")
        )

        run = await _sync(connector)

        stored = run.complete.await_args.kwargs["error_message"]
        assert "RuntimeError" in stored
        assert "internal" not in stored

    async def test_a_partial_failure_still_counts_its_files(self) -> None:
        run = await _sync(_Connector(files=["a.md", "b.md"]), ingest_status=IngestionStatus.ERROR)

        assert run.complete.await_args.kwargs["error_message"] == "2 files failed"

    async def test_the_connector_is_closed_whichever_way_the_sync_went(self) -> None:
        ok = _Connector(files=["a.md"])
        broken = _Connector(files=[], listing_error=RuntimeError("boom"))

        await _sync(ok)
        await _sync(broken)

        assert (ok.closed, broken.closed) == (1, 1)
