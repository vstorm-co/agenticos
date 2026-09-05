"""The organization's MCP servers - the ones an agent may be built on.

Distinct from `/me/mcp-connections`, which is a person's own. A connection
here belongs to the organization, is gated on `mcp:manage`, and is the
only kind an agent spec can bind: a published agent whose reach depended on
whose session ran it would be neither reviewable nor reproducible.

Every route carries a `require(...)` gate, per-resource ones included. That is
not a break with the rule those gates follow elsewhere - it is the same rule.
A gate is wrong on a route whose answer a resource grant could widen, because a
role check cannot see the grant; an MCP connection has no grants and no owner to
share it with, so `mcp:manage` is the whole of the decision. The
provider-credential routes next door are gated the same way for the same reason.

The credential is write-only, like a provider key: it goes in, it is sealed for
this organization, and nothing here ever returns it.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.mcp_oauth import OAuthError
from app.api.deps import Auth, McpConnectionSvc, require
from app.core.permissions import Perm
from app.schemas.mcp_connection import (
    GithubOAuthStart,
    McpConnectionRead,
    McpConnectionTestResult,
    McpOAuthStart,
    McpOAuthStartResult,
    McpToolRead,
    OrgMcpConnectionCreate,
    OrgMcpConnectionList,
    OrgMcpConnectionUpdate,
)

router = APIRouter()


@router.get(
    "",
    response_model=OrgMcpConnectionList,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def list_org_mcp_connections(service: McpConnectionSvc, ctx: Auth) -> Any:
    """The MCP servers this organization has connected."""
    items, total = await service.list_for_org(ctx)
    return OrgMcpConnectionList(
        items=[McpConnectionRead.from_model(c) for c in items],
        total=total,
    )


@router.post(
    "",
    response_model=McpConnectionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def create_org_mcp_connection(
    data: OrgMcpConnectionCreate, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Connect a server for the whole organization. The URL is SSRF-validated."""
    connection = await service.create_for_org(ctx, data)
    return McpConnectionRead.from_model(connection)


@router.post(
    "/oauth/start",
    response_model=McpOAuthStartResult,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def start_org_mcp_oauth(data: McpOAuthStart, service: McpConnectionSvc, ctx: Auth) -> Any:
    """Begin the OAuth flow for a server the organization will own.

    Somebody consents, and the connection that comes back belongs to the
    organization - which is what a shared service account is for. The grant is
    still theirs at the provider, so revoking their access there stops the
    organization's server working until it is authorized again. An organization
    that wants this should consent with an account it controls.

    Declared above `/{connection_id}` because that route parses its segment as
    a UUID and would answer this path with a 422 instead.
    """
    try:
        authorization_url = await service.oauth_start_for_org(
            ctx, name=data.name, url=data.url, catalog_key=data.catalog_key
        )
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.post(
    "/oauth/start/github",
    response_model=McpOAuthStartResult,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def start_org_github_oauth(
    data: GithubOAuthStart, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Begin the GitHub OAuth App flow for a trigger portal, using the org's own creds.

    GitHub does not support the discovery-and-registration flow the sibling
    `/oauth/start` runs. This one instead reads the organization's stored
    `github_oauth_app` secret, builds GitHub's consent URL for the portal's scopes
    (`repo` to see events, `admin:repo_hook` to register the webhook), and stages the
    flow on the organization's connection - keyed to the portal's MCP catalog entry
    so the trigger and the agent's tools share one connected account.

    A `github_oauth_app` secret that has not been added yet is a `NotFoundError`
    (404) the UI shows as a prerequisite, and a portal that does not connect through
    GitHub is a `BadRequestError` (400); both are the platform's domain exceptions,
    so no `OAuthError` translation is needed here.
    """
    authorization_url = await service.oauth_start_for_org_github(ctx, portal_key=data.portal_key)
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.post(
    "/oauth/start/portal",
    response_model=McpOAuthStartResult,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def start_org_polled_portal_oauth(
    data: GithubOAuthStart, service: McpConnectionSvc, ctx: Auth
) -> Any:
    """Begin the consent flow for a portal the platform polls rather than is posted to.

    Gmail is the case: nothing registers a webhook, so the flow's only job is a
    refreshable token carrying the portal's read scopes. It uses the deployment's
    own Google client rather than a per-organization OAuth App - see
    `google_oauth`'s docstring for why - so a deployment with none configured is a
    `NotFoundError` (404) the card shows as a prerequisite, and a portal that is
    not polled is a `BadRequestError` (400).

    Same body as its GitHub sibling (a portal key) and the same
    `mcp:manage` gate: connecting an account for the whole organization is the
    permission that route already demands.
    """
    authorization_url = await service.oauth_start_for_polled_portal(ctx, portal_key=data.portal_key)
    return McpOAuthStartResult(authorization_url=authorization_url)


@router.patch(
    "/{connection_id}",
    response_model=McpConnectionRead,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def update_org_mcp_connection(
    connection_id: UUID,
    data: OrgMcpConnectionUpdate,
    service: McpConnectionSvc,
    ctx: Auth,
) -> Any:
    """Patch a connection. `auth_token: ""` clears the stored credential."""
    connection = await service.update_for_org(ctx, connection_id=connection_id, data=data)
    return McpConnectionRead.from_model(connection)


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def delete_org_mcp_connection(
    connection_id: UUID, service: McpConnectionSvc, ctx: Auth
) -> None:
    """Remove a connection. Agents still naming it lose that server, not the run."""
    await service.delete_for_org(ctx, connection_id=connection_id)


@router.post(
    "/{connection_id}/test",
    response_model=McpConnectionTestResult,
    dependencies=[Depends(require(Perm.MCP_MANAGE))],
)
async def test_org_mcp_connection(connection_id: UUID, service: McpConnectionSvc, ctx: Auth) -> Any:
    """Probe the server and return the tools it offers; persists `last_status`."""
    _connection, tools, error = await service.test_for_org(ctx, connection_id=connection_id)
    return McpConnectionTestResult(
        ok=error is None,
        error=error,
        tools=[McpToolRead(name=t.name, description=t.description) for t in tools],
    )
