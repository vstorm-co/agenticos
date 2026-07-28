# Route is lifecycle plumbing only — auth, accept, dispatch loop, disconnect.
# Per-turn orchestration lives in app.services.agent_session.AgentSession.
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import ActiveOrgWS, CurrentUserWS
from app.services.agent import AgentConnectionManager
from app.services.agent_session import AgentSession

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

    await manager.connect(websocket)
    session = AgentSession(
        websocket,
        user,
        organization,
    )

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            await session.handle_frame(data)
    finally:
        await session.shutdown()
        manager.disconnect(websocket)
