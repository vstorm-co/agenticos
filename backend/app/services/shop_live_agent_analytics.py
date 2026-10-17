"""Live-agent analytics — widget metrics on Agentra OLTP (D3 B55)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import median
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.db.models.shop_widget_handling import ShopWidgetHandling
from app.repositories import shop_widget_conversation as widget_conv_repo
from app.repositories import shop_widget_handling as widget_handling_repo
from app.schemas.shop_live_agent_analytics import ShopLiveAgentAnalyticsReportRead
from app.services.shop_channel_handling import HANDLING_MODE_HUMAN, STAFF_MESSAGE_MODEL
from app.services.shop_live_agent_inbox import ShopLiveAgentInboxService
from app.services.shop_widget_customer import (
    WIDGET_CONVERSATION_TITLE,
    parse_widget_customer_identity,
)


def _seconds_delta(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds())


class ShopLiveAgentAnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build_report(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        days: int = 7,
    ) -> ShopLiveAgentAnalyticsReportRead:
        since = datetime.now(UTC) - timedelta(days=days)
        inbox = await ShopLiveAgentInboxService(self.db).build_summary(
            organization_id=organization_id,
            tenant_id=tenant_id,
        )
        human_widget = await widget_handling_repo.count_by_handling_mode_for_organization(
            self.db,
            organization_id,
            handling_mode=HANDLING_MODE_HUMAN,
        )
        sessions_claimed = await self._count_widget_claims_since(
            organization_id=organization_id,
            since=since,
        )
        staff_reply_count = await self._count_staff_replies_since(
            organization_id=organization_id,
            since=since,
        )
        response_samples = await self._first_response_seconds_samples(
            organization_id=organization_id,
            tenant_id=tenant_id,
            since=since,
        )

        avg_seconds: float | None = None
        med_seconds: float | None = None
        if response_samples:
            avg_seconds = sum(response_samples) / len(response_samples)
            med_seconds = float(median(response_samples))

        return ShopLiveAgentAnalyticsReportRead(
            period_days=days,
            queued_total=inbox.queued_total,
            human_active_total=human_widget,
            sessions_claimed=sessions_claimed,
            staff_reply_count=staff_reply_count,
            avg_first_response_seconds=avg_seconds,
            median_first_response_seconds=med_seconds,
            samples_first_response=len(response_samples),
        )

    async def _count_widget_claims_since(
        self,
        *,
        organization_id: UUID,
        since: datetime,
    ) -> int:
        query = (
            select(func.count())
            .select_from(ShopWidgetHandling)
            .join(Conversation, ShopWidgetHandling.conversation_id == Conversation.id)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.user_id.is_(None),
                or_(
                    Conversation.title == WIDGET_CONVERSATION_TITLE,
                    Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
                ),
                ShopWidgetHandling.claimed_at.is_not(None),
                ShopWidgetHandling.claimed_at >= since,
            )
        )
        return int((await self.db.scalar(query)) or 0)

    async def _count_staff_replies_since(
        self,
        *,
        organization_id: UUID,
        since: datetime,
    ) -> int:
        widget_conv_subq = (
            select(Conversation.id)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.user_id.is_(None),
                or_(
                    Conversation.title == WIDGET_CONVERSATION_TITLE,
                    Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
                ),
            )
            .scalar_subquery()
        )
        query = select(func.count(Message.id)).where(
            Message.created_at >= since,
            Message.role == "assistant",
            Message.model_name == STAFF_MESSAGE_MODEL,
            Message.conversation_id.in_(widget_conv_subq),
        )
        return int((await self.db.scalar(query)) or 0)

    async def _first_response_seconds_samples(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
        since: datetime,
    ) -> list[float]:
        samples: list[float] = []
        widget_rows = await self.db.execute(
            select(ShopWidgetHandling, Conversation)
            .join(Conversation, ShopWidgetHandling.conversation_id == Conversation.id)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.user_id.is_(None),
                or_(
                    Conversation.title == WIDGET_CONVERSATION_TITLE,
                    Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
                ),
                ShopWidgetHandling.claimed_at.is_not(None),
                ShopWidgetHandling.claimed_at >= since,
            )
        )
        for handling, conv in widget_rows.all():
            claimed_at = handling.claimed_at
            if claimed_at is None:
                continue
            conv_ids = [handling.conversation_id]
            identity = parse_widget_customer_identity(conv.title)
            if identity.session_id is not None:
                conv_ids = await widget_conv_repo.list_conversation_ids_for_widget_session(
                    self.db,
                    organization_id=organization_id,
                    tenant_id=tenant_id,
                    session_id=identity.session_id,
                )
            first_at = await self._first_staff_message_at(
                conversation_ids=conv_ids,
                after=claimed_at,
            )
            if first_at is not None:
                samples.append(_seconds_delta(claimed_at, first_at))
        return samples

    async def _first_staff_message_at(
        self,
        *,
        conversation_ids: list[UUID],
        after: datetime,
    ) -> datetime | None:
        if not conversation_ids:
            return None
        result = await self.db.execute(
            select(Message.created_at)
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.role == "assistant",
                Message.model_name == STAFF_MESSAGE_MODEL,
                Message.created_at >= after,
            )
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()
