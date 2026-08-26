"""Paging a RAG listing over tied `created_at` neither repeats nor skips a row.

A bulk import lands many `rag_documents` in one microsecond, so `created_at DESC`
alone is not a total order and the page boundaries an `offset`/`limit` client
reads them in are undefined - a row can come back twice or be skipped (#1103).
The unique `id` tiebreaker makes the order total, which is a promise only the
database can be tested to keep.

Both tests assert the exact `id DESC` order the tiebreaker produces over tied
timestamps rather than only set membership: six random ids sorted by `id DESC` is
a specific sequence that the undefined heap order without a tiebreaker does not
reproduce, so each test fails if the tiebreaker is dropped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.repositories import rag_document_repo

pytestmark = pytest.mark.anyio

_TIED = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
_COLLECTION = "kbtiebreak"


async def _kb(db) -> uuid.UUID:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name="Docs",
        scope=KBScope.PERSONAL.value,
        collection_name=_COLLECTION,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        visibility="private",
    )
    db.add(kb)
    await db.flush()
    return kb.id


async def _tied_docs(db, *, kb_id: uuid.UUID, n: int) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for _ in range(n):
        doc_id = uuid.uuid4()
        ids.append(doc_id)
        db.add(
            RAGDocument(
                id=doc_id,
                collection_name=_COLLECTION,
                filename=f"{doc_id.hex}.md",
                filesize=4,
                filetype="md",
                storage_path="",
                status=DocumentStatus.PROCESSING,
                chunk_count=0,
                ingestion_config={},
                knowledge_base_id=kb_id,
                created_at=_TIED,
            )
        )
    await db.flush()
    return ids


async def test_paging_get_for_kb_over_tied_timestamps_is_stable(db) -> None:
    kb_id = await _kb(db)
    ids = await _tied_docs(db, kb_id=kb_id, n=6)

    seen: list[uuid.UUID] = []
    for skip in (0, 2, 4):
        rows, total = await rag_document_repo.get_for_kb(db, kb_id, skip=skip, limit=2)
        assert total == 6
        seen.extend(row.id for row in rows)

    assert seen == sorted(ids, reverse=True)  # no repeat, no skip, and a total order


async def test_get_all_over_tied_timestamps_is_a_total_order(db) -> None:
    ids = await _tied_docs(db, kb_id=await _kb(db), n=6)

    rows, total = await rag_document_repo.get_all(db, collections=[_COLLECTION])

    assert total == len(ids)
    assert [row.id for row in rows] == sorted(ids, reverse=True)
