"""Shop Zalo OAuth start request (Studio parity)."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopZaloOAuthStartIn(BaseSchema):
    name: str = Field(default="", max_length=255)
    default_kb_id: UUID | None = None
    bot_id: UUID | None = Field(
        default=None,
        description="Reconnect OAuth for an existing bot",
    )
    return_url: str | None = Field(default=None, max_length=2000)
    failure_url: str | None = Field(default=None, max_length=2000)


class ShopZaloOAuthStartOut(BaseSchema):
    authorize_url: str
