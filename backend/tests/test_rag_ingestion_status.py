"""Whether a collection, or a knowledge base, is still indexing.

`GET /rag/collections/{name}/info` answered the constant `complete` while the
worker was still ingesting 231 uploads and `total_vectors` climbed from 111 to
1852 under it, so a script that waited for `complete` queried a half-built
collection (#2486). The status now comes from the tracked documents. These pin
each state, and that a failed document is visible without holding it at
`indexing`. The SQL runs against Postgres in
`tests/integration/test_platform_flows.py::TestWhatACollectionReportsItHolds`.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.repositories import rag_document_repo
from app.repositories.rag_document import IngestionCounts
from app.services.rag.models import CollectionInfo
from app.services.rag_document import RAGDocumentService

pytestmark = pytest.mark.anyio


def _counts(
    monkeypatch: pytest.MonkeyPatch, name: str, *, processing: int, indexed: int, failed: int
) -> AsyncMock:
    counts = AsyncMock(
        return_value=IngestionCounts(processing=processing, indexed=indexed, failed=failed)
    )
    monkeypatch.setattr(rag_document_repo, name, counts)
    return counts


@pytest.mark.parametrize(
    ("processing", "indexed", "failed", "status"),
    [
        # The reported case: vectors present, most of the upload still queued.
        (220, 11, 0, "indexing"),
        (0, 231, 0, "complete"),
        # A failure is terminal: waiting on it would wait forever, so it is counted.
        (0, 229, 2, "complete"),
        (1, 0, 3, "indexing"),
        # Nothing uploaded is nothing to wait for.
        (0, 0, 0, "complete"),
    ],
)
class TestIndexingStatus:
    async def test_a_collection_is_indexing_while_any_document_is_processing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_db_session: MagicMock,
        processing: int,
        indexed: int,
        failed: int,
        status: str,
    ) -> None:
        _counts(
            monkeypatch, "ingestion_counts", processing=processing, indexed=indexed, failed=failed
        )

        info = await RAGDocumentService(mock_db_session).collection_info(
            CollectionInfo(name="handbook", total_vectors=111, dim=1536),
            kb=KnowledgeBase(
                id=uuid.uuid4(),
                collection_name="handbook",
                scope=KBScope.ORG.value,
                organization_id=uuid.uuid4(),
            ),
        )

        assert info.model_dump() == {
            "name": "handbook",
            "total_vectors": 111,
            "dim": 1536,
            "indexing_status": status,
            "processing_count": processing,
            "indexed_count": indexed,
            "failed_count": failed,
        }

    async def test_a_knowledge_base_is_indexing_while_any_document_is_processing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_db_session: MagicMock,
        processing: int,
        indexed: int,
        failed: int,
        status: str,
    ) -> None:
        kb_id = uuid.uuid4()
        counts = _counts(
            monkeypatch,
            "ingestion_counts_for_kb",
            processing=processing,
            indexed=indexed,
            failed=failed,
        )

        ingestion = await RAGDocumentService(mock_db_session).ingestion_for_kb(kb_id)

        assert ingestion.model_dump() == {
            "indexing_status": status,
            "processing_count": processing,
            "indexed_count": indexed,
            "failed_count": failed,
        }
        assert counts.await_args.args == (mock_db_session, kb_id)
