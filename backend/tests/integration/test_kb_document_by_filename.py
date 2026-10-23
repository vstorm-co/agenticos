"""A citation names a file; the knowledge base finds the document it came from.

An agent's search result and the console's search page both say
`refunds-and-credits.md`, not a row id, so opening the original asks the base
for its documents with exactly that name.
"""

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


async def _doc(db, *, kb_id: uuid.UUID, collection: str, filename: str) -> uuid.UUID:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=collection,
        filename=filename,
        filesize=4,
        filetype="md",
        storage_path="",
        status=DocumentStatus.DONE,
        chunk_count=1,
        ingestion_config={},
        knowledge_base_id=kb_id,
    )
    db.add(doc)
    await db.flush()
    return doc.id


async def test_a_name_finds_that_document_in_that_base_only(db) -> None:
    handbook = await _kb(db, "kbhandbook")
    policies = await _kb(db, "kbpolicies")
    wanted = await _doc(db, kb_id=handbook, collection="kbhandbook", filename="refunds.md")
    await _doc(db, kb_id=handbook, collection="kbhandbook", filename="refunds-old.md")
    # The same name in another base is that base's document, not this one's.
    await _doc(db, kb_id=policies, collection="kbpolicies", filename="refunds.md")

    rows, total = await rag_document_repo.get_for_kb(db, handbook, filename="refunds.md")

    assert total == 1
    assert [row.id for row in rows] == [wanted]


async def test_without_a_name_the_whole_base_is_listed(db) -> None:
    handbook = await _kb(db, "kbhandbook2")
    await _doc(db, kb_id=handbook, collection="kbhandbook2", filename="a.md")
    await _doc(db, kb_id=handbook, collection="kbhandbook2", filename="b.md")

    _, total = await rag_document_repo.get_for_kb(db, handbook)

    assert total == 2
