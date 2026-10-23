"""A browse's live view (#2128): watch an agent's browser, and take it over."""

from fastapi import APIRouter, WebSocket

from app.api.deps import CurrentUserWS
from app.services import live_browse

router = APIRouter()


@router.websocket("/ws/browse/{run_id}/{call_id}")
async def browse_live(
    websocket: WebSocket,
    run_id: str,
    call_id: str,
    _user: CurrentUserWS,
) -> None:
    """Stream one browse to a viewer, and take their commands.

    Authenticated like `/ws/agent`: the token in the `access_token.<token>`
    subprotocol. Which organization the browse is in comes from the browse, and the
    viewer must belong to it and be allowed to watch - the person the run acts for,
    someone who may edit the agent, or someone who may view runs; only the first
    two may take the browser over.

    The server sends a `browser_snapshot` first - the task, what the browse has
    done and its latest picture - then every frame as it happens. The client
    sends `BrowserCommand`s: `take_over`, `give_back`, and while it holds the
    browser, `click`, `type`, `key` and `scroll`. Closes with 4404 for a browse that
    has ended more than an hour ago or never existed, and 4403 for a viewer who may
    not watch it.
    """
    await websocket.accept(subprotocol=websocket.state.accept_subprotocol)
    await live_browse.stream(
        websocket, auth_token=websocket.state.auth_token, run_id=run_id, call_id=call_id
    )
