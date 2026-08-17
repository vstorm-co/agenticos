"""When an agent runs itself - the Builder's "Schedules" for one agent.

Almost every route here acts on *one* agent, so it carries no `require(...)` gate.
That is the access layer's rule, not an oversight: a role gate cannot see the grants
on a row, so a Viewer holding an explicit run grant on a single agent would be
refused before `resolve_access` ever widened their access. The decision is handed to
`AgentTriggerService`, which reads the role scope *and* the grant through
`agents:run`, and reports a refusal as "not found" so agent ids stay unprobeable.

The one exception is the org-wide listing on `org_router` (`GET /triggers`): a
collection route with no single resource whose grants could widen the answer, so it
carries `require(agents:view)` as its coarse first door, exactly as `GET /agents`
and the org-wide `GET /runs` do. The per-agent visibility filtering still happens in
the service. `tests/api/test_platform_routes.py` enforces both halves.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import AgentTriggerSvc, Auth, require
from app.core.permissions import Perm
from app.schemas.agent_trigger import TriggerCreate, TriggerList, TriggerRead, TriggerUpdate
from app.schemas.portal import (
    PortalCatalog,
    PortalPresetRead,
    PortalRead,
    PortalTargetList,
    PortalTargetRead,
)
from app.services import portal_catalog

router = APIRouter()

# A second router, mounted without the `/agents` prefix, for the one trigger view
# that is not about a single agent: every schedule and trigger in the
# organization. It cannot live on `router` - `/agents/triggers` would be shadowed
# by `/agents/{agent_id}` from the registry, which is registered first - so it is
# its own top-level `/triggers`, the same shape as the org-wide `/runs` listing.
org_router = APIRouter()


@org_router.get(
    "/trigger-portals",
    response_model=PortalCatalog,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_trigger_portals() -> Any:
    """The services a trigger can be built on, each with its ready-made presets.

    Hand-curated data, gated like `GET /triggers` and `GET /mcp-catalog` on the
    coarse `agents:view` first door - browsing what can be set up, not acting on
    one agent. The scopes a portal registers with are deliberately not exposed.
    """
    items = [
        PortalRead(
            key=portal.key,
            name=portal.name,
            description=portal.description,
            category=portal.category,
            icon=portal.icon or None,
            event_source=portal.event_source,
            delivery=portal.delivery.value,
            target_kind=portal.target_kind,
            connection_catalog_key=portal.mcp_catalog_key,
            presets=[
                PortalPresetRead(
                    key=preset.key,
                    label=preset.label,
                    description=preset.description,
                    target_required=preset.target_required,
                )
                for preset in portal.presets
            ],
        )
        for portal in portal_catalog.CATALOG
    ]
    return PortalCatalog(items=items, total=len(items))


@org_router.get(
    "/trigger-portals/{portal_key}/targets",
    response_model=PortalTargetList,
    dependencies=[Depends(require(Perm.AGENTS_RUN))],
)
async def list_portal_targets(
    portal_key: str,
    ctx: Auth,
    service: AgentTriggerSvc,
    connection_id: UUID = Query(..., description="The connected account to enumerate targets from"),
) -> Any:
    """The repositories (or channels) a portal's preset can point at.

    Gated on `agents:run`, not the catalog's `agents:view`: enumerating an
    account's repositories through its token is part of building a trigger, not
    browsing what exists. An empty list is a legitimate answer - a portal that
    registers no webhooks, or a connection that cannot be read - and the picker
    falls back to a free-text target.
    """
    targets = await service.list_portal_targets(ctx, portal_key, connection_id)
    items = [PortalTargetRead(id=target.id, label=target.label) for target in targets]
    return PortalTargetList(items=items, total=len(items))


@org_router.get(
    "/triggers", response_model=TriggerList, dependencies=[Depends(require(Perm.AGENTS_VIEW))]
)
async def list_org_triggers(
    ctx: Auth,
    service: AgentTriggerSvc,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """Every schedule and trigger in the organization the caller may see."""
    items, total = await service.list_for_organization(ctx, skip=skip, limit=limit)
    return TriggerList(items=items, total=total)


@router.get("/{agent_id}/triggers", response_model=TriggerList)
async def list_triggers(agent_id: UUID, ctx: Auth, service: AgentTriggerSvc) -> Any:
    """Every schedule on this agent."""
    items = await service.list_for_agent(ctx, agent_id)
    return TriggerList(items=items, total=len(items))


@router.post(
    "/{agent_id}/triggers", response_model=TriggerRead, status_code=status.HTTP_201_CREATED
)
async def create_trigger(
    agent_id: UUID, data: TriggerCreate, ctx: Auth, service: AgentTriggerSvc
) -> Any:
    """Schedule this agent to run itself."""
    return await service.create(ctx, agent_id, data)


@router.post(
    "/{agent_id}/triggers/{trigger_id}/run",
    response_model=TriggerRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_trigger_now(
    agent_id: UUID, trigger_id: UUID, ctx: Auth, service: AgentTriggerSvc
) -> Any:
    """Accept one extra fire of this schedule, as its creator, cadence untouched.

    202, not 200: the fire is dispatched once this request commits rather than run
    inside it, so the trigger comes back as it stands and its `last_run_id` still
    names the previous run (#658).
    """
    return await service.run_now(ctx, agent_id, trigger_id)


@router.patch("/{agent_id}/triggers/{trigger_id}", response_model=TriggerRead)
async def update_trigger(
    agent_id: UUID,
    trigger_id: UUID,
    data: TriggerUpdate,
    ctx: Auth,
    service: AgentTriggerSvc,
) -> Any:
    """Pause, resume, retime, repoint, or reword a schedule."""
    return await service.update(ctx, agent_id, trigger_id, data)


@router.delete("/{agent_id}/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(
    agent_id: UUID, trigger_id: UUID, ctx: Auth, service: AgentTriggerSvc
) -> Response:
    """Remove a schedule entirely - the agent stops running itself."""
    await service.delete(ctx, agent_id, trigger_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
