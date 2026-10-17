"""Shop FAQ curation settings schemas (D3 B58)."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopFaqSettingsRead(BaseSchema):
    default_faq_suggestion_kb_id: UUID | None = None
    default_faq_suggestion_kb_name: str | None = None
    auto_draft_faq_min_occurrences: int = 0


class ShopFaqSettingsPatch(BaseSchema):
    default_faq_suggestion_kb_id: UUID | None = None
    auto_draft_faq_min_occurrences: int | None = Field(default=None, ge=0, le=99)
