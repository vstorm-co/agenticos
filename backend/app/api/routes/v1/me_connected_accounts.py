"""The caller's own connected accounts (#2191).

A mount bound to "each person's own account" reads the account of whoever is
talking to the agent, so these are a person's to connect and disconnect, with no
organization permission. Application accounts additionally require edit authority
over their Vault credential because the chosen subject can act as another user.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, McpConnectionSvc
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
from app.services.integrations import IntegrationSetup

router = APIRouter()


@router.get("", response_model=ConnectedAccountList)
async def list_my_accounts(service: McpConnectionSvc, ctx: Auth, provider: str = "google") -> Any:
    """The caller's connected accounts, oldest first."""
    accounts = await service.list_accounts(ctx, for_organization=False, provider=provider)
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


@router.get("/setup/{provider}", response_model=IntegrationSetup)
async def integration_setup(
    provider: str, service: McpConnectionSvc, ctx: Auth, write: bool = False
) -> Any:
    """The deployment's redirect URL, exact scopes and provider-console links."""
    return service.integration_setup(provider, write=write)


@router.post("/oauth/start", response_model=McpOAuthStartResult)
async def start_my_account(
    data: ConnectedAccountStart, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Begin connecting a Google account of the caller's, with the organization's OAuth client.

    A `404` while the organization has stored no Google OAuth client: the page
    shows that as the prerequisite it is.
    """
    authorization_url = await service.account_start(
        ctx,
        browser_nonce=data.browser_nonce,
        connection_id=data.connection_id,
        provider=data.provider,
        products=data.products,
        label=data.label,
        write=data.write,
        for_organization=False,
    )
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_my_account(account_id: UUID, service: McpConnectionSvc, ctx: Auth) -> None:
    """Disconnect one of the caller's accounts."""
    await service.delete_account(ctx, account_id, for_organization=False)


@router.post(
    "/slack/token", response_model=ConnectedAccountRead, status_code=status.HTTP_201_CREATED
)
async def connect_slack_token(
    data: ConnectedAccountToken, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect a validated Slack user or bot token without OAuth."""
    row = await service.connect_slack_token(
        ctx,
        token=data.token,
        write=data.write,
        label=data.label,
        connection_id=data.connection_id,
        for_organization=False,
    )
    return ConnectedAccountRead.from_model(row)


@router.post("/imap", response_model=ConnectedAccountRead, status_code=status.HTTP_201_CREATED)
async def connect_imap_account(
    data: ConnectedImapAccount, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect an IMAP mailbox over verified TLS using an app password."""
    row = await service.connect_imap_account(
        ctx,
        credential=data.credential,
        label=data.label,
        connection_id=data.connection_id,
        for_organization=False,
    )
    return ConnectedAccountRead.from_model(row)


@router.post(
    "/application", response_model=ConnectedAccountRead, status_code=status.HTTP_201_CREATED
)
async def connect_application_account(
    data: ConnectedApplicationAccount, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect an application credential the caller may use as a personal named account."""
    row = await service.connect_application_account(
        ctx,
        provider=data.provider,
        connection_id=data.connection_id,
        secret_id=data.secret_id,
        subject=data.subject,
        products=data.products,
        write=data.write,
        label=data.label,
        for_organization=False,
    )
    return ConnectedAccountRead.from_model(row)


@router.post(
    "/odoo",
    response_model=ConnectedAccountRead,
    status_code=status.HTTP_201_CREATED,
)
async def connect_odoo_account(
    data: ConnectedOdooAccount, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Validate an Odoo 19+ JSON-2 API key and seal its database connection."""
    row = await service.connect_odoo_account(
        ctx,
        credential=data.credential,
        connection_id=data.connection_id,
        label=data.label,
        write=data.write,
        for_organization=False,
    )
    return ConnectedAccountRead.from_model(row)
