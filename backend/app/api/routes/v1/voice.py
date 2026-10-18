"""Voice conversations (#54): whether an agent can take a call, the call's socket, its minutes."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket

from app.api.deps import (
    ActiveOrgWS,
    AgentRegistrySvc,
    Auth,
    CurrentUserWS,
    VoiceSettingsSvc,
    VoiceUsageSvc,
    require,
)
from app.core.permissions import Perm
from app.schemas.voice import VoiceReadinessRead, VoiceUsageRead
from app.services.api_key import KeyCaller
from app.services.voice import VoiceCallSession, socket_caller

router = APIRouter()


@router.get("/agents/{agent_id}/voice", response_model=VoiceReadinessRead)
async def voice_readiness(
    agent_id: UUID,
    registry: AgentRegistrySvc,
    voice: VoiceSettingsSvc,
    ctx: Auth,
    surface: Literal["web", "embed"] = Query(
        default="web",
        description=(
            "Where the call would come from: `web` for `/chat`, which the organization's "
            "chat switch also gates, or `embed` for a widget or hosted page, which the "
            "embed form reads before offering its voice switch"
        ),
    ),
) -> Any:
    """Whether a call to this agent would start, and why not.

    Anyone who may run the agent, a grant included; a 404 for one they may not.
    Per-resource, so no route gate: the registry decides (`resolve_access`).
    Read before the call button is offered, so nobody grants the microphone
    only to be refused.
    """
    agent = await registry.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
    readiness = await voice.readiness(
        organization_id=ctx.organization_id, agent=agent, surface=surface
    )
    return VoiceReadinessRead.model_validate(readiness)


@router.get(
    "/voice/usage",
    response_model=VoiceUsageRead,
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def voice_usage(
    service: VoiceUsageSvc,
    ctx: Auth,
    start: datetime = Query(description="Calls started at or after this instant"),
    end: datetime = Query(description="Calls started before this instant"),
) -> Any:
    """Call minutes over a window, by agent, and this month's against the organization's limit.

    Counted from the call rows the monthly limit reads, so the dashboard figure
    and the refusal at the limit agree. A reconnect is not a second call. An
    `end` not after `start` is refused with 422.
    """
    return VoiceUsageRead.model_validate(await service.usage(ctx, start=start, end=end))


@router.websocket("/ws/voice")
async def voice_websocket(
    websocket: WebSocket, user: CurrentUserWS, organization: ActiveOrgWS
) -> None:
    """A voice call (#54). Lifecycle only: auth, accept, hand over to `VoiceCallSession`.

    The same user and organization auth as `/ws/agent`, and a socket of its own
    because the agent socket's JSON turn loop does not fit a call. The token the
    handshake used is kept so every heartbeat can re-check it (#1437).
    """
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    # A call is a person at the microphone, as a chat turn is a person at the
    # keyboard: `socket_caller` rebuilds authority from the issuer's membership,
    # which would widen a key past the scopes it was issued with.
    if isinstance(getattr(websocket.state, "api_key_caller", None), KeyCaller):
        await websocket.close(code=4003, reason="API keys are not accepted on the voice socket")
        return
    caller = await socket_caller(user, organization, auth_token=websocket.state.auth_token)
    if caller is None:
        await websocket.close(code=4003, reason="Organization access denied")
        return
    await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
    await VoiceCallSession(websocket, caller).run()
