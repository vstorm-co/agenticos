"""Where an agent is available - the Builder's "Where this agent is available".

Every route here acts on *one* agent, so none of them carries a `require(...)`
gate. That is the rule the access layer is built on rather than an oversight: a
role gate cannot see the grants on a row, so a Viewer holding an explicit edit
grant on a single agent would be refused before `resolve_access` ever widened
their access. The decision is handed to `AgentExposureService`, which reads the
role scope *and* the grant, and reports a refusal as "not found" so agent ids
stay unprobeable. `tests/api/test_platform_routes.py` enforces both halves.

One surface concept covers every place an agent can be reached, so the Builder
gets one section rather than one per channel.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.deps import AgentExposureSvc, Auth, ChannelBindingRequestSvc
from app.schemas.agent_exposure import (
    ExposureCreate,
    ExposureList,
    ExposureRead,
    ExposureTargetList,
    ExposureUpdate,
)
from app.schemas.channel_binding_request import (
    BindingDeferred,
    ChannelBindingRequestList,
)

router = APIRouter()

_REQUESTED = (
    "The bot answers people with no account and the caller does not manage channels: a "
    "request was filed instead, and nothing is applied until it is decided"
)


def _requested(deferred: BindingDeferred) -> JSONResponse:  # routes-helper: the 202 body
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=jsonable_encoder(deferred))


@router.get("/{agent_id}/exposures", response_model=ExposureList)
async def list_exposures(agent_id: UUID, ctx: Auth, service: AgentExposureSvc) -> Any:
    """Every place this agent answers."""
    items = await service.list_for_agent(ctx, agent_id)
    return ExposureList(items=items, total=len(items))


@router.get("/{agent_id}/exposures/targets", response_model=ExposureTargetList)
async def list_exposure_targets(agent_id: UUID, ctx: Auth, service: AgentExposureSvc) -> Any:
    """The bots this agent could be made available on.

    Declared before the `{exposure_id}` routes so `targets` is not parsed as
    an id. FastAPI matches in declaration order, and the two would otherwise
    collide on a path that has no valid UUID to offer.
    """
    items = await service.targets(ctx, agent_id)
    return ExposureTargetList(items=items, total=len(items))


@router.get("/{agent_id}/binding-requests", response_model=ChannelBindingRequestList)
async def list_binding_requests(
    agent_id: UUID, ctx: Auth, service: ChannelBindingRequestSvc
) -> Any:
    """The pending requests to bind this agent to a bot that answers people with no account.

    Whoever manages channels sees them all; anyone else who may see the agent sees their own.
    """
    items = await service.list_for_agent(ctx, agent_id)
    return ChannelBindingRequestList(
        items=items, total=len(items)
    )


@router.post(
    "/{agent_id}/exposures",
    response_model=ExposureRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_202_ACCEPTED: {"model": BindingDeferred, "description": _REQUESTED}},
)
async def create_exposure(
    agent_id: UUID, data: ExposureCreate, ctx: Auth, service: AgentExposureSvc
) -> Any:
    """Make this agent available in one more place."""
    created = await service.create(ctx, agent_id, data)
    if isinstance(created, BindingDeferred):
        return _requested(created)
    # Re-read through the listing so the response carries the bot's name, the
    # same shape the section renders. Returning the bare row would make the
    # client hold two representations of one thing.
    exposures = await service.list_for_agent(ctx, agent_id)
    return next(
        exposure for exposure in exposures if exposure.channel_bot_id == data.channel_bot_id
    )


@router.patch(
    "/{agent_id}/exposures/{exposure_id}",
    response_model=ExposureRead,
    responses={status.HTTP_202_ACCEPTED: {"model": BindingDeferred, "description": _REQUESTED}},
)
async def update_exposure(
    agent_id: UUID,
    exposure_id: UUID,
    data: ExposureUpdate,
    ctx: Auth,
    service: AgentExposureSvc,
) -> Any:
    """Pause, resume, rebind, or change what the agent may look up here."""
    updated = await service.update(ctx, agent_id, exposure_id, data)
    if isinstance(updated, BindingDeferred):
        return _requested(updated)
    exposures = await service.list_for_agent(ctx, agent_id)
    return next(exposure for exposure in exposures if exposure.id == updated.id)


@router.delete("/{agent_id}/exposures/{exposure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exposure(
    agent_id: UUID, exposure_id: UUID, ctx: Auth, service: AgentExposureSvc
) -> Response:
    """Stop this agent answering there, and forget the binding."""
    await service.delete(ctx, agent_id, exposure_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
