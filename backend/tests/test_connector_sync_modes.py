"""What `sync_mode` means when the files come from a connector.

#990. It meant nothing. `_run_source_sync` listed, downloaded and ingested every
file a connector answered with, and the mode reached exactly one argument -
`ingest_file`'s `replace` - while `ingest_file` itself never skips anything. So
on the default `new_only` the previous document was neither found nor deleted and
a *second copy* was inserted on every run: a nightly sync of a folder was a
seventh copy of every chunk by the end of the week, all of them ranked against
each other in every search, each one paid for in embeddings.

`sync_local_flow` in the same module had implemented the modes properly the whole
time. These are therefore written as *comparisons between the two flows* wherever
they can be: one `sync_mode` column feeds both, so a mode that means one thing
for a directory on the server and another for a Drive folder is the defect
whatever either one does in isolation.

`existing_document` is left real, because it is the thing being relied on - it
reads the collection's own listing and answers a precedence (#548). What the
tests control is the listing.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.connectors import RemoteFile
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio

BODY = b"the handbook, unchanged since last night"
BODY_HASH = hashlib.sha256(BODY).hexdigest()
SOURCE_PATH = "gdrive://file-1"


def _stored(*, content_hash: str, source_path: str = SOURCE_PATH) -> MagicMock:
    """One row of a collection's document listing, as the store answers it."""
    return MagicMock(
        id="vector-doc-1",
        filename="handbook.md",
        additional_info={"source_path": source_path, "content_hash": content_hash},
    )


def _connector(*, written: bytes = BODY) -> MagicMock:
    """A connector answering one file, whose download writes real bytes.

    Real bytes because the flow hashes what landed on disk - a stand-in that
    wrote nothing would make the comparison this is about vacuous.
    """

    async def download(remote_file: RemoteFile, dest_dir: Path, **_: Any) -> Path:
        dest = dest_dir / remote_file.name
        dest.write_bytes(written)
        return dest

    return MagicMock(
        list_files=AsyncMock(
            return_value=[
                RemoteFile(id="file-1", name="handbook.md", source_path=SOURCE_PATH),
            ]
        ),
        download_file=AsyncMock(side_effect=download),
    )


@asynccontextmanager
async def _syncing(*, mode: str, listing: list[MagicMock], connector: MagicMock) -> Any:
    """The connector flow with its store, database and ingest replaced.

    `IngestionService` stays real: `existing_document` is what decides whether a
    file is skipped, so a stand-in service would be a test of the stand-in.
    """
    store = MagicMock()
    store.aclose = AsyncMock()
    store.get_documents = AsyncMock(return_value=listing)

    source = MagicMock(
        connector_type="gdrive",
        config={"folder_id": "abc"},
        collection_name="docs",
        sync_mode=mode,
        organization_id=uuid.uuid4(),
        secret_id=None,
    )
    sources = MagicMock(
        get_source=AsyncMock(return_value=source),
        update_after_sync=AsyncMock(),
        trigger_sync=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
    )
    ingest = AsyncMock()

    @asynccontextmanager
    async def _db() -> Any:
        yield MagicMock()

    with (
        patch.object(rag_tasks, "VectorStore", return_value=store),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_db),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
        patch.object(rag_tasks, "SyncSourceService", return_value=sources),
        patch.object(rag_tasks, "_config_for_collection", new=AsyncMock()),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest),
        patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
        patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        yield ingest


async def _sync(*, mode: str, listing: list[MagicMock], connector: MagicMock) -> Any:
    async with _syncing(mode=mode, listing=listing, connector=connector) as ingest:
        answer = await rag_tasks._run_source_sync(str(uuid.uuid4()), sync_log_id=str(uuid.uuid4()))
    return answer, ingest


class TestAnIngestAlwaysReplaces:
    """The half of #990 that produced the duplicates.

    `replace=(sync_mode == "full")` meant the two commonest modes told
    `ingest_file` not to look for what it was about to insert beside.
    """

    @pytest.mark.parametrize("mode", ["full", "new_only", "update_only"])
    async def test_whatever_the_mode_a_file_that_is_ingested_replaces_its_document(self, mode: str):
        # A listing whose hash differs, so every mode reaches the ingest: what is
        # under test is the argument it is reached with, not whether it is.
        answer, ingest = await _sync(
            mode=mode,
            listing=[_stored(content_hash="a-different-file-entirely")],
            connector=_connector(),
        )

        assert answer["ingested"] == 1
        assert ingest.await_args.kwargs["replace"] is True


