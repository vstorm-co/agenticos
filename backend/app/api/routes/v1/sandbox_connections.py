"""Where an organization's sandboxes run.

Gated on `connections:manage`, the same permission the vault and the MCP
connections carry, and for the same reason: whoever edits these decides which
host an agent's shell runs on, and the credential behind it can start containers
there.

The listing and the policy are separate calls on purpose. A listing is cheap and
local; a policy is a round trip to a service that may be down, and folding it
into the list would make one unreachable host hide every other connection an
operator has.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, SandboxConnectionSvc, require
from app.core.permissions import Perm
from app.schemas.sandbox_connection import (
    SandboxConnectionCreate,
    SandboxConnectionList,
    SandboxConnectionRead,
    SandboxConnectionUpdate,
    SandboxEventList,
    SandboxPolicyRead,
    SandboxSessionList,
)

router = APIRouter()


@router.get(
    "",
    response_model=SandboxConnectionList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_connections(service: SandboxConnectionSvc, ctx: Auth) -> Any:
    """Every place this organization's agents may be given a workspace."""
    items = await service.list_connections(ctx)
    return SandboxConnectionList(items=items, total=len(items))


@router.post(
    "",
    response_model=SandboxConnectionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def create_connection(
    data: SandboxConnectionCreate, service: SandboxConnectionSvc, ctx: Auth
) -> Any:
    """Register one. The first an organization registers becomes its default."""
    return await service.create(ctx, data)


@router.patch(
    "/{connection_id}",
    response_model=SandboxConnectionRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def update_connection(
    connection_id: UUID,
    data: SandboxConnectionUpdate,
    service: SandboxConnectionSvc,
    ctx: Auth,
) -> Any:
    return await service.update(ctx, connection_id, data)


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def delete_connection(connection_id: UUID, service: SandboxConnectionSvc, ctx: Auth) -> None:
    """Forget a host. The workspaces keyed to it keep their rows, which are what
    record where an agent did its work."""
    await service.delete(ctx, connection_id)


@router.get(
    "/{connection_id}/policy",
    response_model=SandboxPolicyRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def read_policy(connection_id: UUID, service: SandboxConnectionSvc, ctx: Auth) -> Any:
    """What the service allows, asked of the service.

    This is the only way to see the ceilings in force: they are the service's own
    boot configuration and there is deliberately no endpoint to write them - a
    browser that could reconfigure the process holding the Docker socket would
    own the host.

    Proxied rather than fetched by the client, because reaching the service needs
    a token that must never be in a browser.
    """
    return await service.policy(ctx, connection_id)


@router.get(
    "/{connection_id}/sessions",
    response_model=SandboxSessionList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def list_sessions(
    connection_id: UUID,
    service: SandboxConnectionSvc,
    ctx: Auth,
    usage: bool = Query(False, description="Also sample memory and CPU per sandbox"),
) -> Any:
    """The sandboxes this organization has open on that host.

    Filtered rather than forwarded. One service answers for every organization
    that registered a connection at its address, so passing its response through
    would show one tenant another tenant's containers.

    `usage` is off by default because the service pays a daemon round trip per
    sandbox to sample it, which is not what a page that lists twenty of them
    should cost on load.
    """
    return await service.sessions(ctx, connection_id, usage=usage)


@router.get(
    "/{connection_id}/sessions/{session_id}/events",
    response_model=SandboxEventList,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def read_session_events(
    connection_id: UUID,
    session_id: str,
    service: SandboxConnectionSvc,
    ctx: Auth,
    after: int = Query(0, ge=0, description="Only entries newer than this sequence number"),
) -> Any:
    """What has been done to one sandbox: paths read, commands run, how each went.

    Refused as "not found" when the session belongs to another organization. The
    log carries no file contents and no command output by design, but the list of
    paths and commands is still a description of somebody's work.
    """
    return await service.session_events(ctx, connection_id, session_id, after=after)
