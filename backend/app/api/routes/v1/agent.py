# Route is lifecycle plumbing only - auth, accept, dispatch loop, disconnect.
# Per-turn orchestration lives in app.services.agent_session.AgentSession.
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import ActiveOrgWS, CurrentUserWS
from app.services.agent import AgentConnectionManager
from app.services.agent_session import AgentSession
from app.services.api_key import KeyCaller

logger = logging.getLogger(__name__)

router = APIRouter()

manager = AgentConnectionManager()


@router.websocket("/ws/agent")
async def agent_websocket(
    websocket: WebSocket,
    user: CurrentUserWS,
    organization: ActiveOrgWS,
) -> None:
    if user is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return
    # The console's own socket. A run here is a person at the keyboard - their
    # personal connections, no per-key limit - which a key is not; integrations
    # run agents over `POST /agents/{id}/run` instead.
    if isinstance(getattr(websocket.state, "api_key_caller", None), KeyCaller):
        await websocket.close(code=4003, reason="API keys are not accepted on the chat socket")
        return

    await manager.connect(websocket)
    session = AgentSession(
        websocket,
        user,
        organization,
        # Stashed by `get_current_user_ws`, so the session can re-check it on
        # every frame and close a socket whose session was revoked (#1437).
        auth_token=websocket.state.auth_token,
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            await session.handle_frame(data)
    finally:
        # Bookkeeping first, and `session.shutdown()` second, because that one
        # now waits: a turn whose reader has gone is given time to finish and
        # write its answer down (`AgentSession.shutdown`). The connection is
        # already gone by then, so counting it as live for the length of the
        # grace would only misreport it.
        manager.disconnect(websocket)
        await session.shutdown()
