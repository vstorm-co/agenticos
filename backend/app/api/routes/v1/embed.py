"""The public face of an embedded agent: config, widget, and a socket.

Three endpoints, all reachable without a session, all authorised by the same
thing - a public key plus the origin the browser reports. Nothing here reads a
cookie, and nothing here trusts a header the page could have set to anything.

Why a WebSocket rather than a POST per message: an agent turn takes seconds and
streams tokens the whole way. Over HTTP the customer's page has to poll or hold
an SSE connection open and reconnect it themselves; over a socket the browser
does that, and the same frames the dashboard chat already speaks work unchanged.
"""

import logging
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.api.deps import (
    DBSession,
    EmbedSvc,
    limit_embed_admission,
    limit_embed_dictation,
    limit_embed_script,
    limit_embed_upload,
    limit_hosted_config,
    limit_hosted_logo,
)
from app.api.embed_cors import allow_embed_origin
from app.api.routes.v1._stored_bytes import stored_image_response
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.logging import one_line
from app.db.session import get_db_context
from app.schemas.agent_embed import PublicEmbedConfig, PublicPageConfig, PublicUpload
from app.schemas.ml import DictationRead
from app.services import rate_limit, transcription
from app.services.agent_embed import AgentEmbedService, EmbedDenied
from app.services.embed_session import WIDGET_JS, EmbedSession, continuity_key
from app.services.embed_voice_js import VOICE_JS, VOICE_JS_VERSION
from app.services.voice import VoiceCallSession, embed_voice_caller

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


@router.get(
    "/{public_key}/config",
    response_model=PublicEmbedConfig,
    dependencies=[Depends(limit_embed_admission)],
)
async def embed_config(
    public_key: str,
    service: EmbedSvc,
    response: Response,
    origin: str | None = Header(default=None),
) -> Any:
    """What the widget renders itself from.

    Answers with the CORS header for the calling origin only when that origin is
    on the widget's list - a wildcard here would let any site read the config
    and, more to the point, would make the allow-list decorative.
    """
    try:
        admission = await service.admit(public_key, origin=origin, token=None)
        # Inside the same refusal, because a key of another kind has no widget
        # config to answer with and saying which it is would be saying more than
        # a refusal should.
        config = await service.public_config(admission.embed)
    except EmbedDenied:
        raise HTTPException(status_code=403, detail="This widget is not available here") from None

    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return config


@router.get(
    "/{public_key}/hosted",
    response_model=PublicPageConfig,
    dependencies=[Depends(limit_hosted_config)],
)
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
    embed = await service.find_page(public_key)
    if embed is None:
        raise HTTPException(status_code=404, detail="This page is not available")
    return await service.page_config(embed)


@router.get(
    "/{public_key}/logo",
    response_class=Response,
    dependencies=[Depends(limit_hosted_logo)],
)
async def hosted_logo(public_key: str, service: EmbedSvc) -> Any:
    """The one image a hosted page may hand out without a session.

    The agent's avatar or the organization's, whichever the page was configured
    with - both are uploaded through the mechanics that already exist, so there is
    no second upload path and no operator-supplied URL for a page we serve to go
    fetching. The authenticated avatar routes stay authenticated: what makes this
    one public is this embed being a `page`, and nothing wider.

    Per page, like `/hosted` beside it, not per address: the browser fetches this
    from the page's own origin, so the request that reaches here is the frontend
    server's own `fetch` and its address is the container's - counting it would
    put every hosted page's logo in one deployment-wide bucket. It is the most
    expensive route here - two queries, a stat and a file - which is the reason it
    carries a gate at all rather than being left as the cheap read the others are.

    **The type is decided here, not by the name on disk.** A stored file keeps the
    extension whoever uploaded it chose, and the upload paths that produced these
    files - a page's own logo, an agent's avatar, an organization's - validated the
    `Content-Type` header the client *declared* rather than the bytes. So a file
    named `x.html` reaches this route, and a bare `FileResponse` would let
    Starlette guess `text/html` from the suffix and serve a script from the origin
    the hosted page is on, where the frontend proxies this under
    `script-src 'self' 'unsafe-inline'`. So the type is read from the file's own
    bytes, and anything that is not one of the four image types is refused rather
    than corrected: this route hands out one image, and anything else is not this
    page's logo.
    """
    stored = await service.page_logo_path(public_key)
    if stored is None:
        raise HTTPException(status_code=404, detail="No logo")
    response = await stored_image_response(stored, headers={"X-Content-Type-Options": "nosniff"})
    if response is None:
        logger.warning("hosted_logo_not_an_image", extra={"public_key": one_line(public_key)})
        raise HTTPException(status_code=404, detail="No logo")
    return response


