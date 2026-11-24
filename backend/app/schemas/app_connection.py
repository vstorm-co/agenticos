"""Safe browser contract for managed app connections; no provider credentials."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from app.schemas.base import BaseSchema


class AppActionRead(BaseSchema):
    name: str
    label: str
    read_only: bool
    side_effecting: bool
    scopes: list[str]


class AppCatalogEntry(BaseSchema):
    key: str
    toolkit: str
    name: str
    description: str
    category: str
    configured: bool
    availability: Literal["ready", "setup_required", "unavailable"]
    approval_required: bool = False
    action_count: int = Field(ge=0)
    actions: list[AppActionRead]


class AppCatalogRead(BaseSchema):
    configured: bool
    catalog_available: bool
    apps: list[AppCatalogEntry]
    next_cursor: str | None = None


class AppConnectionCreate(BaseSchema):
    toolkit: str = Field(min_length=1, max_length=55, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str | None = Field(default=None, min_length=1, max_length=64)


class AppConnectionStartRead(BaseSchema):
    connection_id: UUID
    attempt_id: UUID
    redirect_url: str
    expires_at: datetime


class AppConnectionCallback(BaseSchema):
    attempt_id: UUID | None = None
    connected_account_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_uri: SecretStr | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def identify_attempt(self) -> AppConnectionCallback:
        if self.session_uri is None and self.attempt_id is None:
            raise ValueError("A connection attempt or identity verification session is required")
        return self


class AppConnectionRead(BaseSchema):
    id: UUID
    catalog_key: str
    toolkit: str
    name: str
    label: str | None
    identity: str | None
    status: Literal["pending", "connected", "expired", "failed", "disabled"]
    is_enabled: bool
    is_default: bool
    authorized: bool
    readiness: Literal["authorization_required", "authorization_verified", "unavailable"]
    app: AppCatalogEntry
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime


class AppConnectionList(BaseSchema):
    items: list[AppConnectionRead]
    total: int
