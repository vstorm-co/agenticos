"""Consenting to an MCP client, and disconnecting one (#2059).

The OAuth endpoints a client talks to are the MCP SDK's, served beside `/mcp`.
These are the console's half: the page a person lands on from `/authorize`, and
the list of applications they have connected. Session-only, like key management:
a token must not be able to approve or revoke the grants tokens come from.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, OAuthServerSvc
from app.schemas.oauth_server import (
    OAuthConsentAnswer,
    OAuthConsentApprove,
    OAuthConsentRead,
    OAuthGrantList,
)

router = APIRouter()


@router.get("/requests/{request_id}", response_model=OAuthConsentRead)
async def read_consent_request(request_id: UUID, service: OAuthServerSvc, ctx: Auth) -> Any:
    """What an application is asking for, in the caller's active organization."""
    return await service.describe(ctx, request_id)


@router.post("/requests/{request_id}/approve", response_model=OAuthConsentAnswer)
async def approve_consent_request(
    request_id: UUID, data: OAuthConsentApprove, service: OAuthServerSvc, ctx: Auth
) -> Any:
    """Let the application act as the caller, within the chosen permissions."""
    return await service.approve(ctx, request_id, data.scopes)


@router.post("/requests/{request_id}/deny", response_model=OAuthConsentAnswer)
async def deny_consent_request(request_id: UUID, service: OAuthServerSvc, ctx: Auth) -> Any:
    """Turn the application away; it is told `access_denied`."""
    return await service.deny(request_id)


@router.get("/grants", response_model=OAuthGrantList)
async def list_connected_applications(service: OAuthServerSvc, ctx: Auth) -> Any:
    """Applications connected as the caller - everybody's, with `api_keys:manage`."""
    return await service.list_grants(ctx)


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def disconnect_application(grant_id: UUID, service: OAuthServerSvc, ctx: Auth) -> None:
    """Revoke an application's access and every token it holds, at once."""
    await service.disconnect(ctx, grant_id)