@router.get(
    "/{public_key}/avatar",
    response_class=Response,
    dependencies=[Depends(limit_hosted_logo)],
)
async def widget_avatar(public_key: str, service: EmbedSvc) -> Any:
    """The agent's uploaded picture, for the widget's header and its answers (#2006).

    Public for the reason `/logo` is: what makes it so is this embed being an
    active widget, and the authenticated avatar route stays authenticated. Typed
    from the file's bytes like `/logo`, and refused when they are not an image.
    """
    stored = await service.widget_avatar_path(public_key)
    if stored is None:
        raise HTTPException(status_code=404, detail="No avatar")
    response = await stored_image_response(stored, headers={"X-Content-Type-Options": "nosniff"})
    if response is None:
        # The stored path, not the key from the address: the key reached the log
        # as typed, and the path is the server's own and names the same file.
        logger.warning("widget_avatar_not_an_image", extra={"stored": stored})
        raise HTTPException(status_code=404, detail="No avatar")
    return response


@router.get(
    "/{public_key}/widget.js",
    response_class=Response,
    dependencies=[Depends(limit_embed_script)],
)
async def embed_widget(public_key: str, db: DBSession) -> Response:
    """The script a customer pastes into their page.

    Served from the API rather than a CDN so a self-hosted deployment needs no
    second host, and so the script always matches the server it talks to. It is
    handed out to anyone who asks: it contains no secret, and the origin check
    happens when it opens a socket, not when it is downloaded.

    Gated per address like the rest, which it was not until the surface count in
    `rate_limit` was made honest. "Static script" is what it looks like from
    outside; from in here it is a row read per request, and the five-minute cache
    is a browser's courtesy rather than a ceiling anybody has to respect.

    On its own counter rather than admission's, because a page load fetches this
    *and* a config *and* opens a socket: one bucket for all three made an operator's
    twenty admissions a minute about seven page loads. See `embed_script_allowed`.
    """
    service = AgentEmbedService(db)
    embed = await service.find_public(public_key)
    if embed is None or not embed.is_active:
        # 404 for a key nobody recognises: this is a script tag, and an HTML
        # error page in a `<script>` is a syntax error in somebody's console.
        raise HTTPException(status_code=404, detail="Unknown widget")

    body = (
        WIDGET_JS.replace("__PUBLIC_KEY__", embed.public_key)
        .replace("__BASE_URL__", settings.PUBLIC_BASE_URL.rstrip("/"))
        .replace("__VOICE_VERSION__", VOICE_JS_VERSION)
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


@router.get(
    "/{public_key}/voice.js",
    response_class=Response,
    dependencies=[Depends(limit_embed_script)],
)
async def embed_voice_script(
    public_key: str,
    service: EmbedSvc,
    v: Annotated[
        str | None,
        Query(max_length=64, description="The script's content hash, as `widget.js` asks for it"),
    ] = None,
) -> Any:
    """The widget's voice call UI (#54).

    Fetched by `widget.js` the first time a visitor opens the panel, and only
    when the public config offers calls, so the script every visitor downloads
    stays small. Like `widget.js` it carries no secret and decides nothing: the
    call's socket is where admission happens. 404 for a key that names no active
    widget with calls switched on, for the reason `widget.js` gives - an error
    page in a `<script>` is a syntax error in somebody's console.

    On the script counter, with `widget.js`: a visitor who opens the panel
    fetches both.

    `widget.js` asks for `?v=<content hash>`, so the URL changes whenever the
    script does and that response is cached for good: a browser can never pair
    a cached call script with a newer widget. Any other `v` - a widget cached
    from before a deploy - gets the current script with the short cache.
    """
    embed = await service.find_voice_widget(public_key)
    if embed is None:
        raise HTTPException(status_code=404, detail="Unknown widget")

    body = VOICE_JS.replace("__PUBLIC_KEY__", embed.public_key).replace(
        "__BASE_URL__", settings.PUBLIC_BASE_URL.rstrip("/")
    )
    cache = (
        "public, max-age=31536000, immutable" if v == VOICE_JS_VERSION else "public, max-age=300"
    )
    return Response(
        content=body,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": cache},
    )


@router.post(
    "/{public_key}/files",
    response_model=PublicUpload,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_embed_upload)],
)
async def embed_upload(
    public_key: str,
    service: EmbedSvc,
    file: Annotated[UploadFile, File()],
    visitor: Annotated[str, Header(alias="X-Visitor-Key", max_length=64)],
) -> Any:
    """A file from a stranger, on a page whose operator allowed it.

    **The only route on this surface that stores anything**, which is why it is
    the only one with three gates rather than one. The limit is counted per address
    *and* per visitor key: the key is minted by the browser, so counting only that
    bounds nothing - a script varies it per file - and counting only the address
    lets one browser on a shared one spend everybody's. The cap and the MIME
    allowlist are the service's, and the row belongs to whoever published the page -
    see `AgentEmbedService.accept_upload`.

    Counted before the key is looked up, like admission next door, so probing for
    live keys with a body attached is not free.

    404 for every refusal that is about the *page* - unknown key, not a page, not
    accepting files, no owner to attribute a file to - because a visitor is owed
    "not here" and nothing about somebody else's configuration. What they sent is
    a different matter and is answered plainly: too large, or a type nothing here
    can read.

    It answers the id and nothing else. The parse, the size and the storage path
    are the operator's to read in the transcript, not the visitor's to read back.

    The continuity key travels as a header rather than a query parameter: the
    model's own docstring calls it a bearer credential for the whole transcript,
    and a query string lands in access logs and any intermediary's. The socket
    handshake cannot avoid a query; this route can.
    """
    if continuity_key(visitor) is None:
        raise HTTPException(status_code=400, detail="A visitor key is required")

    embed = await service.find_page(public_key)
    if embed is None:
        raise HTTPException(status_code=404, detail="This page is not available")
    try:
        stored = await service.accept_upload(
            embed,
            data=await file.read(),
            filename=file.filename or "attachment",
            content_type=file.content_type,
        )
    except EmbedDenied:
        raise HTTPException(status_code=404, detail="This page is not available") from None
    return PublicUpload(id=stored.id, filename=stored.filename)


