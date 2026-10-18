"""A visual drawn to a PNG by the deployment's own browser (#2171).

Where no frame can run a drawing - a reply in a chat app, a dashboard tile for a
page - the browser named by `VISUAL_RENDER_CDP_URL` draws it instead. It reaches
nothing while it does: the drawing is served to it at the address the frame
would have, under the same sandbox policy, the library set is served from disk,
and every other request is refused before it leaves the browser. A tab of its
own, in a browser context of its own, closed afterwards.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.agents.capabilities.browser_use._endpoint import pin_host, version_url, websocket_url
from app.core.config import settings
from app.repositories.conversation import ToolCallArgs
from app.services import artifact as artifacts
from app.services import visual as visuals
from app.services.visual import VISUAL_RUNTIME, VISUAL_TOOLS, VisualKind, visual_document

logger = logging.getLogger(__name__)

RENDER_TIMEOUT = 20.0
"""Seconds a drawing has to load, run and be photographed."""

MAX_HEIGHT = 2400
"""The tallest picture taken, in CSS pixels; a longer page is cut there."""

_LEAD = re.compile(r"\A(?:﻿)?(?:\s+|<!--(?:[^-]|-(?!->))*-->)*(?:<!doctype\b[^>]*>)?", re.I)

# Set by the drawing's own runtime when it has loaded and run for a moment - the
# message it posts to its parent, which a top-level page posts to itself.
_RENDERED_FLAG = """window.addEventListener("message", function (event) {
  if (event.data && event.data.type === "agenticos:visual-rendered") window.__agenticosRendered = true;
});"""


class RenderUnavailableError(RuntimeError):
    """No browser to draw with, or one this deployment does not allow."""


@dataclass(frozen=True)
class Answer:
    """What the browser's request for one address is answered with."""

    body: bytes | None
    content_type: str = "text/html; charset=utf-8"
    policy: str | None = None


def page_url() -> str:
    """Where the drawing is served to the browser: beside the library set, as the frame is."""
    origin = (settings.ARTIFACT_ORIGIN or settings.PUBLIC_BASE_URL).rstrip("/")
    return f"{origin}{settings.API_V1_STR}/artifact-content/visual-render"


def library_prefix() -> str:
    return page_url().rsplit("/", 1)[0] + "/lib/"


def rendered_document(kind: VisualKind, content: str, *, title: str) -> str:
    """The drawing as the frame would write it, with the runtime that says it rendered."""
    page = visual_document(kind, content, title=title)
    lead = _LEAD.match(page)
    cut = lead.end() if lead else 0
    return page[:cut] + VISUAL_RUNTIME + page[cut:]


async def answer(url: str, document: bytes) -> Answer:
    """How the browser's request for `url` is answered: the drawing, a library file, or nothing."""
    if url == page_url():
        return Answer(body=document, policy=artifacts.content_security_policy())
    prefix = library_prefix()
    if url.startswith(prefix):
        name = url[len(prefix) :].split("?", 1)[0]
        if name in artifacts.ARTIFACT_LIBRARY:
            data, media_type = await artifacts.library_file(name)
            return Answer(body=data, content_type=media_type)
    return Answer(body=None)


def allowed_endpoint(cdp_url: str) -> str:
    """The configured browser, checked against the deployment's allowlist.

    Raises:
        RenderUnavailableError: None is configured, or its host is not allowed.
    """
    if not cdp_url:
        raise RenderUnavailableError("No browser is configured to draw visuals with.")
    host = (urlsplit(cdp_url).hostname or "").lower()
    allowed = {entry.strip().lower() for entry in settings.BROWSER_CDP_ALLOWED_HOSTS}
    if not host or host not in allowed:
        raise RenderUnavailableError(
            f"VISUAL_RENDER_CDP_URL names {host!r}, which BROWSER_CDP_ALLOWED_HOSTS does not."
        )
    return cdp_url


def available() -> bool:
    """Whether this deployment can draw a visual to a picture at all."""
    try:
        allowed_endpoint(settings.VISUAL_RENDER_CDP_URL)
    except RenderUnavailableError:
        return False
    return True


async def render_png(
    kind: VisualKind, content: str, *, title: str, width: int = 1000, aspect: float | None = None
) -> bytes:
    """The drawing as a PNG, `width` CSS pixels wide.

    `aspect` (height over width) sizes an SVG by its `viewBox`; anything else is
    measured once it has rendered, up to :data:`MAX_HEIGHT`.

    Raises:
        RenderUnavailableError: No browser to draw with.
        TimeoutError: The drawing did not render in time.
    """
    cdp_url = allowed_endpoint(settings.VISUAL_RENDER_CDP_URL)
    document = rendered_document(kind, content, title=title).encode("utf-8")
    async with asyncio.timeout(RENDER_TIMEOUT):
        return await _photograph(cdp_url, document, width=width, aspect=aspect)


