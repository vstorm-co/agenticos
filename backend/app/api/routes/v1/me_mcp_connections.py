"""User-scoped MCP server connections (Settings → Integrations).

Routes are nested under `/me/mcp-connections` because they always operate
on the current user - there's no cross-user view of these. The stored bearer
token never appears in any response (only `has_auth_token`).
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.agents.mcp_oauth import OAuthError
from app.api.deps import (
    CurrentUser,
    DBSession,
    McpConnectionSvc,
    OptionalCurrentUser,
    get_active_organization,
    get_auth_context,
    key_needs,
)
from app.api.public_api import PUBLIC
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.schemas.mcp_connection import (
    McpConnectionCreate,
    McpConnectionList,
    McpConnectionRead,
    McpConnectionTestResult,
    McpConnectionUpdate,
    McpOAuthCallback,
    McpOAuthCallbackResult,
    McpOAuthStart,
    McpOAuthStartResult,
    McpSignInProbe,
    McpSignInProbeResult,
    McpToolRead,
)
from app.services.mcp_connection import is_google_mcp

router = APIRouter()


@router.get(
    "",
    response_model=McpConnectionList,
    dependencies=[PUBLIC, Depends(key_needs(Perm.AGENTS_RUN))],
)
async def list_mcp_connections(service: McpConnectionSvc, user: CurrentUser) -> Any:
    """List the current user's MCP server connections.

    Public, the one route here that is: an agent suggesting what to connect
    reads what its person already has through the platform's MCP server (#2301).
    The tokens are never in it, and a key reads it only when issued for
    `agents:run`.
    """
    items, total = await service.list_for_user(user_id=user.id)
    return McpConnectionList(
        items=[McpConnectionRead.from_model(c) for c in items],
        total=total,
    )


@router.post("", response_model=McpConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_mcp_connection(
    data: McpConnectionCreate,
    service: McpConnectionSvc,
    user: CurrentUser,
) -> Any:
    """Add an MCP server connection. The URL is SSRF-validated."""
    db_connection = await service.create(user_id=user.id, data=data)
    return McpConnectionRead.from_model(db_connection)


@router.patch("/{connection_id}", response_model=McpConnectionRead)
async def update_mcp_connection(
    connection_id: UUID,
    data: McpConnectionUpdate,
    service: McpConnectionSvc,
    user: CurrentUser,
) -> Any:
    """Patch a connection. `auth_token: ""` clears the stored token."""
    db_connection = await service.update(user_id=user.id, connection_id=connection_id, data=data)
    return McpConnectionRead.from_model(db_connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_mcp_connection(
    connection_id: UUID,
    service: McpConnectionSvc,
    user: CurrentUser,
) -> Any:
    """Remove a connection."""
    await service.delete(user_id=user.id, connection_id=connection_id)
    return None


@router.post("/probe", response_model=McpSignInProbeResult)
async def probe_mcp_sign_in(
    data: McpSignInProbe, service: McpConnectionSvc, user: CurrentUser
) -> Any:
    """Whether a server added by its address supports OAuth sign-in (#2073).

    Runs the discovery a sign-in would, registering nothing. A server that answers
    with no OAuth metadata is `sign_in: false` - a token or no credential, then.
    """
    return await service.probe_sign_in(data.url)


@router.post("/oauth/start", response_model=McpOAuthStartResult)
async def start_mcp_oauth(
    data: McpOAuthStart,
    service: McpConnectionSvc,
    user: CurrentUser,
    request: Request,
    db: DBSession,
    x_organization_id: Annotated[UUID | None, Header()] = None,
) -> Any:
    """Begin the OAuth flow; returns the provider consent URL to redirect to.

    A Google-hosted server connects with the organization's Google client, so the
    caller's organization is needed then, and only then: a personal server does not
    need an active organization.
    """
    ctx: AuthContext | None = None
    if is_google_mcp(data.url):
        org = await get_active_organization(request, user, db, x_organization_id)
        ctx = await get_auth_context(request, user, org, db)
    try:
        authorization_url = await service.oauth_start(
            user_id=user.id,
            name=data.name,
            url=data.url,
            catalog_key=data.catalog_key,
            label=data.label,
            client_id=data.client_id,
            client_secret=data.client_secret,
            ctx=ctx,
        )
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.post("/oauth/callback", response_model=McpOAuthCallbackResult)
async def complete_mcp_oauth(
    data: McpOAuthCallback,
    service: McpConnectionSvc,
    user: OptionalCurrentUser,
) -> Any:
    """Finish the OAuth flow. Authenticated by the `state` token (no session),
    except connected accounts, which also require the initiating session and nonce."""
    try:
        connection = await service.oauth_callback(
            state=data.state,
            code=data.code,
            browser_nonce=data.browser_nonce,
            acting_user_id=user.id if user is not None else None,
        )
    except (OAuthError, NotFoundError) as exc:
        return McpOAuthCallbackResult(ok=False, error=str(exc))
    if connection.purpose == "account":
        # A connected account is named by its address and bound by a terminal's
        # mount, never added to an agent as a server - so no id to offer that with.
        return McpOAuthCallbackResult(ok=True, connection_name=connection.label or connection.name)
    return McpOAuthCallbackResult(
        ok=True,
        connection_name=connection.name,
        connection_id=connection.id,
        scope="org" if connection.scope == "org" else "user",
    )


@router.post(
    "/{connection_id}/test",
    response_model=McpConnectionTestResult,
    dependencies=[PUBLIC, Depends(key_needs(Perm.AGENTS_RUN))],
)
async def test_mcp_connection(
    connection_id: UUID,
    service: McpConnectionSvc,
    user: CurrentUser,
) -> Any:
    """Probe the server and return its tool list; persists last_status."""
    _connection, tools, error = await service.test(user_id=user.id, connection_id=connection_id)
    return McpConnectionTestResult(
        ok=error is None,
        error=error,
        tools=[McpToolRead.model_validate(t, from_attributes=True) for t in tools],
    )
