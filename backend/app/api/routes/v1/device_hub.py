"""The desktop app's socket: the person's computer, reachable by their own runs (#2305)."""

from fastapi import APIRouter, WebSocket, WebSocketException

from app.api.deps import CurrentUserWS
from app.core.exceptions import AuthorizationError
from app.db.session import get_db_context
from app.services import device_hub

router = APIRouter()


@router.websocket("/ws/device")
async def device_socket(websocket: WebSocket, user: CurrentUserWS) -> None:
    """Connect this computer so the person's own runs can work on it.

    Authenticated like `/ws/agent`, with the desktop app's *own* session - the one
    it was paired with, labelled as a desktop app - never a browser tab's or an
    API key. The server sends `call` and `cancel` frames; the app answers each call
    with a `result` and opens with a `hello` saying what it can do. 4403 when the
    token is not a desktop app session of the caller's.
    """
    if websocket.state.api_key_caller is not None:
        raise WebSocketException(code=4403, reason="An API key is not a computer")
    async with get_db_context() as db:
        try:
            session_id, platform = await device_hub.admit(
                db, auth_token=websocket.state.auth_token, user_id=user.id
            )
        except AuthorizationError as exc:
            raise WebSocketException(code=4403, reason=exc.message) from None
    await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
    await device_hub.serve(websocket, user_id=user.id, session_id=session_id, platform=platform)
