"""Shop Studio knowledge base create (internal shop-ai BFF)."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopKnowledgeBaseCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    collection_name: str | None = Field(default=None, min_length=1, max_length=255)
    scope: str | None = Field(default=None, description="Ignored — shop KBs are org-scoped")
    tenant_id: UUID | None = Field(default=None, description="Must match X-Tenant-Id when set")
