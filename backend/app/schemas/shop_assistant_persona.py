"""Shop assistant persona schemas (D3 B59)."""

from pydantic import Field

from app.schemas.base import BaseSchema

ASSISTANT_TONES = frozenset({"friendly", "formal", "playful"})


class ShopAssistantPersonaRead(BaseSchema):
    assistant_name: str | None = None
    assistant_tone: str | None = None
    assistant_custom_instructions: str | None = None
    merchant_morning_digest_enabled: bool = False


class ShopAssistantPersonaPatch(BaseSchema):
    assistant_name: str | None = Field(default=None, max_length=80)
    assistant_tone: str | None = Field(default=None, max_length=32)
    assistant_custom_instructions: str | None = Field(default=None, max_length=4000)
    merchant_morning_digest_enabled: bool | None = None
