"""Connected accounts: OAuth grants a virtual terminal's mount signs in as (#2191).

A response names the account and what it was granted, never a token: the grant is
sealed in the vault and leaves it only for a run that mounts the account.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.core.mail_credential import ImapCredential
from app.core.odoo_credential import OdooCredential
from app.db.models.mcp_connection import McpConnection
from app.schemas.base import BaseSchema


class ConnectedAccountRead(BaseSchema):
    """One connected account, as its owner and an agent's editor see it."""

    id: UUID
    provider: Literal["google", "microsoft", "slack", "imap", "odoo"]
    email: str
    name: str = ""
    label: str | None = None
    scopes: list[str]
    owner: Literal["personal", "organization"]
    needs_reconnect: bool
    """Its grant expired, was revoked, or lost its source credential and must be reconnected."""
    auth_type: str = "oauth"
    polling_failed: bool = False
    created_at: datetime

    @classmethod
    def from_model(
        cls, account: McpConnection, *, needs_reconnect: bool = False
    ) -> ConnectedAccountRead:
        return cls(
            id=account.id,
            auth_type=account.auth_type or "oauth",
            polling_failed=account.last_status == "error",
            name=account.name,
            label=account.label,
            provider="microsoft"
            if account.catalog_key == "microsoft"
            else "slack"
            if account.catalog_key == "slack"
            else "imap"
            if account.catalog_key == "imap"
            else "odoo"
            if account.catalog_key == "odoo"
            else "google",
            email=account.account_email or account.label or account.name,
            scopes=sorted(account.granted_scopes or ()),
            owner="organization" if account.scope == "org" else "personal",
            needs_reconnect=needs_reconnect
            or not account.account_authorized
            or account.authorization_expired,
            created_at=account.created_at,
        )


class ConnectedAccountList(BaseSchema):
    items: list[ConnectedAccountRead]
    total: int


class ConnectedAccountStart(BaseSchema):
    connection_id: UUID | None = Field(
        default=None,
        description="Reconnect this owned account in place, preserving its ID and authentication method.",
    )
    label: str = Field(default="", max_length=64)
    provider: Literal["google", "microsoft", "slack", "imap"] = "google"
    products: list[str] | None = Field(default=None, max_length=12)
    write: bool = False
    browser_nonce: str = Field(min_length=32, max_length=128)


class ConnectedAccountToken(BaseSchema):
    write: bool = False
    connection_id: UUID | None = Field(
        default=None,
        description="Reconnect this owned account in place, preserving its ID and authentication method.",
    )
    token: SecretStr = Field(description="A Slack user or bot token, sealed before storage.")
    label: str = Field(default="", max_length=64)


class ConnectedApplicationAccount(BaseSchema):
    connection_id: UUID | None = Field(
        default=None,
        description="Reconnect this owned account in place, preserving its ID and authentication method.",
    )
    provider: Literal["google", "microsoft"]
    secret_id: UUID
    subject: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^(?:[^\s@]+@[^\s@]+|[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})$",
    )
    products: list[str] = Field(min_length=1, max_length=12)
    write: bool = False
    label: str = Field(default="", max_length=64)


class ConnectedImapAccount(BaseSchema):
    connection_id: UUID | None = Field(
        default=None,
        description="Reconnect this owned account in place, preserving its ID and authentication method.",
    )
    credential: ImapCredential
    label: str = Field(default="", max_length=64)


class ConnectedOdooAccount(BaseSchema):
    connection_id: UUID | None = Field(
        default=None,
        description="Reconnect this owned account in place, preserving its ID and authentication method.",
    )
    credential: OdooCredential
    label: str = Field(default="", max_length=64)
    write: bool = False
