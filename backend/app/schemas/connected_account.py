"""Connected accounts: OAuth grants a virtual terminal's mount signs in as (#2191).

A response names the account and what it was granted, never a token: the grant is
sealed in the vault and leaves it only for a run that mounts the account.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.db.models.mcp_connection import McpConnection
from app.schemas.base import BaseSchema


class ConnectedAccountRead(BaseSchema):
    """One connected account, as its owner and an agent's editor see it."""

    id: UUID
    provider: Literal["google"]
    email: str
    scopes: list[str]
    owner: Literal["personal", "organization"]
    needs_reconnect: bool
    """Its grant stopped working - revoked, expired - and it has to be connected again."""
    created_at: datetime

    @classmethod
    def from_model(cls, account: McpConnection) -> ConnectedAccountRead:
        return cls(
            id=account.id,
            provider="google",
            email=account.label or account.name,
            scopes=sorted(account.granted_scopes or ()),
            owner="organization" if account.scope == "org" else "personal",
            needs_reconnect=account.authorization_expired,
            created_at=account.created_at,
        )


class ConnectedAccountList(BaseSchema):
    items: list[ConnectedAccountRead]
    total: int