@router.post(
    "/{public_key}/dictation",
    response_model=DictationRead,
    dependencies=[Depends(limit_embed_dictation)],
)
async def embed_dictation(
    public_key: str,
    request: Request,
    response: Response,
    service: EmbedSvc,
    file: Annotated[
        UploadFile,
        File(
            description=(
                "The recording: WAV holding 16 kHz mono 16-bit PCM, or - where the deployment "
                "accepts compressed audio - WebM, Ogg or MP4 from MediaRecorder"
            )
        ),
    ],
    duration: Annotated[
        float | None,
        Form(
            ge=0,
            description=(
                "How many seconds the browser recorded. Client-reported, used for the usage "
                "record only where the provider states no length, and clamped"
            ),
        ),
    ] = None,
    token: Annotated[
        str | None,
        Form(max_length=4096, description="A `jwt` widget's visitor token, as on the socket"),
    ] = None,
    visitor: Annotated[str | None, Header(alias="X-Visitor-Key", max_length=64)] = None,
    origin: Annotated[str | None, Header()] = None,
) -> Any:
    """Turn a visitor's recording into text, on a page or a widget set to `server` (#1797).

    Admission follows the surface - see `AgentEmbedService.admit_dictation`: a
    widget by its allow-list and, in `jwt` mode, the customer's token; a page by
    its continuity key in `X-Visitor-Key`; a socket not at all. Then the embed's
    own `dictation` has to be `server` and its agent published. The organization's
    `/chat` engine has no say here - it is about the console's composer.

    **The widget sends no custom header**, so its request is a simple one with no
    preflight, and the token travels as a form field: never in the query string,
    which lands in access logs, and never in a header, which would need a preflight
    the global CORS policy refuses for somebody else's site. The visitor's origin
    is what this answers to instead - on success and on every refusal after
    admission (`app.api.embed_cors`), so a recording too long or a provider timing
    out reaches the widget as what it is rather than as a network error.

    The audio is not stored, and the text is the visitor's to edit before sending.
    Refusals carry `details.reason` exactly as `POST /agents/{id}/dictation` does:
    400 `empty`, `unsupported_type`, `too_large`; 503 `not_configured`,
    `provider_error`, `timeout`. 404 for every refusal about the embed, and 429
    past the per-address, per-link or per-visitor limit. Each attempt that reaches
    the provider is a paid call outside every model budget, which is what those
    limits are for - `docs/channels.md` gives the worst case for a leaked link.
    """
    try:
        admission = await service.admit_dictation(
            public_key, origin=origin, token=token, visitor_key=continuity_key(visitor)
        )
    except EmbedDenied:
        raise HTTPException(status_code=404, detail="Dictation is not available here") from None
    if admission.embed.kind == "widget":
        # Admitted against the allow-list, so this origin may read what follows.
        allow_embed_origin(request, origin)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
    try:
        text = await service.dictate(
            admission,
            # One byte past the ceiling, so an oversized body is never copied whole
            # and the service can still name the limit it is over.
            content=await file.read(transcription.MAX_BYTES + 1),
            mime_type=file.content_type or "application/octet-stream",
            reported_seconds=duration,
        )
    except EmbedDenied:
        raise HTTPException(status_code=404, detail="Dictation is not available here") from None
    return DictationRead(text=text)


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

    The shape is checked rather than assumed, because this socket is a published
    integration (#516) and a client of somebody's own may reach it. Whoever holds
    a key resumes the thread it names, so `visitor=1` would be a conversation
    anybody can walk into, and a client keying on a customer id rather than on
    random bytes is the mistake that invites. Anything that is not the 128 random
    bits our page mints is dropped - see `_continuity_key`.

    **Admission gets a session; the conversation does not.** This socket stays
    open for as long as a visitor leaves the tab open, and the session below is
    closed before the first frame is read - the turn loop opens one per turn, the
    way the dashboard chat does. Held open across the conversation, fifteen idle
    widget visitors exhausted the connection pool and took the API down with them
    (#39).
    """
    origin = websocket.headers.get("origin")

    # The one admission gate that is not `limit_embed_admission`: a refusal here is
    # a close code, not a status, so there is no exception handler to raise into.
    if not (await rate_limit.embed_admission_allowed(websocket)).allowed:
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
        # Only a page resumes by key, and only an anonymous visitor: a `jwt`
        # visitor is already named by their token, and a widget's conversation
        # lasts as long as its socket.
        visitor_key=(
            continuity_key(visitor)
            if admission.embed.kind == "page" and admission.visitor is None
            else None
        ),
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


@router.websocket("/{public_key}/voice/ws")
async def embed_voice_socket(
    websocket: WebSocket,
    public_key: str,
    token: str | None = Query(default=None),
    visitor: str | None = Query(default=None, max_length=64),
) -> None:
    """A visitor's voice call with an embedded agent (#54).

    Admitted as the embed's own socket is - a widget by its allow-list and, in
    `jwt` mode, the customer's token; a hosted page by this deployment's origin and
    its continuity key in `visitor`, whose thread the call lands in; a socket
    integration not at all - and only while the embed's `voice_conversation` is
    on. Then the call's own protocol and refusals, exactly as `/ws/voice`
    speaks them (`app.schemas.voice`).

    **Every call is a paid realtime session**, so starting one is counted per
    address before the key is looked up (`rate_limit.embed_voice_allowed`, `4029` past
    it), then per visitor for a `jwt` widget and per link once the visitor is admitted,
    at most `VOICE_MAX_CALLS_PER_EMBED` calls are open on one embed at once
    (refused on the socket as `line_busy`), and each call is bounded by the
    agent's longest call and the budgets. The
    embed's own `rate_limit_per_minute` counts messages, not calls. A visitor cannot approve anything:
    tools that need an approval are left out of their calls. Refusals about the
    embed all close with `4003`, without saying which.
    """
    if not (await rate_limit.embed_voice_allowed(websocket)).allowed:
        await websocket.accept()
        await websocket.close(code=WS_TOO_MANY, reason="Too many calls. Try again shortly.")
        return
    visitor_key = continuity_key(visitor)
    async with get_db_context() as db:
        try:
            admission = await AgentEmbedService(db).admit_voice(
                public_key,
                origin=websocket.headers.get("origin"),
                token=token,
                visitor_key=visitor_key,
            )
        except EmbedDenied, BadRequestError:
            await websocket.accept()
            await websocket.close(code=WS_DENIED, reason="Calls are not available here")
            return
        visitor_over = (
            admission.visitor is not None
            and not (
                await rate_limit.embed_voice_visitor_allowed(
                    public_key=public_key, visitor=admission.visitor
                )
            ).allowed
        )
        # The link's ceiling only once admitted: a stranger with no valid token
        # must not be able to spend it for the visitors who have one.
        if (
            visitor_over
            or not (await rate_limit.embed_voice_link_allowed(public_key=public_key)).allowed
        ):
            await websocket.accept()
            await websocket.close(code=WS_TOO_MANY, reason="Too many calls. Try again shortly.")
            return
        caller = await embed_voice_caller(db, admission, visitor_key=visitor_key)
    await websocket.accept()
    await VoiceCallSession(websocket, caller).run()
