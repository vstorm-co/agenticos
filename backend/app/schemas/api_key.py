"""Organization API key schemas (#1794)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.core.permissions import Perm
from app.schemas.base import BaseSchema

ApiKeyStatus = Literal["active", "expired", "revoked"]
ApiKeyPresetId = Literal["read_only", "knowledge_ingest", "full_access"]


class ApiKeyCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=100, description="What the key is for")
    scopes: list[Perm] = Field(
        min_length=1,
        description=(
            "Permissions from the catalog the key may use. Each must be one the issuer "
            "holds; at use, the issuer's current role narrows them further"
        ),
    )
    expires_at: AwareDatetime | None = Field(
        default=None, description="When the key stops working; omit for no expiry"
    )


class ApiKeyRead(BaseSchema):
    id: UUID
    name: str
    prefix: str = Field(description="The key's first characters - enough to recognise it")
    scopes: list[str]
    user_id: UUID = Field(description="The member whose authority the key carries")
    issuer_email: str
    status: ApiKeyStatus
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    key: str = Field(description="The key itself. Returned only in this response - store it now")


class ApiKeyList(BaseSchema):
    items: list[ApiKeyRead]
    total: int


class ApiKeyPreset(BaseSchema):
    id: ApiKeyPresetId
    scopes: list[str]


class ApiKeyScopeCatalog(BaseSchema):
    """What the caller may put on a key: their own permissions, and the presets."""

    scopes: list[str]
    presets: list[ApiKeyPreset]
