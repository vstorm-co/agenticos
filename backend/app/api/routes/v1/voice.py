"""Voice conversations (#54): whether an agent can take a call, and the call's socket."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket

from app.api.deps import ActiveOrgWS, AgentRegistrySvc, Auth, CurrentUserWS, VoiceSettingsSvc
from app.core.permissions import Perm
from app.schemas.voice import VoiceReadinessRead
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
    return VoiceReadinessRead(**readiness.__dict__)


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
    caller = await socket_caller(user, organization, auth_token=websocket.state.auth_token)
    if caller is None:
        await websocket.close(code=4003, reason="Organization access denied")
        return
    await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
    await VoiceCallSession(websocket, caller).run()
