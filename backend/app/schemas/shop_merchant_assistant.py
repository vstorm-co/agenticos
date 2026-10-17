"""Studio merchant assistant chat (Shop owner / Jarvis)."""

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopMerchantAssistantChatIn(BaseSchema):
    message: str = Field(min_length=1, max_length=4000)


class ShopMerchantAssistantChatOut(BaseSchema):
    reply: str
