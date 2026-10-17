"""Shop widget chat quality report schemas (D3 B61)."""

from datetime import datetime
from uuid import UUID

from app.schemas.base import BaseSchema


class ShopChatQualityWeakReplyRead(BaseSchema):
    conversation_id: UUID
    message_id: UUID
    user_message: str
    assistant_reply: str
    created_at: datetime


class ShopChatQualityFaqGapRead(BaseSchema):
    suggestion_id: UUID
    kb_id: UUID
    question_text: str
    occurrence_count: int
    has_draft: bool
    last_seen_at: datetime


class ShopChatQualityReportRead(BaseSchema):
    period_days: int
    widget_conversation_count: int
    weak_replies: list[ShopChatQualityWeakReplyRead]
    faq_gaps: list[ShopChatQualityFaqGapRead]


class ShopChatQualitySummaryRead(BaseSchema):
    period_days: int
    weak_reply_count: int
    faq_gap_count: int
    faq_pending_count: int
