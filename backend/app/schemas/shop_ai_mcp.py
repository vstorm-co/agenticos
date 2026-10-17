"""Shop Studio MCP wire format (compatible with multi-agent / storefront Studio)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema

ShopMcpPerm = Literal["readonly", "safe", "full"]


class ShopMcpCatalogConnectorRead(BaseSchema):
    id: str
    name: str
    description: str = ""
    transport: str
    default_perm: ShopMcpPerm = "readonly"
    auth: str | None = None
    tools: list[dict] = Field(default_factory=list)


class ShopMcpCatalogList(BaseSchema):
    items: list[ShopMcpCatalogConnectorRead]
    total: int


class ShopMcpConnectionRead(TimestampSchema):
    id: UUID
    connector_id: str
    name: str
    account_label: str | None = None
    perm: ShopMcpPerm = "readonly"
    organization_id: UUID | None = None
    tenant_id: UUID | None = None
    is_active: bool
    has_credentials: bool = False
    config_json: dict | None = None
    last_health_at: datetime | None = None
    last_health_ok: bool | None = None
    last_health_message: str | None = None
    oauth_connected: bool = False


class ShopMcpConnectionList(BaseSchema):
    items: list[ShopMcpConnectionRead]
    total: int


class ShopMcpConnectionCreate(BaseSchema):
    """Shop Studio wire format (multi-agent compatible)."""

    connector_id: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    account_label: str | None = Field(default=None, max_length=255)
    perm: ShopMcpPerm = "readonly"
    bearer_token: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=500)
    oauth_authorize_url: str | None = Field(default=None, max_length=500)
    oauth_token_url: str | None = Field(default=None, max_length=500)
    oauth_client_id: str | None = Field(default=None, max_length=255)
    oauth_scopes: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=4096)


class ShopMcpConnectionUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    account_label: str | None = Field(default=None, max_length=255)
    perm: ShopMcpPerm | None = None
    is_active: bool | None = None
    bearer_token: str | None = None
    base_url: str | None = Field(default=None, max_length=500)
    oauth_authorize_url: str | None = Field(default=None, max_length=500)
    oauth_token_url: str | None = Field(default=None, max_length=500)
    oauth_client_id: str | None = Field(default=None, max_length=255)
    oauth_scopes: str | None = Field(default=None, max_length=500)
    client_secret: str | None = None


class ShopMcpConnectionTestResult(BaseSchema):
    ok: bool
    message: str
    tested_at: datetime
