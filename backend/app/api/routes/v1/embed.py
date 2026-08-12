"""The public face of an embedded agent: config, widget, and a socket.

Three endpoints, all reachable without a session, all authorised by the same
thing - a public key plus the origin the browser reports. Nothing here reads a
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
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse

from app.api.deps import DBSession, EmbedSvc
from app.core.config import settings
from app.db.session import get_db_context
from app.schemas.agent_embed import PublicEmbedConfig, PublicHostedConfig
from app.services import rate_limit
from app.services.agent_embed import AgentEmbedService, EmbedDenied
from app.services.embed_session import WIDGET_JS, EmbedSession

logger = logging.getLogger(__name__)

router = APIRouter()

# Close codes the widget reads. 4003 is deliberately the same for every refusal:
# a page that is not on the allow-list learns that it is not allowed, and
# nothing about whether a token would have helped.
WS_DENIED = 4003

# Not folded into 4003. "You are not allowed here" and "you are allowed here but
# arriving too fast" ask a client for opposite things - stop for ever, and retry
# later - so a client that cannot tell them apart either hammers a refusal or
# gives up on a limit.
WS_TOO_MANY = 4029


@router.get("/{public_key}/config", response_model=PublicEmbedConfig)
async def embed_config(
    public_key: str,
    service: EmbedSvc,
    request: Request,
    response: Response,
    origin: str | None = Header(default=None),
) -> Any:
    """What the widget renders itself from.

    Answers with the CORS header for the calling origin only when that origin is
    on the widget's list - a wildcard here would let any site read the config
    and, more to the point, would make the allow-list decorative.
    """
    if not await rate_limit.embed_admission_allowed(request):
        raise HTTPException(status_code=429, detail="Too many requests")

    try:
        admission = await service.admit(public_key, origin=origin, token=None)
    except EmbedDenied:
        raise HTTPException(status_code=403, detail="This widget is not available here") from None

    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return await service.public_config(admission.embed)


@router.get("/{public_key}/hosted", response_model=PublicHostedConfig)
async def hosted_config(public_key: str, service: EmbedSvc) -> Any:
    """What a page of our own renders itself from.

    No origin check, unlike every other route here, and that is the stance rather
    than an oversight: an allow-list is a rule about *other people's* sites, and
    this page is ours. What protects a hosted link in `public` mode is the key's
    unguessability, the embed's rate bucket, its budget and its pause switch -
    nothing else, which is why it is said in `docs/channels.md` too.

    404 rather than 403 when hosting is off, for the same reason the widget script
    does: a key that names nothing and a key whose page is not published are the
    same amount of information to give away.

    **The only route here limited per page rather than per address.** This one is
    called by the frontend server, not by the browser, so the address belongs to
    a container and counting it put the whole deployment in one bucket - see
    `rate_limit.hosted_admission_allowed`.
    """
    if not await rate_limit.hosted_admission_allowed(public_key):
        raise HTTPException(status_code=429, detail="Too many requests")

    embed = await service.find_hosted(public_key)
    if embed is None:
        raise HTTPException(status_code=404, detail="This page is not available")
    return await service.hosted_config(embed)


@router.get("/{public_key}/logo", response_class=FileResponse)
async def hosted_logo(public_key: str, service: EmbedSvc, request: Request) -> Any:
    """The one image a hosted page may hand out without a session.

    The agent's avatar or the organization's, whichever the page was configured
    with - both are uploaded through the mechanics that already exist, so there is
    no second upload path and no operator-supplied URL for a page we serve to go
    fetching. The authenticated avatar routes stay authenticated: what makes this
    one public is the hosted flag on this embed, and nothing wider.

    Per address, unlike `/hosted` beside it: this one is fetched by the visitor's
    browser as an `<img>`, so the address is theirs. It is the most expensive
    route here - two queries, a stat and a file - which is the reason it carries a
    gate at all rather than being left as the cheap read the others are.
    """
    if not await rate_limit.embed_admission_allowed(request):
        raise HTTPException(status_code=429, detail="Too many requests")

    path = await service.hosted_logo_path(public_key)
    if path is None:
        raise HTTPException(status_code=404, detail="No logo")
    return FileResponse(path)


@router.get("/{public_key}/widget.js", response_class=Response)
async def embed_widget(public_key: str, db: DBSession, request: Request) -> Response:
    """The script a customer pastes into their page.

    Served from the API rather than a CDN so a self-hosted deployment needs no
    second host, and so the script always matches the server it talks to. It is
    handed out to anyone who asks: it contains no secret, and the origin check
    happens when it opens a socket, not when it is downloaded.

    Gated per address like the rest, which it was not until the surface count in
    `rate_limit` was made honest. "Static script" is what it looks like from
    outside; from in here it is a row read per request, and the five-minute cache
    is a browser's courtesy rather than a ceiling anybody has to respect.
    """
    if not await rate_limit.embed_admission_allowed(request):
        raise HTTPException(status_code=429, detail="Too many requests")

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
    visitor: str | None = Query(default=None, max_length=64),
) -> None:
    """One visitor's conversation with an embedded agent.

    The token arrives as a query parameter because browsers cannot set headers
    on a WebSocket handshake. It is the customer's own signed token, not ours,
    and it never leaves this process.

    `visitor` is the hosted page's own continuity key, kept in `localStorage` so a
    bookmarked link reopens the thread it left. It is a bearer credential for that
    conversation and is treated as one: it is only read for a hosted connection,
    and in `jwt` mode it is ignored outright, because the token's subject already
    answers who this is and a second answer would be a weaker one.

    **Admission gets a session; the conversation does not.** This socket stays
    open for as long as a visitor leaves the tab open, and the session below is
    closed before the first frame is read - the turn loop opens one per turn, the
    way the dashboard chat does. Held open across the conversation, fifteen idle
    widget visitors exhausted the connection pool and took the API down with them
    (#39).
    """
    origin = websocket.headers.get("origin")

    if not await rate_limit.embed_admission_allowed(websocket):
        await websocket.accept()
        await websocket.close(code=WS_TOO_MANY, reason="Too many connections. Try again shortly.")
        return

    async with get_db_context() as db:
        service = AgentEmbedService(db)
        try:
            admission = await service.admit(public_key, origin=origin, token=token)
        except EmbedDenied:
            # Accepted first, then closed with a code: a handshake rejected
            # outright gives the browser no way to tell "refused" from "server
            # is down", and the widget would retry forever.
            await websocket.accept()
            await websocket.close(code=WS_DENIED, reason="This widget is not available here")
            return

    session = EmbedSession(
        sessions=get_db_context,
        embed=admission.embed,
        visitor=admission.visitor,
        websocket=websocket,
        hosted=admission.hosted,
        # Only a hosted connection resumes by key, and only an anonymous one: a
        # `jwt` visitor is already named by their token.
        visitor_key=visitor if admission.hosted and admission.visitor is None else None,
    )
    await websocket.accept()
    try:
        await session.greet()
        while True:
            frame = await websocket.receive_json()
            await session.handle(frame)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("embed_session_failed", extra={"embed_id": str(admission.embed.id)})
        await session.fail("Something went wrong. Please try again.")
    finally:
        await session.close()
