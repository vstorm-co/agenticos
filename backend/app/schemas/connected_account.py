"""Connected accounts: OAuth grants a virtual terminal's mount signs in as (#2191).

A response names the account and what it was granted, never a token: the grant is
sealed in the vault and leaves it only for a run that mounts the account.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from app.core.mail_credential import ImapCredential
from app.db.models.mcp_connection import McpConnection
from app.schemas.base import BaseSchema


class ConnectedAccountRead(BaseSchema):
    """One connected account, as its owner and an agent's editor see it."""

    id: UUID
    provider: Literal["google", "microsoft", "slack", "imap"]
    email: str
    name: str = ""
    label: str | None = None
    scopes: list[str]
    owner: Literal["personal", "organization"]
    needs_reconnect: bool
    """Its grant stopped working - revoked, expired - and it has to be connected again."""
    created_at: datetime

    @classmethod
    def from_model(cls, account: McpConnection) -> ConnectedAccountRead:
        return cls(
            id=account.id,
            name=account.name,
            label=account.label,
            provider="microsoft"
            if account.catalog_key == "microsoft"
            else "slack"
            if account.catalog_key == "slack"
            else "imap"
            if account.catalog_key == "imap"
            else "google",
            email=account.account_email or account.label or account.name,
            scopes=sorted(account.granted_scopes or ()),
            owner="organization" if account.scope == "org" else "personal",
            needs_reconnect=not account.account_authorized or account.authorization_expired,
            created_at=account.created_at,
        )


class ConnectedAccountList(BaseSchema):
    items: list[ConnectedAccountRead]
    total: int


class ConnectedAccountStart(BaseSchema):
    label: str = Field(default="", max_length=64)
    provider: Literal["google", "microsoft", "slack", "imap"] = "google"
    products: list[str] | None = Field(default=None, max_length=12)
    write: bool = False
    browser_nonce: str = Field(min_length=32, max_length=128)


class ConnectedAccountToken(BaseSchema):
    token: SecretStr = Field(description="A Slack user or bot token, sealed before storage.")
    label: str = Field(default="", max_length=64)


class ConnectedApplicationAccount(BaseSchema):
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
    credential: ImapCredential
    label: str = Field(default="", max_length=64)
