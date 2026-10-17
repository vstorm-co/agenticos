"""What a knowledge base has a parse of, as the virtual terminal mounts it (#2191).

`/knowledge/<base>/` lists one file per document whose chunks are stored, so a
document still parsing, one that failed and another base's document are all
absent from it.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.repositories import rag_document_repo

pytestmark = pytest.mark.anyio


async def _kb(db, collection: str) -> uuid.UUID:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=collection,
        scope=KBScope.PERSONAL.value,
        collection_name=collection,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        visibility="private",
    )
    db.add(kb)
    await db.flush()
    return kb.id


async def _doc(
    db,
    *,
    kb_id: uuid.UUID,
    collection: str,
    filename: str,
    status: DocumentStatus = DocumentStatus.DONE,
    vector_document_id: str | None = "vec",
) -> uuid.UUID:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=collection,
        filename=filename,
        filesize=4,
        filetype="md",
        storage_path="",
        status=status,
        chunk_count=1,
        ingestion_config={},
        knowledge_base_id=kb_id,
        vector_document_id=vector_document_id,
    )
    db.add(doc)
    await db.flush()
    return doc.id


async def test_only_this_bases_indexed_documents_are_listed(db) -> None:
    handbook = await _kb(db, "kbmiragehandbook")
    other = await _kb(db, "kbmirageother")
    first = await _doc(db, kb_id=handbook, collection="kbmiragehandbook", filename="a.md")
    second = await _doc(db, kb_id=handbook, collection="kbmiragehandbook", filename="b.md")
    await _doc(
        db,
        kb_id=handbook,
        collection="kbmiragehandbook",
        filename="parsing.md",
        status=DocumentStatus.PROCESSING,
    )
    await _doc(
        db,
        kb_id=handbook,
        collection="kbmiragehandbook",
        filename="no-vectors.md",
        vector_document_id=None,
    )
    await _doc(db, kb_id=other, collection="kbmirageother", filename="theirs.md")

    rows = await rag_document_repo.get_indexed_for_kb(db, handbook)

    assert {row.id for row in rows} == {first, second}
