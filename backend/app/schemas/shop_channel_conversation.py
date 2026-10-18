"""Shop channel session inbox schemas (Zalo / Messenger live agent)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopChannelSessionRead(BaseSchema):
    id: UUID
    bot_id: UUID
    bot_name: str
    platform: str
    platform_chat_id: str
    conversation_id: UUID | None = None
    customer_label: str
    customer_ref: str
    handling_mode: str
    claimed_by_user_id: UUID | None = None
    claimed_by_name: str | None = None
    claimed_at: datetime | None = None
    message_count: int = 0
    preview: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime


class ShopChannelSessionList(BaseSchema):
    items: list[ShopChannelSessionRead]
    total: int


class ShopChannelMessageRead(BaseSchema):
    id: UUID
    role: str
    content: str
    sender_type: str = Field(description="customer | bot | staff")
    created_at: datetime


class ShopChannelMessageList(BaseSchema):
    items: list[ShopChannelMessageRead]
    total: int


class ShopChannelSessionClaimIn(BaseSchema):
    claimed_by_user_id: UUID
    claimed_by_name: str | None = None


class ShopChannelSessionReplyIn(BaseSchema):
    text: str = Field(min_length=1, max_length=4000)
    staff_user_id: UUID | None = None
    staff_name: str | None = None
