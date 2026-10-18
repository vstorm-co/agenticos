"""The console's live-update socket (#2061): changes made elsewhere, as they commit."""

from fastapi import APIRouter, WebSocket

from app.api.deps import ActiveOrgWS
from app.services import change_feed

router = APIRouter()


@router.websocket("/ws/events")
async def change_events(
    websocket: WebSocket,
    organization: ActiveOrgWS,
) -> None:
    """Stream the active organization's changes that this caller may see.

    Authenticated like `/ws/agent`: the token in the `access_token.<token>`
    subprotocol, the organization in `?organization_id=`. The server only sends;
    each frame is one `ChangeEvent` as JSON.
    """
    await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
    await change_feed.stream_changes(
        websocket, organization_id=organization.id, auth_token=websocket.state.auth_token
    )
