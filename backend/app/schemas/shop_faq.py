"""Shop FAQ suggestion schemas (D3 B56)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopFaqSuggestionRead(BaseSchema):
    id: UUID
    knowledge_base_id: UUID
    tenant_id: UUID
    question_text: str
    occurrence_count: int
    source: str
    status: str
    suggested_answer: str | None = None
    suggested_answer_auto: bool = False
    suggested_answer_at: datetime | None = None
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime | None = None


class ShopFaqSuggestionList(BaseSchema):
    items: list[ShopFaqSuggestionRead]
    total: int


class ShopFaqInboxPromoteIn(BaseSchema):
    kb_id: UUID | None = None


class ShopFaqEntryCreate(BaseSchema):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_published: bool = True


class ShopFaqEntryUpdate(BaseSchema):
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    answer: str | None = Field(default=None, min_length=1, max_length=8000)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_published: bool | None = None


class ShopFaqEntryRead(BaseSchema):
    id: UUID
    knowledge_base_id: UUID
    tenant_id: UUID
    question: str
    answer: str
    sort_order: int
    is_published: bool
    rag_status: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ShopFaqEntryList(BaseSchema):
    items: list[ShopFaqEntryRead]
    total: int


class ShopFaqSuggestionAccept(BaseSchema):
    answer: str | None = Field(default=None, min_length=1, max_length=8000)
    is_published: bool = True
