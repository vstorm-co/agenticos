"""FAQ Q&A entries → Agentra RAG sync (D3 B57)."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands.rag import get_rag_services
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.shop_faq_entry import ShopFaqEntry
from app.repositories import knowledge_base_repo, rag_document as rag_document_repo
from app.repositories import shop_faq_entry as entry_repo
from app.schemas.shop_faq import (
    ShopFaqEntryCreate,
    ShopFaqEntryList,
    ShopFaqEntryRead,
    ShopFaqEntryUpdate,
)
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionResult, IngestionStatus
from app.services.shop_faq_suggestion_utils import is_faq_kb

logger = logging.getLogger(__name__)

SOURCE_TYPE_FAQ = "faq_entry"


def render_faq_entry_text(*, question: str, answer: str) -> str:
    q = question.strip()
    a = answer.strip()
    return f"Câu hỏi: {q}\nTrả lời: {a}"


def faq_entry_hash(*, question: str, answer: str) -> str:
    payload = f"{question.strip()}\n{answer.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def faq_source_path(entry_id: UUID) -> str:
    return f"faq://{entry_id}"


async def _get_rag_doc_for_entry(
    db: AsyncSession,
    *,
    kb_id: UUID,
    entry_id: UUID,
) -> RAGDocument | None:
    path = faq_source_path(entry_id)
    result = await db.execute(
        select(RAGDocument).where(
            RAGDocument.knowledge_base_id == kb_id,
            RAGDocument.source_path == path,
        )
    )
    return result.scalar_one_or_none()


class ShopFaqService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_entries(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
    ) -> ShopFaqEntryList:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        rows = await entry_repo.list_for_kb(
            self.db, kb_id=kb.id, minerp_tenant_id=minerp_tenant_id
        )
        items = [await self._to_read(row, kb) for row in rows]
        return ShopFaqEntryList(items=items, total=len(items))

    async def create_entry(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        data: ShopFaqEntryCreate,
    ) -> ShopFaqEntryRead:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        sort_order = data.sort_order
        if sort_order is None:
            sort_order = await entry_repo.next_sort_order(self.db, kb_id=kb.id)
        entry = await entry_repo.create(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
            knowledge_base_id=kb.id,
            question=data.question.strip(),
            answer=data.answer.strip(),
            sort_order=sort_order,
            is_published=data.is_published,
        )
        if entry.is_published:
            await self._sync_entry_safe(entry, kb)
        return await self._to_read(entry, kb)

    async def update_entry(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        entry_id: UUID,
        data: ShopFaqEntryUpdate,
    ) -> ShopFaqEntryRead:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        entry = await self._get_entry_or_404(
            kb_id=kb.id, minerp_tenant_id=minerp_tenant_id, entry_id=entry_id
        )
        if not any(
            v is not None for v in (data.question, data.answer, data.sort_order, data.is_published)
        ):
            raise BadRequestError(message="No fields to update")
        entry = await entry_repo.update(
            self.db,
            entry,
            question=data.question.strip() if data.question is not None else None,
            answer=data.answer.strip() if data.answer is not None else None,
            sort_order=data.sort_order,
            is_published=data.is_published,
        )
        if entry.is_published:
            await self._sync_entry_safe(entry, kb)
        else:
            await self._remove_entry_from_rag(entry, kb)
        return await self._to_read(entry, kb)

    async def delete_entry(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        entry_id: UUID,
    ) -> None:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        entry = await self._get_entry_or_404(
            kb_id=kb.id, minerp_tenant_id=minerp_tenant_id, entry_id=entry_id
        )
        await self._remove_entry_from_rag(entry, kb)
        await entry_repo.delete(self.db, entry)

    async def _require_faq_kb(self, *, organization_id: UUID, kb_id: UUID) -> KnowledgeBase:
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if kb is None or kb.organization_id != organization_id:
            raise NotFoundError(
                message="Knowledge base not found",
                details={"knowledge_base_id": str(kb_id)},
            )
        if not is_faq_kb(kb):
            raise BadRequestError(
                message="Knowledge base is not eligible for FAQ entries",
                details={"knowledge_base_id": str(kb_id)},
            )
        return kb

    async def _get_entry_or_404(
        self,
        *,
        kb_id: UUID,
        minerp_tenant_id: UUID,
        entry_id: UUID,
    ) -> ShopFaqEntry:
        entry = await entry_repo.get_by_id(
            self.db,
            entry_id=entry_id,
            kb_id=kb_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        if entry is None:
            raise NotFoundError(message="FAQ entry not found", details={"entry_id": str(entry_id)})
        return entry

    async def _to_read(self, entry: ShopFaqEntry, kb: KnowledgeBase) -> ShopFaqEntryRead:
        rag_doc = await _get_rag_doc_for_entry(self.db, kb_id=kb.id, entry_id=entry.id)
        return ShopFaqEntryRead(
            id=entry.id,
            knowledge_base_id=entry.knowledge_base_id,
            tenant_id=entry.minerp_tenant_id,
            question=entry.question,
            answer=entry.answer,
            sort_order=entry.sort_order,
            is_published=entry.is_published,
            rag_status=rag_doc.status if rag_doc else None,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    async def _sync_entry_safe(self, entry: ShopFaqEntry, kb: KnowledgeBase) -> None:
        try:
            await self._sync_entry(entry, kb)
        except Exception:
            logger.exception("FAQ RAG sync failed for entry %s", entry.id)

    async def _sync_entry(self, entry: ShopFaqEntry, kb: KnowledgeBase) -> None:
        text = render_faq_entry_text(question=entry.question, answer=entry.answer)
        version = faq_entry_hash(question=entry.question, answer=entry.answer)
        source_path = faq_source_path(entry.id)
        existing = await _get_rag_doc_for_entry(self.db, kb_id=kb.id, entry_id=entry.id)

        processor, vector_store, _, _, _ = get_rag_services()
        ingestion = IngestionService(
            processor=processor,
            vector_store=vector_store,
            tenant=kb.vector_tenant,
        )

        if existing and existing.vector_document_id:
            await ingestion.remove_document(kb.collection_name, existing.vector_document_id)

        filename = f"faq-{entry.id}.txt"
        if existing is None:
            doc = await rag_document_repo.create(
                self.db,
                collection_name=kb.collection_name,
                filename=filename,
                filesize=len(text.encode("utf-8")),
                filetype="faq",
                storage_path="",
                source_path=source_path,
                status=DocumentStatus.PROCESSING,
                organization_id=entry.organization_id,
                knowledge_base_id=kb.id,
            )
        else:
            doc = existing
            doc.filesize = len(text.encode("utf-8"))
            doc.status = DocumentStatus.PROCESSING
            doc.error_message = None
            await self.db.flush()

        result = await self._ingest_text(
            ingestion,
            text=text,
            collection_name=kb.collection_name,
            source_path=source_path,
            filename=filename,
        )
        if result.status == IngestionStatus.ERROR:
            await rag_document_repo.update_status(
                self.db,
                doc.id,
                status=DocumentStatus.ERROR,
                error_message=result.error_message or result.message,
            )
            return

        await rag_document_repo.update_status(
            self.db,
            doc.id,
            status=DocumentStatus.DONE,
            vector_document_id=result.document_id,
            chunk_count=result.chunk_count or 0,
            completed_at=datetime.now(UTC),
            error_message=None,
        )

    async def _remove_entry_from_rag(self, entry: ShopFaqEntry, kb: KnowledgeBase) -> None:
        existing = await _get_rag_doc_for_entry(self.db, kb_id=kb.id, entry_id=entry.id)
        if existing is None:
            return
        processor, vector_store, _, _, _ = get_rag_services()
        ingestion = IngestionService(
            processor=processor,
            vector_store=vector_store,
            tenant=kb.vector_tenant,
        )
        if existing.vector_document_id:
            await ingestion.remove_document(kb.collection_name, existing.vector_document_id)
        await rag_document_repo.delete(self.db, existing.id)

    async def _ingest_text(
        self,
        ingestion: IngestionService,
        *,
        text: str,
        collection_name: str,
        source_path: str,
        filename: str,
    ) -> IngestionResult:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        try:
            return await ingestion.ingest_file(
                tmp_path,
                collection_name,
                replace=True,
                source_path=source_path,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
