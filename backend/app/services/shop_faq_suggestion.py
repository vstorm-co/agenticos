"""FAQ suggestions from widget inbox (D3 B56)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_commit
from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.shop_faq_suggestion import ShopFaqSuggestion
from app.repositories import (
    knowledge_base_repo,
    shop_ai_settings as shop_ai_settings_repo,
    shop_faq_suggestion as suggestion_repo,
)
from app.schemas.shop_faq import (
    ShopFaqEntryCreate,
    ShopFaqEntryRead,
    ShopFaqSuggestionAccept,
    ShopFaqSuggestionList,
    ShopFaqSuggestionRead,
)
from app.services.shop_faq_suggestion_utils import is_faq_kb, question_fingerprint
from app.services.shop_widget_faq_rag import retrieve_faq_rag_draft_text

logger = logging.getLogger(__name__)

# Re-export for callers that imported from this module (B56).
__all__ = ["ShopFaqSuggestionService", "is_faq_kb"]


class ShopFaqSuggestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def promote_from_inbox(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        question: str,
    ) -> ShopFaqSuggestionRead:
        text = (question or "").strip()
        if len(text) < 3:
            raise BadRequestError(
                message="Question text too short",
                details={"min_length": 3},
            )
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        row = await self._upsert_suggestion(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb=kb,
            text=text,
            source="inbox",
        )
        return self._to_read(row, minerp_tenant_id=minerp_tenant_id)

    async def list_suggestions(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        status: str = "pending",
    ) -> ShopFaqSuggestionList:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        rows = await suggestion_repo.list_for_kb(
            self.db,
            kb_id=kb.id,
            minerp_tenant_id=minerp_tenant_id,
            status=status,
        )
        items = [self._to_read(row, minerp_tenant_id=minerp_tenant_id) for row in rows]
        return ShopFaqSuggestionList(items=items, total=len(items))

    async def dismiss(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        suggestion_id: UUID,
    ) -> ShopFaqSuggestionRead:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        suggestion = await self._get_or_404(
            kb_id=kb.id,
            minerp_tenant_id=minerp_tenant_id,
            suggestion_id=suggestion_id,
        )
        if suggestion.status != "pending":
            raise BadRequestError(
                message="Only pending suggestions can be dismissed",
                details={"suggestion_id": str(suggestion_id), "status": suggestion.status},
            )
        await suggestion_repo.update_status(self.db, suggestion, status="dismissed")
        return self._to_read(suggestion, minerp_tenant_id=minerp_tenant_id)

    async def draft_answer(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        suggestion_id: UUID,
    ) -> ShopFaqSuggestionRead:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        suggestion = await self._get_or_404(
            kb_id=kb.id,
            minerp_tenant_id=minerp_tenant_id,
            suggestion_id=suggestion_id,
        )
        if suggestion.status != "pending":
            raise BadRequestError(
                message="Draft answer only available for pending suggestions",
                details={"suggestion_id": str(suggestion_id)},
            )

        answer = await retrieve_faq_rag_draft_text(
            self.db,
            tenant_id=minerp_tenant_id,
            question=suggestion.question_text,
            kb_id=kb.id,
        )
        if not answer:
            raise BadRequestError(
                message="No knowledge base excerpts found for this question",
                details={"suggestion_id": str(suggestion_id)},
            )

        await suggestion_repo.set_suggested_answer(
            self.db, suggestion, answer=answer, auto=False
        )
        return self._to_read(suggestion, minerp_tenant_id=minerp_tenant_id)

    async def accept(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        suggestion_id: UUID,
        data: ShopFaqSuggestionAccept,
    ) -> ShopFaqEntryRead:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        suggestion = await self._get_or_404(
            kb_id=kb.id,
            minerp_tenant_id=minerp_tenant_id,
            suggestion_id=suggestion_id,
        )
        if suggestion.status != "pending":
            raise BadRequestError(
                message="Only pending suggestions can be accepted",
                details={"suggestion_id": str(suggestion_id), "status": suggestion.status},
            )

        answer = (data.answer or suggestion.suggested_answer or "").strip()
        if not answer:
            raise BadRequestError(
                message="Answer required — generate a draft or provide answer text",
                details={"suggestion_id": str(suggestion_id)},
            )

        entry = await self._create_faq_entry_for_accept(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=kb.id,
            question=suggestion.question_text,
            answer=answer,
            is_published=data.is_published,
        )
        await suggestion_repo.update_status(self.db, suggestion, status="accepted")
        return entry

    async def auto_draft_pending_suggestion(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        suggestion_id: UUID,
    ) -> bool:
        kb = await self._require_faq_kb(organization_id=organization_id, kb_id=kb_id)
        suggestion = await self._get_or_404(
            kb_id=kb.id,
            minerp_tenant_id=minerp_tenant_id,
            suggestion_id=suggestion_id,
        )
        if suggestion.status != "pending" or suggestion.suggested_answer:
            return False

        settings_row = await shop_ai_settings_repo.get(self.db, minerp_tenant_id)
        threshold = (
            settings_row.auto_draft_faq_min_occurrences if settings_row is not None else 0
        )
        if threshold <= 0 or suggestion.occurrence_count < threshold:
            return False

        answer = await retrieve_faq_rag_draft_text(
            self.db,
            tenant_id=minerp_tenant_id,
            question=suggestion.question_text,
            kb_id=kb.id,
        )
        if not answer:
            logger.warning(
                "FAQ auto-draft skipped — no RAG excerpt for suggestion %s",
                suggestion_id,
            )
            return False

        await suggestion_repo.set_suggested_answer(
            self.db,
            suggestion,
            answer=answer,
            auto=True,
        )
        return True

    async def _create_faq_entry_for_accept(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        question: str,
        answer: str,
        is_published: bool,
    ) -> ShopFaqEntryRead:
        from app.services.shop_faq_sync import ShopFaqService

        return await ShopFaqService(self.db).create_entry(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=kb_id,
            data=ShopFaqEntryCreate(
                question=question,
                answer=answer,
                is_published=is_published,
            ),
        )

    async def _get_or_404(
        self,
        *,
        kb_id: UUID,
        minerp_tenant_id: UUID,
        suggestion_id: UUID,
    ) -> ShopFaqSuggestion:
        suggestion = await suggestion_repo.get_by_id(
            self.db,
            suggestion_id=suggestion_id,
            kb_id=kb_id,
            minerp_tenant_id=minerp_tenant_id,
        )
        if suggestion is None:
            raise NotFoundError(
                message="FAQ suggestion not found",
                details={"suggestion_id": str(suggestion_id)},
            )
        return suggestion

    async def _require_faq_kb(self, *, organization_id: UUID, kb_id: UUID) -> KnowledgeBase:
        kb = await knowledge_base_repo.get_by_id(self.db, kb_id)
        if kb is None or kb.organization_id != organization_id:
            raise NotFoundError(
                message="Knowledge base not found",
                details={"knowledge_base_id": str(kb_id)},
            )
        if not is_faq_kb(kb):
            raise BadRequestError(
                message="Knowledge base is not eligible for FAQ suggestions",
                details={"knowledge_base_id": str(kb_id)},
            )
        return kb

    async def _upsert_suggestion(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb: KnowledgeBase,
        text: str,
        source: str,
    ) -> ShopFaqSuggestion:
        fp = question_fingerprint(text)
        existing = await suggestion_repo.get_by_fingerprint(
            self.db,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=kb.id,
            fingerprint=fp,
        )
        if existing is None:
            row = await suggestion_repo.create(
                self.db,
                minerp_tenant_id=minerp_tenant_id,
                organization_id=organization_id,
                knowledge_base_id=kb.id,
                question_fingerprint=fp,
                question_text=text,
                source=source,
            )
            await self._maybe_enqueue_auto_draft(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
                kb_id=kb.id,
                suggestion=row,
            )
            return row
        if existing.status != "pending":
            return existing
        row = await suggestion_repo.bump_occurrence(self.db, existing, question_text=text)
        await self._maybe_enqueue_auto_draft(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=kb.id,
            suggestion=row,
        )
        return row

    async def _maybe_enqueue_auto_draft(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        kb_id: UUID,
        suggestion: ShopFaqSuggestion,
    ) -> None:
        settings_row = await shop_ai_settings_repo.get(self.db, minerp_tenant_id)
        threshold = (
            settings_row.auto_draft_faq_min_occurrences if settings_row is not None else 0
        )
        if threshold <= 0:
            return
        if suggestion.status != "pending" or suggestion.suggested_answer:
            return
        if suggestion.occurrence_count < threshold:
            return
        _schedule_auto_draft_task(
            self.db,
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=kb_id,
            suggestion_id=suggestion.id,
        )

    @staticmethod
    def _to_read(row: ShopFaqSuggestion, *, minerp_tenant_id: UUID) -> ShopFaqSuggestionRead:
        return ShopFaqSuggestionRead(
            id=row.id,
            knowledge_base_id=row.knowledge_base_id,
            tenant_id=minerp_tenant_id,
            question_text=row.question_text,
            occurrence_count=row.occurrence_count,
            source=row.source,
            status=row.status,
            suggested_answer=row.suggested_answer,
            suggested_answer_auto=row.suggested_answer_auto,
            suggested_answer_at=row.suggested_answer_at,
            last_seen_at=row.last_seen_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


def _schedule_auto_draft_task(
    session: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    kb_id: UUID,
    suggestion_id: UUID,
) -> None:
    try:
        from app.worker.tasks.shop_faq_auto_draft import run_faq_auto_draft_background

        spawn_after_commit(
            session,
            run_faq_auto_draft_background(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
                kb_id=kb_id,
                suggestion_id=suggestion_id,
            ),
            name=f"shop_faq_auto_draft:{suggestion_id}",
        )
    except Exception:
        logger.warning(
            "Could not schedule FAQ auto-draft for suggestion %s",
            suggestion_id,
            exc_info=True,
        )
