"""Derive chatbot quality signals from widget conversations + FAQ suggestions (B61)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.repositories import knowledge_base_repo, shop_faq_suggestion as suggestion_repo
from app.schemas.shop_widget_quality import (
    ShopChatQualityFaqGapRead,
    ShopChatQualityReportRead,
    ShopChatQualitySummaryRead,
    ShopChatQualityWeakReplyRead,
)
from app.services.shop_faq_suggestion_utils import is_faq_kb
from app.services.shop_widget_customer import WIDGET_CONVERSATION_TITLE
from app.services.shop_widget_quality_heuristics import looks_like_weak_assistant_reply


class ShopWidgetQualityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build_report(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        days: int = 7,
        weak_limit: int = 20,
        faq_gap_limit: int = 15,
    ) -> ShopChatQualityReportRead:
        period_days = max(1, min(days, 90))
        since = datetime.now(UTC) - timedelta(days=period_days)

        conv_base = select(Conversation.id).where(
            Conversation.organization_id == organization_id,
            Conversation.user_id.is_(None),
            or_(
                Conversation.title == WIDGET_CONVERSATION_TITLE,
                Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
            ),
            func.coalesce(Conversation.updated_at, Conversation.created_at) >= since,
        )
        widget_conversation_count = int(
            (await self.db.execute(select(func.count()).select_from(conv_base.subquery()))).scalar_one()
        )

        weak_replies = await self._collect_weak_replies(
            organization_id=organization_id,
            since=since,
            limit=weak_limit,
        )
        faq_gaps = await self._collect_faq_gaps(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            limit=faq_gap_limit,
        )

        return ShopChatQualityReportRead(
            period_days=period_days,
            widget_conversation_count=widget_conversation_count,
            weak_replies=weak_replies,
            faq_gaps=faq_gaps,
        )

    async def build_summary(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        days: int = 7,
    ) -> ShopChatQualitySummaryRead:
        report = await self.build_report(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            days=days,
        )
        return ShopChatQualitySummaryRead(
            period_days=report.period_days,
            weak_reply_count=len(report.weak_replies),
            faq_gap_count=len(report.faq_gaps),
            faq_pending_count=len(report.faq_gaps),
        )

    async def _collect_weak_replies(
        self,
        *,
        organization_id: UUID,
        since: datetime,
        limit: int,
    ) -> list[ShopChatQualityWeakReplyRead]:
        conv_ids_subq = (
            select(Conversation.id)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.user_id.is_(None),
                or_(
                    Conversation.title == WIDGET_CONVERSATION_TITLE,
                    Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
                ),
            )
            .subquery()
        )

        rows = (
            await self.db.execute(
                select(Message)
                .where(
                    Message.conversation_id.in_(select(conv_ids_subq.c.id)),
                    Message.role == "assistant",
                    Message.created_at >= since,
                )
                .order_by(Message.created_at.desc())
                .limit(limit * 4)
            )
        ).scalars().all()

        items: list[ShopChatQualityWeakReplyRead] = []
        for assistant_msg in rows:
            content = assistant_msg.content or ""
            if not looks_like_weak_assistant_reply(content):
                continue
            user_msg = (
                await self.db.execute(
                    select(Message.content)
                    .where(
                        Message.conversation_id == assistant_msg.conversation_id,
                        Message.role == "user",
                        Message.created_at <= assistant_msg.created_at,
                    )
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not user_msg:
                continue
            items.append(
                ShopChatQualityWeakReplyRead(
                    conversation_id=assistant_msg.conversation_id,
                    message_id=assistant_msg.id,
                    user_message=user_msg.strip(),
                    assistant_reply=content.strip()[:500],
                    created_at=assistant_msg.created_at,
                )
            )
            if len(items) >= limit:
                break
        return items

    async def _collect_faq_gaps(
        self,
        *,
        organization_id: UUID,
        minerp_tenant_id: UUID,
        limit: int,
    ) -> list[ShopChatQualityFaqGapRead]:
        faq_kbs = [
            kb
            for kb in await knowledge_base_repo.list_org_scoped(self.db, organization_id)
            if is_faq_kb(kb)
        ]
        if not faq_kbs:
            return []

        gaps: list[ShopChatQualityFaqGapRead] = []
        for kb in faq_kbs:
            rows = await suggestion_repo.list_for_kb(
                self.db,
                kb_id=kb.id,
                minerp_tenant_id=minerp_tenant_id,
                status="pending",
            )
            for row in rows:
                gaps.append(
                    ShopChatQualityFaqGapRead(
                        suggestion_id=row.id,
                        kb_id=kb.id,
                        question_text=row.question_text,
                        occurrence_count=row.occurrence_count,
                        has_draft=bool(row.suggested_answer),
                        last_seen_at=row.last_seen_at,
                    )
                )

        gaps.sort(
            key=lambda g: (g.occurrence_count, g.last_seen_at),
            reverse=True,
        )
        return gaps[:limit]
