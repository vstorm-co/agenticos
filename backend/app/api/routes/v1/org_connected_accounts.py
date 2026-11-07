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
from app.schemas.connected_account import (
    ConnectedAccountList,
    ConnectedAccountRead,
    ConnectedAccountStart,
    ConnectedAccountToken,
    ConnectedApplicationAccount,
    ConnectedImapAccount,
    ConnectedOdooAccount,
)
from app.schemas.mcp_connection import McpOAuthStartResult

router = APIRouter()


@router.get(
    "",
    response_model=ConnectedAccountList,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def list_org_accounts(service: McpConnectionSvc, ctx: Auth, provider: str = "google") -> Any:
    """The organization's connected accounts, oldest first."""
    accounts = await service.list_accounts(ctx, for_organization=True, provider=provider)
    return ConnectedAccountList(
        items=[
            ConnectedAccountRead.from_model(
                account,
                needs_reconnect=await service.account_needs_reconnect(
                    account, organization_id=ctx.organization_id
                ),
            )
            for account in accounts
        ],
        total=len(accounts),
    )


@router.post(
    "/oauth/start",
    response_model=McpOAuthStartResult,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def start_org_account(
    data: ConnectedAccountStart, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Begin connecting a Google account for the organization.

    A `404` while the organization has stored no Google OAuth client.
    """
    authorization_url = await service.account_start(
        ctx,
        browser_nonce=data.browser_nonce,
        provider=data.provider,
        products=data.products,
        label=data.label,
        write=data.write,
        for_organization=True,
    )
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


@router.post(
    "/slack/token",
    response_model=ConnectedAccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def connect_slack_token(
    data: ConnectedAccountToken, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect a validated Slack user or bot token without OAuth."""
    row = await service.connect_slack_token(
        ctx, token=data.token, label=data.label, for_organization=True
    )
    return ConnectedAccountRead.from_model(row)


@router.post(
    "/application",
    response_model=ConnectedAccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def connect_application_account(
    data: ConnectedApplicationAccount, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect a Google service account or a Microsoft application from its vault credential."""
    row = await service.connect_application_account(ctx, **data.model_dump())
    return ConnectedAccountRead.from_model(row)


@router.post(
    "/imap",
    response_model=ConnectedAccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def connect_imap_account(
    data: ConnectedImapAccount, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect an IMAP mailbox over verified TLS using an app password."""
    row = await service.connect_imap_account(
        ctx, credential=data.credential, label=data.label, for_organization=True
    )
    return ConnectedAccountRead.from_model(row)


@router.post(
    "/odoo",
    response_model=ConnectedAccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def connect_odoo_account(
    data: ConnectedOdooAccount, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Validate an Odoo 19+ JSON-2 API key and seal its database connection."""
    row = await service.connect_odoo_account(
        ctx,
        credential=data.credential,
        label=data.label,
        write=data.write,
        for_organization=True,
    )
    return ConnectedAccountRead.from_model(row)
