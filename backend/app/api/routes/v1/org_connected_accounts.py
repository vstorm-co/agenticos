"""The organization's connected accounts (#2191).

An account the organization connected answers for everybody who talks to an agent
that mounts it, so connecting and disconnecting one takes `mcp:manage` - the gate
connecting a portal for the whole organization already has. Listing takes only
`connections:view`, so an agent's editor can pick one in the Builder.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, McpConnectionSvc, require
from app.core.permissions import Perm
from app.schemas.connected_account import ConnectedAccountList, ConnectedAccountRead
from app.schemas.mcp_connection import McpOAuthStartResult

router = APIRouter()


@router.get(
    "",
    response_model=ConnectedAccountList,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def list_org_accounts(service: McpConnectionSvc, ctx: Auth) -> Any:
    """The organization's connected accounts, oldest first."""
    accounts = await service.list_accounts(ctx, for_organization=True)
    return ConnectedAccountList(
        items=[ConnectedAccountRead.from_model(account) for account in accounts],
        total=len(accounts),
    )


@router.post(
    "/oauth/start",
    response_model=McpOAuthStartResult,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def start_org_account(service: McpConnectionSvc, ctx: Auth) -> Any:
    """Begin connecting a Google account for the organization.

    A `404` while the organization has stored no Google OAuth client.
    """
    authorization_url = await service.account_start(ctx, for_organization=True)
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def delete_org_account(account_id: UUID, service: McpConnectionSvc, ctx: Auth) -> None:
    """Disconnect one of the organization's accounts."""
    await service.delete_account(ctx, account_id, for_organization=True)
