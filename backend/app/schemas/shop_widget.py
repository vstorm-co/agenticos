"""Shop A public widget chat schemas."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.shop_widget_action import ShopWidgetAction


class ShopWidgetChatIn(BaseSchema):
    """Anonymous storefront widget message."""

    message: str = Field(..., min_length=1, max_length=2000)
    session_id: UUID
    kb_id: UUID | None = Field(default=None, description="FAQ knowledge base override")
    shopper_user_id: UUID | None = Field(
        default=None,
        description="Logged-in storefront shopper (optional)",
    )
    shopper_display_name: str | None = Field(default=None, max_length=120)
    shopper_email: str | None = Field(default=None, max_length=255)


class ShopWidgetChatOut(BaseSchema):
    """Widget chat reply."""

    reply: str
    session_id: UUID
    actions: list[ShopWidgetAction] = Field(default_factory=list)
    handling_mode: str = Field(default="ai", description="ai | queued | human")


class ShopWidgetPollOut(BaseSchema):
    """New widget thread messages for client polling."""

    session_id: UUID
    handling_mode: str = "ai"
    items: list[dict] = Field(default_factory=list)
