"""The public face of an embedded agent: config, widget, and a socket.

Three endpoints, all reachable without a session, all authorised by the same
thing — a public key plus the origin the browser reports. Nothing here reads a
cookie, and nothing here trusts a header the page could have set to anything.

Why a WebSocket rather than a POST per message: an agent turn takes seconds and
streams tokens the whole way. Over HTTP the customer's page has to poll or hold
an SSE connection open and reconnect it themselves; over a socket the browser
does that, and the same frames the dashboard chat already speaks work unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from app.api.deps import DBSession, EmbedSvc
from app.core.config import settings
from app.db.session import get_db_context
from app.schemas.agent_embed import PublicEmbedConfig
from app.services.agent_embed import AgentEmbedService, EmbedDenied
from app.services.embed_session import WIDGET_JS, EmbedSession

logger = logging.getLogger(__name__)

router = APIRouter()

# Close codes the widget reads. 4003 is deliberately the same for every refusal:
# a page that is not on the allow-list learns that it is not allowed, and
# nothing about whether a token would have helped.
WS_DENIED = 4003


@router.get("/{public_key}/config", response_model=PublicEmbedConfig)
async def embed_config(
    public_key: str,
    service: EmbedSvc,
    response: Response,
    origin: str | None = Header(default=None),
) -> Any:
    """What the widget renders itself from.

    Answers with the CORS header for the calling origin only when that origin is
    on the widget's list — a wildcard here would let any site read the config
    and, more to the point, would make the allow-list decorative.
    """
    try:
        embed, _ = await service.admit(public_key, origin=origin, token=None)
    except EmbedDenied:
        raise HTTPException(status_code=403, detail="This widget is not available here") from None

    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return await service.public_config(embed)


@router.get("/{public_key}/widget.js", response_class=Response)
async def embed_widget(public_key: str, db: DBSession) -> Response:
    """The script a customer pastes into their page.

    Served from the API rather than a CDN so a self-hosted deployment needs no
    second host, and so the script always matches the server it talks to. It is
    handed out to anyone who asks: it contains no secret, and the origin check
    happens when it opens a socket, not when it is downloaded.
    """
    service = AgentEmbedService(db)
    embed = await service.find_public(public_key)
    if embed is None or not embed.is_active:
        # 404 for a key nobody recognises: this is a script tag, and an HTML
        # error page in a `<script>` is a syntax error in somebody's console.
        raise HTTPException(status_code=404, detail="Unknown widget")

    body = WIDGET_JS.replace("__PUBLIC_KEY__", embed.public_key).replace(
        "__BASE_URL__", settings.PUBLIC_BASE_URL.rstrip("/")
    )
    return Response(
        content=body,
        media_type="application/javascript; charset=utf-8",
        headers={
            # Short, because the theme is edited in the Builder and a day-long
            # cache would make a colour change look like it did not save.
            "Cache-Control": "public, max-age=300",
        },
    )


@router.websocket("/{public_key}/ws")
async def embed_socket(
    websocket: WebSocket,
    public_key: str,
    token: str | None = Query(default=None),
) -> None:
    """One visitor's conversation with an embedded agent.

    The token arrives as a query parameter because browsers cannot set headers
    on a WebSocket handshake. It is the customer's own signed token, not ours,
    and it never leaves this process.
    """
    origin = websocket.headers.get("origin")

    async with get_db_context() as db:
        service = AgentEmbedService(db)
        try:
            embed, visitor = await service.admit(public_key, origin=origin, token=token)
        except EmbedDenied:
            # Accepted first, then closed with a code: a handshake rejected
            # outright gives the browser no way to tell "refused" from "server
            # is down", and the widget would retry forever.
            await websocket.accept()
            await websocket.close(code=WS_DENIED, reason="This widget is not available here")
            return

        session = EmbedSession(db=db, embed=embed, visitor=visitor, websocket=websocket)
        await websocket.accept()
        try:
            await session.greet()
            while True:
                frame = await websocket.receive_json()
                await session.handle(frame)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("embed_session_failed", extra={"embed_id": str(embed.id)})
            await session.fail("Something went wrong. Please try again.")
        finally:
            await session.close()