async def picture_of_turn(
    called: list[tuple[str, str, dict[str, Any], str | None]],
    *,
    organization_id: UUID,
    conversation_id: UUID | None,
) -> bytes | None:
    """The last visual a turn drew, as a PNG, for a surface that shows pictures, not pages.

    `called` is the turn's calls in order, as `(id, tool, args, result)`. A revision
    of a drawing from an earlier turn finds its base in the conversation.
    `None` when the turn drew nothing, there is no browser to draw with, or the
    drawing would not render: a picture that cannot be made must not cost
    somebody the answer it came with.
    """
    in_turn = {
        call_id: ToolCallArgs(call_id, tool, args)
        for call_id, tool, args, result in called
        if tool in VISUAL_TOOLS and result is not None and result.startswith(visuals.DREW)
    }
    last = next((call_id for call_id, *_ in reversed(called) if call_id in in_turn), None)
    if last is None or not available():
        return None

    async def lookup(call_id: str) -> ToolCallArgs | None:
        if call_id in in_turn:
            return in_turn[call_id]
        if conversation_id is None:
            return None
        return await visuals.stored_call(conversation_id=conversation_id, tool_call_id=call_id)

    try:
        visual = await visuals.rebuild(last, lookup)
        content = (
            await visuals.inlined(visual, organization_id, conversation_id)
            if conversation_id is not None
            else visual.content
        )
        return await render_png(
            visual.kind,
            content,
            title=visual.title,
            aspect=visuals.svg_aspect(content) if visual.kind == "svg" else None,
        )
    except Exception:
        logger.exception("Could not draw a visual for a reply")
        return None


async def _resolve(host: str) -> str | None:  # pragma: no cover - needs a resolver
    try:
        ipaddress.ip_address(host)
    except ValueError:
        found = await asyncio.get_running_loop().getaddrinfo(host, None)
        return str(found[0][4][0]) if found else None
    return None


async def _photograph(  # pragma: no cover - needs a live browser
    cdp_url: str, document: bytes, *, width: int, aspect: float | None
) -> bytes:
    """Open a tab in a context of its own, serve it the drawing, wait, and take the picture."""
    import httpx

    try:
        # ty: `cdp-use` arrives with the `browser` extra, as for `browser_use`.
        from cdp_use import CDPClient  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise RenderUnavailableError("Drawing visuals needs the `browser` extra.") from exc

    endpoint = pin_host(cdp_url, await _resolve(urlsplit(cdp_url).hostname or ""))
    if endpoint.startswith(("ws://", "wss://")):
        socket = endpoint
    else:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(version_url(endpoint))
            response.raise_for_status()
            socket = websocket_url(endpoint, response.json())

    client = CDPClient(socket)
    await client.start()
    pending: set[asyncio.Task[Any]] = set()
    context_id: str | None = None
    target: str | None = None
    try:
        context = await client.send.Target.createBrowserContext(params={"disposeOnDetach": True})
        context_id = context["browserContextId"]
        created = await client.send.Target.createTarget(
            params={"url": "about:blank", "browserContextId": context_id}
        )
        target = created["targetId"]
        attached = await client.send.Target.attachToTarget(
            params={"targetId": target, "flatten": True}
        )
        session = attached["sessionId"]

        async def respond(request_id: str, url: str) -> None:
            reply = await answer(url, document)
            if reply.body is None:
                await client.send.Fetch.failRequest(
                    params={"requestId": request_id, "errorReason": "BlockedByClient"},
                    session_id=session,
                )
                return
            headers = [
                {"name": "Content-Type", "value": reply.content_type},
                {"name": "Access-Control-Allow-Origin", "value": "*"},
            ]
            if reply.policy is not None:
                headers.append({"name": "Content-Security-Policy", "value": reply.policy})
            await client.send.Fetch.fulfillRequest(
                params={
                    "requestId": request_id,
                    "responseCode": 200,
                    "responseHeaders": headers,
                    "body": base64.b64encode(reply.body).decode("ascii"),
                },
                session_id=session,
            )

        def paused(event: dict[str, Any], session_id: str | None) -> None:
            if session_id == session:
                task = asyncio.ensure_future(respond(event["requestId"], event["request"]["url"]))
                pending.add(task)
                task.add_done_callback(pending.discard)

        client.register.Fetch.requestPaused(paused)
        await client.send.Fetch.enable(
            params={"patterns": [{"urlPattern": "*"}]}, session_id=session
        )
        height = round(width * aspect) if aspect else 800
        await client.send.Emulation.setDeviceMetricsOverride(
            params={
                "width": width,
                "height": min(height, MAX_HEIGHT),
                "deviceScaleFactor": 1,
                "mobile": False,
            },
            session_id=session,
        )
        await client.send.Page.enable(session_id=session)
        await client.send.Page.addScriptToEvaluateOnNewDocument(
            params={"source": _RENDERED_FLAG}, session_id=session
        )
        await client.send.Page.navigate(params={"url": page_url()}, session_id=session)
        while True:
            flag = await client.send.Runtime.evaluate(
                params={"expression": "window.__agenticosRendered === true", "returnByValue": True},
                session_id=session,
            )
            if flag.get("result", {}).get("value") is True:
                break
            await asyncio.sleep(0.2)
        if not aspect:
            measured = await client.send.Runtime.evaluate(
                params={
                    "expression": "Math.ceil(document.body.scrollHeight)",
                    "returnByValue": True,
                },
                session_id=session,
            )
            height = int(measured.get("result", {}).get("value") or height)
            await client.send.Emulation.setDeviceMetricsOverride(
                params={
                    "width": width,
                    "height": max(1, min(height, MAX_HEIGHT)),
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
                session_id=session,
            )
        shot = await client.send.Page.captureScreenshot(
            params={"format": "png"}, session_id=session
        )
        return base64.b64decode(shot["data"])
    finally:
        for task in pending:
            task.cancel()
        if target is not None:
            try:
                await client.send.Target.closeTarget(params={"targetId": target})
            except Exception:
                logger.warning("visual_render_close_failed", exc_info=True)
        if context_id is not None:
            try:
                await client.send.Target.disposeBrowserContext(
                    params={"browserContextId": context_id}
                )
            except Exception:
                logger.warning("visual_render_dispose_failed", exc_info=True)
        await client.stop()
