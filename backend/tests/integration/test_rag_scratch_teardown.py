"""A processing document's parse copy does not outlive its knowledge base (#2681).

A teardown deletes the document rows while their ingest jobs are still queued. Each
job now finds its row gone, ends without a retry and takes its scratch copy with it;
the hourly sweep removes the copy of a document that is gone and keeps the copy of
one still processing. Run against a real teardown on Postgres.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import settings
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import DocumentStatus
from app.services import rag_scratch
from app.services.knowledge_base import KnowledgeBaseService
from app.worker.attempt import Attempt, running
from app.worker.jobs import IngestDocument
from app.worker.tasks import rag_tasks
from tests.integration.test_deletion_reconciliation import (
    _kb_document,
    _org,
    _org_collection,
    _user,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _processing_document(
    factory: async_sessionmaker, collection: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """A base holding one document whose ingest is still queued."""
    async with factory() as s:
        owner = _user()
        s.add(owner)
        await s.flush()
        org = await _org(s, owner)
        base = _org_collection(org.id, collection)
        s.add(base)
        await s.flush()
        row = _kb_document(collection, base.id, org.id, f"rag/{collection}/notes.txt")
        row.status = DocumentStatus.PROCESSING
        s.add(row)
        await s.commit()
        return base.id, row.id


def _write_copy(document_id: uuid.UUID, *, age: timedelta = timedelta(0)) -> Path:
    path = rag_scratch.scratch_path(document_id, attempt=1, filename="notes.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"what the uploader wrote")
    stamp = (datetime.now(UTC) - age).timestamp()
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    return tmp_path


async def test_the_queued_job_of_a_torn_down_base_removes_the_copy(
    engine: AsyncEngine, media: Path
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    collection = f"scratch{uuid.uuid4().hex[:12]}"
    base_id, document_id = await _processing_document(factory, collection)
    copy = _write_copy(document_id)

    async with factory() as s:
        kb = await s.get(KnowledgeBase, base_id)
        assert kb is not None
        await KnowledgeBaseService(s).delete_for_rag_collection(kb)
        await s.commit()

    job = IngestDocument(
        rag_document_id=document_id,
        collection_name=collection,
        filepath=str(copy),
        source_path="notes.txt",
        replace=False,
        attempt=1,
    )
    with running(Attempt(number=1, of=2)):
        outcome = await rag_tasks.ingest_document(job)

    assert outcome == {"status": "deleted", "filename": "notes.txt"}
    assert not copy.exists()


async def test_the_sweep_removes_a_gone_documents_copy_and_keeps_a_processing_ones(
    engine: AsyncEngine, media: Path
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    _, kept_id = await _processing_document(factory, f"scratch{uuid.uuid4().hex[:12]}")
    kept = _write_copy(kept_id, age=timedelta(hours=3))
    orphan = _write_copy(uuid.uuid4(), age=timedelta(hours=3))

    async with factory() as s:
        swept = await rag_scratch.sweep_stale(s, now=datetime.now(UTC))

    assert swept == rag_scratch.ScratchSweep(removed=1, kept=1)
    assert kept.exists()
    assert not orphan.exists()
