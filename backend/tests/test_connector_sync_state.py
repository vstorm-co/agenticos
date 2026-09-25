"""What a connector sync remembers, and what it puts right before it reads (#987).

Two behaviours `_sync_source` has on top of the listing and removal
`tests/test_sync_removal.py` covers:

- **An unchanged source stops early.** A connector's `remote_version`, stored
  after a clean run with a fingerprint of the configuration, lets the next run
  that finds the same pair skip listing entirely - for a repository, one
  `ls-remote` instead of a clone.
- **What a dead run left half-ingested is settled first.** A worker killed
  between storing a file's vectors and recording their id leaves a `PROCESSING`
  row and vectors nothing tracks; the next run clears them and ingests the file
  again, rather than skipping it as unchanged and leaving vectors a removal can
  never find.

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

from app.core.secret_kinds import StorableSecret
from app.db.models.rag_document import DocumentStatus
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConnectorConfig,
    RemoteFile,
    RemoteListing,
)
from app.services.rag.models import IngestionStatus
from app.services.sync_source import SyncState, sync_fingerprint
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio

CONFIG = {"repository_url": "https://git.test/acme/handbook.git"}
ROOT = "fake://handbook@main/"
KB_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()


class _Connector(BaseSyncConnector):
    """A source whose version, listing and failures a test decides."""

    CONNECTOR_TYPE = "fake"

    def __init__(
        self,
        *,
        files: list[str],
        version: str | None = "sha-2",
        listing_error: Exception | None = None,
    ) -> None:
        self.files = files
        self.version = version
        self.listing_error = listing_error
        self.listed = 0
        self.closed = 0

    async def remote_version(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> str | None:
        return self.version

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> RemoteListing:
        self.listed += 1
        if self.listing_error is not None:
            raise self.listing_error
        return RemoteListing(
            files=[
                RemoteFile(id=name, name=name, source_path=f"{ROOT}{name}") for name in self.files
            ]
        )

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


OPENED_ID = uuid.uuid4()


def _row(
    name: str, *, vector_id: str | None = None, status: str = DocumentStatus.PROCESSING
) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(), source_path=f"{ROOT}{name}", vector_document_id=vector_id, status=status
    )


@dataclass
class _Store:
    """What the vector store holds, by address, and which deletes it refuses."""

    at: dict[str, list[str]] = field(default_factory=dict)
    refuses: set[str] = field(default_factory=set)
    lookup_error: Exception | None = None
    removed: list[str] = field(default_factory=list)


@dataclass
class _Run:
    answer: dict[str, Any]
    connector: _Connector
    ingest: AsyncMock
    complete: AsyncMock
    after: AsyncMock
    documents: MagicMock
    store: _Store
    forgotten: list[str] = field(default_factory=list)

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
    stale: list[MagicMock] | None = None,
    settled: list[MagicMock] | None = None,
    tracked: set[str] | None = None,
    store: _Store | None = None,
    ingest_status: IngestionStatus = IngestionStatus.DONE,
    claimants: set[uuid.UUID] | None = None,
) -> _Run:
    source = MagicMock(
        id=SOURCE_ID,
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
    vector_store = MagicMock(find_existing_document=AsyncMock(return_value=None))
    ingest = AsyncMock(
        return_value=MagicMock(
            status=ingest_status,
            document_id="vector-doc",
            chunk_count=1,
            replaced_document_id=None,
            error_message=None if ingest_status is IngestionStatus.DONE else "parse failed",
        )
    )
    held = store or _Store()
    run = _Run(
        answer={},
        connector=connector,
        ingest=ingest,
        complete=complete,
        after=after,
        documents=MagicMock(),
        store=held,
    )

    async def forget(row_id: str) -> None:
        run.forgotten.append(row_id)

    async def settled_at(**kwargs: Any) -> list[MagicMock]:
        return [row for row in settled or [] if row.source_path == kwargs["source_path"]]

    run.documents = MagicMock(
        create_document=AsyncMock(return_value=MagicMock(id=OPENED_ID)),
        complete_ingestion=AsyncMock(),
        fail_ingestion=AsyncMock(),
        stale_for_source=AsyncMock(return_value=stale or []),
        settled_at=AsyncMock(side_effect=settled_at),
        tracked_vector_ids=AsyncMock(return_value=tracked or set()),
        unlisted_by_source=AsyncMock(return_value=[]),
        forget_document=AsyncMock(side_effect=forget),
        claimants=AsyncMock(return_value=claimants or set()),
        claim_listed=AsyncMock(),
        add_claims=AsyncMock(),
    )

    async def document_ids_at(_self: Any, _collection: str, source_path: str) -> list[str]:
        if held.lookup_error is not None:
            raise held.lookup_error
        return held.at.get(source_path, [])

    async def remove_document(_self: Any, _collection: str, document_id: str, *_: Any) -> bool:
        if document_id in held.refuses:
            return False
        held.removed.append(document_id)
        return True

    @asynccontextmanager
    async def _db() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    @asynccontextmanager
    async def _lock(_source_id: str) -> AsyncIterator[bool]:
        yield True

    with (
        patch.object(rag_tasks, "VectorStore", return_value=vector_store),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_db),
        patch.object(rag_tasks, "_exclusive_source_run", new=_lock),
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
        patch.object(rag_tasks.IngestionService, "document_ids_at", new=document_ids_at),
        patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"fake": lambda: connector}),
        patch(
            "app.services.rag_sync.RAGSyncService", return_value=MagicMock(complete_sync=complete)
        ),
        patch("app.services.rag_document.RAGDocumentService", return_value=run.documents),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        config_service.return_value.resolved_image_model = AsyncMock(return_value=None)
        run.answer = await rag_tasks._run_source_sync(str(SOURCE_ID), sync_log_id="log-1")
    return run


class TestAnUnchangedSourceStopsEarly:
    async def test_the_same_version_under_the_same_configuration_lists_nothing(self) -> None:
        connector = _Connector(files=["a.md"], version="sha-1")

        run = await _sync(connector, stored_state=_state("sha-1"))

        assert connector.listed == 0
        run.ingest.assert_not_awaited()
        assert run.answer["status"] == "done"

    async def test_an_early_stop_removes_nothing(self) -> None:
        """It listed nothing, which is no evidence anything went upstream."""
        run = await _sync(_Connector(files=[], version="sha-1"), stored_state=_state("sha-1"))

        run.documents.unlisted_by_source.assert_not_awaited()

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

    async def test_the_connector_is_closed_whichever_way_the_sync_went(self) -> None:
        ok = _Connector(files=["a.md"])
        broken = _Connector(files=[], listing_error=RuntimeError("boom"))

        await _sync(ok)
        await _sync(broken)

        assert (ok.closed, broken.closed) == (1, 1)


class TestWhatADeadRunLeftIsSettledFirst:
    async def test_vectors_nothing_tracks_are_cleared_and_the_file_ingested_again(self) -> None:
        """Codex on #1867: the vectors were stored, the row never learned their id.
        Left alone the next run skipped the file by its hash, and removing it later
        had no id to delete by."""
        stale = _row("a.md")
        store = _Store(at={f"{ROOT}a.md": ["orphan"]})

        run = await _sync(_Connector(files=["a.md"]), stale=[stale], store=store)

        assert store.removed == ["orphan"]
        assert run.forgotten == [str(stale.id)]
        assert run.answer["ingested"] == 1
        assert run.stored_state == _state("sha-2")

    async def test_vectors_a_row_tracks_are_kept_and_only_the_stale_row_goes(self) -> None:
        """A run that died before it stored anything left the old document in place."""
        stale = _row("a.md")
        store = _Store(at={f"{ROOT}a.md": ["live"]})

        run = await _sync(_Connector(files=["a.md"]), stale=[stale], store=store, tracked={"live"})

        assert store.removed == []
        assert run.forgotten == [str(stale.id)]

    async def test_a_row_whose_vectors_the_dead_run_replaced_goes_with_it(self) -> None:
        """Died after replacing the old document and before settling: the old row
        names vectors that are gone, and would otherwise count the file twice."""
        stale = _row("a.md")
        replaced = _row("a.md", vector_id="old", status=DocumentStatus.DONE)
        store = _Store(at={f"{ROOT}a.md": ["new"]})

        run = await _sync(
            _Connector(files=["a.md"]), stale=[stale], settled=[replaced], store=store
        )

        assert store.removed == ["new"]
        assert run.forgotten == [str(stale.id), str(replaced.id)]
        run.documents.add_claims.assert_not_awaited()

    async def test_another_sources_claim_on_a_dropped_row_moves_to_the_new_one(self) -> None:
        """The other source lists the address too. Dropped with the dead row, its
        claim would leave the document this run ingests again to this source
        alone, and this source dropping it later would remove it (#1879)."""
        other = uuid.uuid4()
        stale = _row("a.md")
        replaced = _row("a.md", vector_id="old", status=DocumentStatus.DONE)

        run = await _sync(
            _Connector(files=["a.md"]),
            stale=[stale],
            settled=[replaced],
            store=_Store(at={f"{ROOT}a.md": ["new"]}),
            claimants={other, SOURCE_ID},
        )

        run.documents.claimants.assert_awaited_once_with([str(replaced.id)])
        run.documents.add_claims.assert_awaited_once_with(str(OPENED_ID), sync_source_ids={other})

    @pytest.mark.parametrize(
        "store",
        [
            _Store(at={f"{ROOT}a.md": ["orphan"]}, refuses={"orphan"}),
            _Store(lookup_error=RuntimeError("store unavailable")),
        ],
        ids=["a vector delete refused", "the lookup failed"],
    )
    async def test_a_row_that_could_not_be_settled_is_kept_and_fails_the_run(
        self, store: _Store
    ) -> None:
        """Never dropped unread: failed, the run records no state and the next retries."""
        stale = _row("a.md")

        run = await _sync(
            _Connector(files=[], version="sha-1"),
            stale=[stale],
            store=store,
            stored_state=_state("sha-0"),
        )

        assert run.forgotten == []
        assert run.answer["status"] == "error"
        assert run.stored_state is None
        assert "left half-ingested" in run.complete.await_args.kwargs["error_message"]

    async def test_a_stale_row_keeps_an_unchanged_source_from_stopping_early(self) -> None:
        connector = _Connector(files=["a.md"], version="sha-1")

        run = await _sync(connector, stored_state=_state("sha-1"), stale=[_row("a.md")])

        assert connector.listed == 1
        assert run.answer["ingested"] == 1
