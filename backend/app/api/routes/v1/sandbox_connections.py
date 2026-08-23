"""Where an organization's sandboxes run.

Two gates, and which one a route carries is the difference between watching a
host and owning it. Writing here decides which host an agent's shell runs on and
attaches the credential that can start containers there, so it is
`connections:manage` - the same permission the vault and the MCP connections
carry, and for the same reason. Reading is `connections:view`: a session list, an
activity log and the ceilings a service enforces are what somebody looks at when
an agent keeps hitting a memory limit, and that is an operator's question. Under
one permission the only way to answer it was to hand out create, edit and delete
as well.

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
    SandboxLocalCredentialRead,
    SandboxLocalServiceRead,
    SandboxOperationList,
    SandboxPolicyRead,
    SandboxProbeRequest,
    SandboxRuntimeCatalog,
    SandboxSessionList,
)

router = APIRouter()


@router.get(
    "",
    response_model=SandboxConnectionList,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
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


@router.get(
    "/local",
    response_model=SandboxLocalServiceRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def read_local_service(service: SandboxConnectionSvc, ctx: Auth) -> Any:
    """Whether this deployment is already running a sandbox service of its own.

    Declared before `/{connection_id}` so `local` is not read as an id.

    A prefill, not a decision: an operator registering the service their own
    `make dev` started should not have to know that it answers at
    `http://sandboxd:8080` and that the token is in `backend/.env`. Nothing is
    changed by asking, and a deployment running no sandbox service gets `url: null`
    and a form exactly as it was.
    """
    return await service.local_service(ctx)


@router.post(
    "/local/credential",
    response_model=SandboxLocalCredentialRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def store_local_credential(service: SandboxConnectionSvc, ctx: Auth) -> Any:
    """Store this deployment's own service token in the vault, and name its id.

    A POST because it writes a vault entry. The value comes from this process's
    environment and never from the request, which is the point - it is already
    here, and a form that asked for it was asking somebody to go and copy a secret
    out of a file.
    """
    return await service.store_local_credential(ctx)


@router.get(
    "/runtimes",
    response_model=SandboxRuntimeCatalog,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def list_runtimes(service: SandboxConnectionSvc, ctx: Auth) -> Any:
    """Every runtime the sandbox library ships.

    Declared before `/{connection_id}` so `runtimes` is not read as an id.

    Static, and answered without contacting anything: this is the catalog a
    `sandboxd` is built from, which is what lets the connection form offer a
    populated select before an address or a key exists. What a *particular* service
    permits is narrower and only that service can say - `POST /probe` and
    `GET /{id}/policy` are the two ways to ask it.
    """
    runtimes = service.runtime_catalog()
    return SandboxRuntimeCatalog(items=runtimes, total=len(runtimes))


@router.post(
    "/probe",
    response_model=SandboxPolicyRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def probe_service(data: SandboxProbeRequest, service: SandboxConnectionSvc, ctx: Auth) -> Any:
    """Test an address and a key, and read what that service allows.

    The same read as `/{id}/policy`, one step earlier: a form has an address and a
    vault entry but no row yet, and this is what makes `Default runtime` a list of
    aliases the service will accept rather than free text where a typo is stored
    happily and refused at the first tool call.

    A POST despite being a read. The address and the key are the input, a query
    string is where URLs end up in access logs, and `secret_id` in one is a
    reference to a credential that opens a host.
    """
    return await service.probe_policy(ctx, data)


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
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
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
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
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
    "/operations",
    response_model=SandboxOperationList,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def read_sandbox_operations(
    service: SandboxConnectionSvc,
    ctx: Auth,
    session_key: str | None = Query(None, description="Narrow to one sandbox session"),
    op: str | None = Query(None, description="Narrow to one operation"),
    failed_only: bool = Query(False, description="Only operations that did not succeed"),
    query: str | None = Query(None, max_length=200, description="Substring of the op or target"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """This organization's record of what its agents did in their sandboxes.

    Read from our own table, so it answers a week later and after a `sandboxd`
    restart - which the service's own 200-entry buffer never could (#1061). The
    filters narrow a query rather than an array the client holds, and the total is
    what makes the pager honest.

    Not under a connection: an operation is recorded against the *session* the
    agent worked in, and a sandbox outlives the connection row it was opened
    through - a log that could only be read per connection would lose the record
    the moment somebody deleted the host.
    """
    return await service.operations(
        ctx,
        session_key=session_key,
        op=op,
        failed_only=failed_only,
        query=query,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{connection_id}/sessions/{session_id}/events",
    response_model=SandboxEventList,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
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
