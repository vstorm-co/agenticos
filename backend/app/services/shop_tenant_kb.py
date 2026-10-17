"""Shop org knowledge base admin — list/create/delete with FAQ transfer (D3 B60)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.repositories import (
    collection_teardown_repo,
    knowledge_base_repo,
    rag_document as rag_document_repo,
    shop_ai_settings as shop_ai_settings_repo,
    shop_faq_entry as shop_faq_entry_repo,
    shop_faq_suggestion as shop_faq_suggestion_repo,
)
from app.schemas.knowledge_base import KnowledgeBaseList, KnowledgeBaseRead
from app.schemas.shop_kb_delete import ShopKbDeleteResult
from app.schemas.shop_knowledge_base import ShopKnowledgeBaseCreate
from app.services.file_storage import get_file_storage
from app.services.knowledge_base import KnowledgeBaseService, _derive_collection_name, _with_counts
from app.services.rag_document import RAGDocumentService
from app.services.shop_faq_suggestion_utils import is_faq_kb, question_fingerprint
from app.services.shop_faq_sync import ShopFaqService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _TransferStats:
    faq_entries_transferred: int = 0
    faq_entries_skipped_duplicate: int = 0
    suggestions_transferred: int = 0
    suggestions_merged: int = 0
    documents_transferred: int = 0
    documents_skipped: int = 0


class ShopTenantKnowledgeBaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_shop(
        self,
        *,
        organization_id: UUID,
    ) -> KnowledgeBaseList:
        rows = await knowledge_base_repo.list_org_scoped(self.db, organization_id)
        kb_svc = KnowledgeBaseService(self.db)
        counts = await kb_svc.counts_for(rows)
        items = [_with_counts(kb, counts.get(kb.collection_name)) for kb in rows]
        return KnowledgeBaseList(items=items, total=len(items))

    async def create_for_shop(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        data: ShopKnowledgeBaseCreate,
    ) -> KnowledgeBaseRead:
        if data.tenant_id is not None and data.tenant_id != minerp_tenant_id:
            raise BadRequestError(message="tenant_id must match X-Tenant-Id")

        existing = await knowledge_base_repo.list_org_scoped(self.db, organization_id)
        if not existing:
            raise BadRequestError(
                message="Organization has no knowledge base template — provision shop org first",
                details={"organization_id": str(organization_id)},
            )
        ref = next((kb for kb in existing if is_faq_kb(kb)), existing[0])
        collection_name = data.collection_name or _derive_collection_name(data.name)
        if await collection_teardown_repo.is_reserved(self.db, collection_name):
            raise AlreadyExistsError(
                message=f"A collection named '{collection_name}' is being torn down; try again shortly",
                details={"collection": collection_name},
            )

        kb = await knowledge_base_repo.create(
            self.db,
            name=data.name.strip(),
            collection_name=collection_name,
            scope=KBScope.ORG.value,
            description=data.description,
            owner_user_id=ref.owner_user_id,
            organization_id=organization_id,
            ingestion_config=dict(ref.ingestion_config or {}),
            embedding_model=ref.embedding_model,
            embedding_dim=ref.embedding_dim,
            embedding_provider=ref.embedding_provider,
            embedding_secret_id=ref.embedding_secret_id,
            embedding_endpoint_id=ref.embedding_endpoint_id,
        )
        return _with_counts(kb, None)

    async def delete(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        transfer_to: UUID | None = None,
    ) -> ShopKbDeleteResult:
        source_kb = await self._get_deletable_kb(
            organization_id=organization_id,
            kb_id=kb_id,
        )
        faq_kbs = await self._list_faq_kbs(organization_id)
        if len(faq_kbs) <= 1:
            raise BadRequestError(
                message="Cannot delete the only FAQ knowledge base for this shop",
                details={"kb_id": str(kb_id)},
            )
        if transfer_to is None:
            raise BadRequestError(
                message="transfer_to is required — choose a KB to move Q&A and suggestions",
                details={"kb_id": str(kb_id)},
            )
        if transfer_to == kb_id:
            raise BadRequestError(
                message="transfer_to must differ from the knowledge base being deleted",
                details={"kb_id": str(kb_id), "transfer_to": str(transfer_to)},
            )

        target_kb = await self._get_org_kb(organization_id=organization_id, kb_id=transfer_to)
        if target_kb is None or not is_faq_kb(target_kb):
            raise BadRequestError(
                message="transfer_to must be a merchant FAQ knowledge base for this shop",
                details={"transfer_to": str(transfer_to)},
            )

        stats = await self._transfer_content(
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
            source_kb=source_kb,
            target_kb=target_kb,
        )
        await self._repoint_references(
            minerp_tenant_id=minerp_tenant_id,
            organization_id=organization_id,
            from_kb_id=kb_id,
            to_kb_id=transfer_to,
        )
        await knowledge_base_repo.delete(self.db, kb_id)
        return ShopKbDeleteResult(
            faq_entries_transferred=stats.faq_entries_transferred,
            faq_entries_skipped_duplicate=stats.faq_entries_skipped_duplicate,
            suggestions_transferred=stats.suggestions_transferred,
            suggestions_merged=stats.suggestions_merged,
            documents_transferred=stats.documents_transferred,
            documents_skipped=stats.documents_skipped,
        )

    async def _get_org_kb(
        self,
        *,
        organization_id: UUID,
        kb_id: UUID,
    ) -> KnowledgeBase | None:
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if kb is None or kb.organization_id != organization_id:
            return None
        return kb

    async def _get_deletable_kb(
        self,
        *,
        organization_id: UUID,
        kb_id: UUID,
    ) -> KnowledgeBase:
        kb = await self._get_org_kb(organization_id=organization_id, kb_id=kb_id)
        if kb is None:
            raise NotFoundError(
                message="Knowledge base not found",
                details={"kb_id": str(kb_id)},
            )
        if not is_faq_kb(kb):
            raise BadRequestError(
                message="Cannot delete system knowledge base",
                details={"kb_id": str(kb_id), "name": kb.name},
            )
        return kb

    async def _list_faq_kbs(self, organization_id: UUID) -> list[KnowledgeBase]:
        rows = await knowledge_base_repo.list_org_scoped(self.db, organization_id)
        return [row for row in rows if is_faq_kb(row)]

    async def _transfer_content(
        self,
        *,
        minerp_tenant_id: UUID,
        organization_id: UUID,
        source_kb: KnowledgeBase,
        target_kb: KnowledgeBase,
    ) -> _TransferStats:
        stats = _TransferStats()
        faq_svc = ShopFaqService(self.db)

        target_entries = await shop_faq_entry_repo.list_for_kb(
            self.db, kb_id=target_kb.id, minerp_tenant_id=minerp_tenant_id
        )
        target_question_fps = {
            question_fingerprint(entry.question) for entry in target_entries
        }

        source_entries = await shop_faq_entry_repo.list_for_kb(
            self.db, kb_id=source_kb.id, minerp_tenant_id=minerp_tenant_id
        )
        for entry in source_entries:
            fp = question_fingerprint(entry.question)
            if fp in target_question_fps:
                await faq_svc._remove_entry_from_rag(entry, source_kb)
                await shop_faq_entry_repo.delete(self.db, entry)
                stats.faq_entries_skipped_duplicate += 1
                continue

            await faq_svc._remove_entry_from_rag(entry, source_kb)
            entry.knowledge_base_id = target_kb.id
            entry.sort_order = await shop_faq_entry_repo.next_sort_order(
                self.db, kb_id=target_kb.id
            )
            entry.updated_at = datetime.now(UTC)
            await self.db.flush()
            if entry.is_published:
                await faq_svc._sync_entry_safe(entry, target_kb)
            target_question_fps.add(fp)
            stats.faq_entries_transferred += 1

        source_suggestions = await shop_faq_suggestion_repo.list_all_for_kb(
            self.db,
            kb_id=source_kb.id,
            minerp_tenant_id=minerp_tenant_id,
        )
        for suggestion in source_suggestions:
            existing = await shop_faq_suggestion_repo.get_by_fingerprint(
                self.db,
                minerp_tenant_id=minerp_tenant_id,
                kb_id=target_kb.id,
                fingerprint=suggestion.question_fingerprint,
            )
            if existing is None:
                suggestion.knowledge_base_id = target_kb.id
                suggestion.updated_at = datetime.now(UTC)
                stats.suggestions_transferred += 1
                continue

            if existing.status == "pending" and suggestion.status == "pending":
                existing.occurrence_count += suggestion.occurrence_count
                if suggestion.last_seen_at > existing.last_seen_at:
                    existing.last_seen_at = suggestion.last_seen_at
                    existing.question_text = suggestion.question_text
                if not existing.suggested_answer and suggestion.suggested_answer:
                    existing.suggested_answer = suggestion.suggested_answer
                    existing.suggested_answer_at = suggestion.suggested_answer_at
                existing.updated_at = datetime.now(UTC)
            await self.db.delete(suggestion)
            stats.suggestions_merged += 1

        await self._transfer_upload_documents(
            source_kb=source_kb,
            target_kb=target_kb,
            stats=stats,
        )

        await self.db.flush()
        return stats

    @staticmethod
    def _is_transferable_upload(doc: RAGDocument) -> bool:
        if (doc.source_path or "").startswith("faq://"):
            return False
        if doc.filetype in {"faq", "catalog"}:
            return False
        return True

    async def _transfer_upload_documents(
        self,
        *,
        source_kb: KnowledgeBase,
        target_kb: KnowledgeBase,
        stats: _TransferStats,
    ) -> None:
        from app.commands.rag import get_rag_services
        from app.services.rag.ingestion import IngestionService

        processor, vector_store, _, _, _ = get_rag_services()
        ingestion = IngestionService(
            processor=processor,
            vector_store=vector_store,
            tenant=source_kb.vector_tenant,
        )
        storage = get_file_storage()
        rag_svc = RAGDocumentService(self.db)
        docs = await rag_document_repo.list_all_for_kb(self.db, source_kb.id)
        for doc in docs:
            if not self._is_transferable_upload(doc):
                continue
            if doc.vector_document_id:
                try:
                    await ingestion.remove_document(
                        source_kb.collection_name, doc.vector_document_id
                    )
                except Exception:
                    logger.exception("Failed to remove RAG doc %s from source KB", doc.id)

            doc.knowledge_base_id = target_kb.id
            doc.collection_name = target_kb.collection_name
            doc.status = DocumentStatus.PROCESSING
            doc.vector_document_id = None
            doc.chunk_count = 0
            doc.error_message = None
            doc.completed_at = None
            await self.db.flush()

            if not doc.storage_path:
                stats.documents_skipped += 1
                continue
            file_path = storage.get_full_path(doc.storage_path)
            if not file_path or not file_path.is_file():
                stats.documents_skipped += 1
                continue

            file_data = file_path.read_bytes()
            await rag_svc._queue_parse(
                doc.id,
                collection_name=target_kb.collection_name,
                filename=doc.filename,
                file_data=file_data,
                replace=True,
                attempt=1,
            )
            stats.documents_transferred += 1

    async def _repoint_references(
        self,
        *,
        minerp_tenant_id: UUID,
        organization_id: UUID,
        from_kb_id: UUID,
        to_kb_id: UUID,
    ) -> None:
        settings = await shop_ai_settings_repo.get(self.db, minerp_tenant_id)
        if settings is not None and settings.default_faq_suggestion_kb_id == from_kb_id:
            await shop_ai_settings_repo.set_default_faq_suggestion_kb_id(
                self.db,
                minerp_tenant_id,
                organization_id=organization_id,
                kb_id=to_kb_id,
            )
        await self.db.flush()
