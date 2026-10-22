"""The caller's own connected accounts (#2191).

A mount bound to "each person's own account" reads the account of whoever is
talking to the agent, so these are a person's to connect and disconnect, with no
organization permission: they act on nobody else's data.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, McpConnectionSvc
from app.schemas.connected_account import ConnectedAccountList, ConnectedAccountRead
from app.schemas.mcp_connection import McpOAuthStartResult

router = APIRouter()


@router.get("", response_model=ConnectedAccountList)
async def list_my_accounts(service: McpConnectionSvc, ctx: Auth) -> Any:
    """The caller's connected accounts, oldest first."""
    accounts = await service.list_accounts(ctx, for_organization=False)
    return ConnectedAccountList(
        items=[ConnectedAccountRead.from_model(account) for account in accounts],
        total=len(accounts),
    )


@router.post("/oauth/start", response_model=McpOAuthStartResult)
async def start_my_account(service: McpConnectionSvc, ctx: Auth) -> Any:
    """Begin connecting a Google account of the caller's, with the organization's OAuth client.

    A `404` while the organization has stored no Google OAuth client: the page
    shows that as the prerequisite it is.
    """
    authorization_url = await service.account_start(ctx, for_organization=False)
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_my_account(account_id: UUID, service: McpConnectionSvc, ctx: Auth) -> None:
    """Disconnect one of the caller's accounts."""
    await service.delete_account(ctx, account_id, for_organization=False)
