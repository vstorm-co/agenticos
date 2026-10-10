"""Schemas for consenting to, and revoking, an MCP client's OAuth access (#2059)."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.core.permissions import Perm
from app.schemas.api_key import ApiKeyScopeCatalog
from app.schemas.base import BaseSchema


class OAuthConsentRead(BaseSchema):
    """What a person is asked to approve on the consent page."""

    request_id: UUID
    client_name: str
    client_uri: str | None
    redirect_host: str = Field(description="Where the person is sent back to, as a host")
    organization_id: UUID
    organization_name: str
    catalog: ApiKeyScopeCatalog


class OAuthConsentApprove(BaseSchema):
    scopes: list[Perm] = Field(min_length=1)


class OAuthConsentAnswer(BaseSchema):
    redirect_to: str = Field(description="Send the browser here to hand the answer to the client")


class OAuthGrantRead(BaseSchema):
    id: UUID
    client_name: str
    client_uri: str | None
    user_id: UUID
    user_email: str
    scopes: list[str]
    created_at: datetime


class OAuthGrantList(BaseSchema):
    items: list[OAuthGrantRead]
    total: int
