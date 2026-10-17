"""Shop widget conversation inbox schemas (Studio)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopWidgetConversationRead(BaseSchema):
    id: UUID
    session_id: UUID | None = None
    customer_label: str | None = None
    customer_ref: str
    shopper_user_id: UUID | None = None
    shopper_email: str | None = None
    message_count: int = 0
    preview: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    handling_mode: str = "ai"
    claimed_by_name: str | None = None


class ShopWidgetConversationList(BaseSchema):
    items: list[ShopWidgetConversationRead]
    total: int


class ShopWidgetMessageRead(BaseSchema):
    id: UUID
    role: str
    content: str
    sender_type: str = Field(description="customer | bot | staff")
    created_at: datetime


class ShopWidgetMessageList(BaseSchema):
    items: list[ShopWidgetMessageRead]
    total: int


class ShopWidgetStaffClaimIn(BaseSchema):
    claimed_by_user_id: UUID
    claimed_by_name: str | None = None


class ShopWidgetStaffReplyIn(BaseSchema):
    text: str = Field(min_length=1, max_length=4000)