class TestAnUnchangedFile:
    async def test_it_is_skipped_rather_than_embedded_again(self):
        """The cost this exists to avoid. Before the fix a nightly sync
        re-embedded every unchanged file and inserted a second copy of it."""
        answer, ingest = await _sync(
            mode="new_only",
            listing=[_stored(content_hash=BODY_HASH)],
            connector=_connector(),
        )

        ingest.assert_not_awaited()
        assert answer["skipped"] == 1
        assert answer["ingested"] == 0

    async def test_update_only_skips_it_too(self):
        answer, ingest = await _sync(
            mode="update_only",
            listing=[_stored(content_hash=BODY_HASH)],
            connector=_connector(),
        )

        ingest.assert_not_awaited()
        assert answer["skipped"] == 1

    async def test_full_re_ingests_it_because_that_is_what_full_means(self):
        answer, ingest = await _sync(
            mode="full",
            listing=[_stored(content_hash=BODY_HASH)],
            connector=_connector(),
        )

        ingest.assert_awaited_once()
        assert answer["ingested"] == 1
        assert answer["skipped"] == 0


class TestAChangedFile:
    async def test_new_only_re_ingests_it(self):
        """Which is what `sync_local_flow` does with the same mode - the name
        says otherwise, and the two flows agreeing matters more than the name,
        because one column feeds both."""
        answer, ingest = await _sync(
            mode="new_only",
            listing=[_stored(content_hash="what-it-was-yesterday")],
            connector=_connector(),
        )

        ingest.assert_awaited_once()
        assert answer["ingested"] == 1
        assert answer["skipped"] == 0


class TestAFileNeverSeenBefore:
    async def test_new_only_ingests_it(self):
        answer, ingest = await _sync(mode="new_only", listing=[], connector=_connector())

        assert answer["ingested"] == 1
        assert ingest.await_args.kwargs["source_path"] == SOURCE_PATH

    async def test_update_only_skips_it_without_paying_for_the_download(self):
        """`update_only` means "do not add anything", so the answer is known
        before the bytes are fetched - and fetching them anyway is a transfer per
        new file in the folder, on every run."""
        connector = _connector()

        answer, ingest = await _sync(mode="update_only", listing=[], connector=connector)

        connector.download_file.assert_not_awaited()
        ingest.assert_not_awaited()
        assert answer["skipped"] == 1


class TestAStoredDocumentWithNoHash:
    async def test_it_is_re_ingested_rather_than_assumed_current(self):
        """A document ingested before the hash was recorded, or by a path that
        did not record one. Skipping it would be a decision nothing later
        corrects; re-embedding it costs once."""
        answer, ingest = await _sync(
            mode="new_only",
            listing=[_stored(content_hash="")],
            connector=_connector(),
        )

        assert answer["ingested"] == 1
        assert ingest.await_args.kwargs["replace"] is True


class TestAListingTheStoreCannotAnswer:
    async def test_a_failed_lookup_ingests_rather_than_skips(self):
        """`existing_document` answers "no match" when the store refuses, and
        that has to mean *ingest*: a failed query is not evidence a document is
        unchanged, and the sync that believed it would leave the collection
        stale with nothing said."""
        store_error = MagicMock()
        store_error.aclose = AsyncMock()
        store_error.get_documents = AsyncMock(side_effect=RuntimeError("no such table"))

        connector = _connector()
        source = MagicMock(
            connector_type="gdrive",
            config={"folder_id": "abc"},
            collection_name="docs",
            sync_mode="new_only",
            organization_id=uuid.uuid4(),
            secret_id=None,
        )
        sources = MagicMock(
            get_source=AsyncMock(return_value=source),
            update_after_sync=AsyncMock(),
            trigger_sync=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        )
        ingest = AsyncMock()

        @asynccontextmanager
        async def _db() -> Any:
            yield MagicMock()

        with (
            patch.object(rag_tasks, "VectorStore", return_value=store_error),
            patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
            patch.object(rag_tasks, "get_worker_db_context", new=_db),
            patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
            patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
            patch.object(rag_tasks, "SyncSourceService", return_value=sources),
            patch.object(rag_tasks, "_config_for_collection", new=AsyncMock()),
            patch.object(rag_tasks, "IngestionConfigService") as config_service,
            patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest),
            patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
            patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
        ):
            config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
            answer = await rag_tasks._run_source_sync(
                str(uuid.uuid4()), sync_log_id=str(uuid.uuid4())
            )

        assert answer["ingested"] == 1
        assert answer["skipped"] == 0
