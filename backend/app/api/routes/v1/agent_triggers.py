"""When an agent runs itself - the Builder's "Schedules" for one agent.

Every route here acts on *one* agent, so none carries a `require(...)` gate. That
is the access layer's rule, not an oversight: a role gate cannot see the grants on
a row, so a Viewer holding an explicit run grant on a single agent would be refused
before `resolve_access` ever widened their access. The decision is handed to
`AgentTriggerService`, which reads the role scope *and* the grant through
`agents:run`, and reports a refusal as "not found" so agent ids stay unprobeable.
`tests/api/test_platform_routes.py` enforces both halves.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import AgentTriggerSvc, Auth
from app.schemas.agent_trigger import TriggerCreate, TriggerList, TriggerRead, TriggerUpdate

router = APIRouter()


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


@router.post("/{agent_id}/triggers/{trigger_id}/run", response_model=TriggerRead)
async def run_trigger_now(
    agent_id: UUID, trigger_id: UUID, ctx: Auth, service: AgentTriggerSvc
) -> Any:
    """Fire this schedule now, as its creator, without disturbing its cadence."""
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
