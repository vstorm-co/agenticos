"""The workflow-run WebSocket - lifecycle plumbing only (#1792).

Auth at the handshake, accept, the receive loop, and stopping the stream on
disconnect. What a frame does is `app.services.workflow_run_socket`.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import ActiveOrgWS, CurrentUserWS
from app.services.workflow_run_socket import WorkflowRunSocket

router = APIRouter()


@router.websocket("/ws/workflow-runs")
async def workflow_run_websocket(
    websocket: WebSocket, user: CurrentUserWS, organization: ActiveOrgWS
) -> None:
    # Echo the application subprotocol the handshake chose, as the agent socket does.
    await websocket.accept(subprotocol=getattr(websocket.state, "accept_subprotocol", None))
    session = WorkflowRunSocket(
        websocket,
        organization_id=organization.id,
        # Stashed by `get_current_user_ws`, so every frame and every read of the
        # stream re-checks the session the socket was opened with (#1437).
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
        await session.stop()
