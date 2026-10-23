"""Visuals - drawings an agent writes into the conversation, and how they are framed.

A visual is an app that has not been saved: a self-contained document an agent
writes as the `content` argument of `draw`, rendered live in the chat while the
argument streams. It is stored nowhere but in the tool call that carried it, so a
reload re-renders it from the transcript.

Two things live here because both the frame and a saved app must agree on them:

- **The document a visual becomes** (:func:`visual_document`). `html` is the page
  as written; `svg` and `mermaid` are wrapped into one. The live frame builds the
  same document from the same templates, which :func:`frame_document` hands it, so
  what is drawn in the chat and what is saved as an app are the same bytes.
- **The frame** (:func:`frame_document`): one fixed page served on the content
  origin under the app sandbox policy. It holds no visual - the console posts the
  content into it - so nothing streaming has to be stored before it can be shown,
  and the isolation comes from a response header rather than a `srcdoc` meta tag.
"""

import asyncio
import base64
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.media import prefix_for
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.artifact import ArtifactMediaType
from app.db.models.conversation import Conversation
from app.db.session import get_db_context
from app.repositories import agent as agent_repo
from app.repositories import agent_run as agent_run_repo
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation as conversation_repo
from app.repositories import visual as visual_repo
from app.repositories.conversation import ToolCallArgs
from app.schemas.visual import VisualList, VisualListItem, VisualPublish, VisualPublished
from app.services import artifact as artifacts
from app.services.access import AGENT, resolve_access
from app.services.artifact import platform_script
from app.services.conversation import ConversationService
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

VisualKind = Literal["svg", "html", "mermaid"]

DRAW = "draw"
REVISE = "revise_visual"
VISUAL_TOOLS = (DRAW, REVISE)
"""The calls that leave a visual behind. `read_visual` reads one and leaves none."""

DREW = ("Drew ", "Revised ")
"""How a `draw` or `revise_visual` call that made a visual answers. A call refused
with a retry prompt, or steered away, answers otherwise - and made nothing."""

_KINDS: tuple[VisualKind, ...] = ("svg", "html", "mermaid")

MAX_CHAIN = 50
"""How many revisions deep a visual is followed before it is called broken.

A revision names the visual it changes, and that one may be a revision too. The
id is the model's to choose, so a chain is bounded rather than trusted to end.
"""

IMAGE_NAME = r"^[a-z0-9][a-z0-9_-]{0,39}$"
"""What an image of a visual may be called - the `NAME` in `{{image:NAME}}`."""

IMAGE_MAX_BYTES = 2 * 1024 * 1024
"""One image's ceiling. A visual inlines its images when it is drawn and saved,
so a few photos are the budget, not an album."""

MAX_IMAGES = 6
"""How many images one visual may carry."""

THUMBNAIL = "_thumbnail"
"""The name a visual's thumbnail is kept under, beside its pictures - one no
picture can take, since a picture's name starts with a letter or a digit."""

THUMBNAIL_WIDTH = 640
"""How wide a thumbnail is drawn, in CSS pixels - the console's own width for one."""

THUMBNAIL_MAX_BYTES = 512 * 1024
"""A thumbnail's ceiling: a small PNG for a dashboard tile, not the drawing."""

IMAGE_TOKEN = re.compile(r"\{\{image:([a-z0-9][a-z0-9_-]{0,39})\}\}")
"""Where a visual uses one of its images: `<img src="{{image:logo}}">`, an SVG
`<image href="{{image:logo}}">`, or a CSS `url({{image:logo}})`."""

_FRAME_PATH = Path(__file__).resolve().parent.parent / "core" / "catalog" / "visuals" / "frame.html"

MERMAID_LIBRARY = "lib/mermaid-12.1.0.min.js"

_SVG_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title>
<style>
:root { color-scheme: light dark; }
html, body { margin: 0; height: 100%; }
body > svg { display: block; width: 100%; height: 100%; }
</style></head><body>
{{content}}
</body></html>
"""

_MERMAID_PAGE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{{{title}}}}</title>
<style>
:root {{ color-scheme: light dark; }}
html, body {{ margin: 0; }}
body {{ font: 14px/1.5 system-ui, sans-serif; padding: 16px; box-sizing: border-box; }}
.mermaid {{ margin: 0; display: flex; justify-content: center; }}
.mermaid svg {{ max-width: 100%; height: auto; }}
</style>
<script src="{MERMAID_LIBRARY}"></script>
</head><body>
<pre class="mermaid">{{{{content}}}}</pre>
<script>
mermaid.initialize({{
  startOnLoad: false,
  securityLevel: "strict",
  theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "default",
}});
mermaid.run({{ querySelector: ".mermaid" }});
</script>
</body></html>
"""

VISUAL_RUNTIME = """<script data-agenticos="visual">(function () {
  "use strict";
  function post(message) {
    try { parent.postMessage(message, "*"); } catch (error) { /* opened on its own */ }
  }
  function fail(message) { post({ type: "agenticos:visual-error", message: String(message) }); }
  window.addEventListener("error", function (event) {
    var target = event.target;
    // A map tile that did not load is the map kit's to handle - it falls back to
    // an outline - not a broken drawing for the model to fix.
    if (target && target.classList && target.classList.contains("leaflet-tile")) return;
    if (target && target !== window && (target.src || target.href)) {
      fail("Could not load " + (target.src || target.href));
      return;
    }
    fail((event.message || "Script error") + (event.lineno ? " (line " + event.lineno + ")" : ""));
  }, true);
  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    fail(reason && reason.message ? reason.message : reason);
  });
  document.addEventListener("securitypolicyviolation", function (event) {
    fail("Blocked: " + (event.blockedURI || "inline") + " is not allowed (" + event.effectiveDirective + ")");
  });
  // The height of what is drawn, not of the frame it is drawn in: the
  // document's scrollHeight is never less than the frame's own height, so a
  // drawing that was once tall - a map's tiles stacked for a moment before
  // their stylesheet applied - stayed that tall, and was shrunk to fit with a
  // band of nothing under it.
  function size() {
    var body = document.body;
    var height = document.documentElement.scrollHeight;
    if (body) {
      var style = getComputedStyle(body);
      height = body.scrollHeight + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
    }
    post({ type: "agenticos:visual-size", height: Math.ceil(height) });
  }
  var watch = window.ResizeObserver ? new ResizeObserver(size) : null;
  if (watch) watch.observe(document.documentElement);
  window.addEventListener("load", function () {
    // The script runs in the head, before there is a body to watch.
    if (watch && document.body) watch.observe(document.body);
    size();
    setTimeout(function () {
      // A drawing that ends up as an SVG - a Mermaid diagram above all - is sent
      // back as markup, so the console can make its thumbnail without a browser
      // of its own: the frame's pixels are not the console's to read.
      var drawn = document.querySelector("svg");
      if (drawn) post({ type: "agenticos:visual-svg", markup: drawn.outerHTML });
      post({ type: "agenticos:visual-rendered" });
    }, 800);
  });
  setInterval(function () { post({ type: "agenticos:visual-alive" }); }, 1000);
})();</script>"""
"""What a visual's document gets first in the live frame: its size and its failures.

Reported to the console, which sizes the frame to the drawing and tells the model
what went wrong - a script error, a library that did not load, a request the
policy refused. A heartbeat lets the console notice a drawing that has locked up.
Not part of a saved app: there is nobody to report to on a page opened on its own.
"""

_frame: bytes | None = None


def image_type(data: bytes) -> str | None:
    """The media type of an image, read from its bytes; `None` for anything else.

    By content, never by a name or a header: the bytes become a `data:` URI a
    drawing renders, and a file called `photo.png` that is HTML is not an image.
    SVG is admitted - shown through `<img>` or as a `data:` URI it runs no script.
    """
    head = data[:512]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in data[:4096].lower()):
        return "image/svg+xml"
    return None


def image_path(organization_id: UUID, conversation_id: UUID, visual_id: str, name: str) -> str:
    """Where one image of one visual is kept: under its thread's media prefix.

    So it goes when the conversation does, with the rest of the thread's media,
    and an organization's teardown takes it too.

    The visual's id is the model provider's tool-call id, so it is hashed rather
    than written into the path: a `..` or a `/` in it must not reach outside the
    thread's prefix. `name` is held to :data:`IMAGE_NAME` before it gets here.
    """
    folder = hashlib.sha256(visual_id.encode("utf-8")).hexdigest()[:32]
    return f"{prefix_for(organization_id, conversation_id)}/visuals/{folder}/{name}"


async def save_image(
    organization_id: UUID, conversation_id: UUID, visual_id: str, name: str, data: bytes
) -> None:
    """Keep one image of a visual, for the console and a saved app to read."""
    await get_file_storage().save_at(
        image_path(organization_id, conversation_id, visual_id, name), data
    )


async def load_image(
    organization_id: UUID, conversation_id: UUID, visual_id: str, name: str
) -> tuple[bytes, str] | None:
    """One kept image and its media type, or `None` when it is not there."""
    storage = get_file_storage()
    path = image_path(organization_id, conversation_id, visual_id, name)
    if not await storage.exists(path):
        return None
    data = await storage.load(path)
    kind = image_type(data)
    return (data, kind) if kind is not None else None


def image_names(args: Mapping[str, Any]) -> list[str]:
    """The names a recorded `draw` or `revise_visual` call gave its images."""
    raw = args.get("images")
    if not isinstance(raw, list):
        return []
    return [
        name for item in raw if isinstance(item, dict) and isinstance(name := item.get("name"), str)
    ]


def inline_images(content: str, uris: Mapping[str, str]) -> str:
    """The visual with each `{{image:NAME}}` it has an image for replaced by its URI."""
    return IMAGE_TOKEN.sub(lambda match: uris.get(match.group(1), match.group(0)), content)


_VIEW_BOX = re.compile(
    r"<svg\b[^>]*?\bviewBox\s*=\s*[\"']\s*[-+\d.eE]+[\s,]+[-+\d.eE]+[\s,]+([\d.eE+]+)[\s,]+([\d.eE+]+)",
    re.IGNORECASE,
)


def svg_aspect(content: str) -> float | None:
    """Height over width of an SVG drawing, from its `viewBox`; `None` when it has none."""
    found = _VIEW_BOX.search(content[:4000])
    if found is None:
        return None
    width, height = float(found.group(1)), float(found.group(2))
    return height / width if width > 0 and height > 0 else None


async def inlined(visual: Visual, organization_id: UUID, conversation_id: UUID) -> str:
    """The visual with every picture it has kept put in as a `data:` URI."""
    uris: dict[str, str] = {}
    for name, owner in visual.images.items():
        kept = await load_image(organization_id, conversation_id, owner, name)
        if kept is not None:
            uris[name] = data_uri(*kept)
    return inline_images(visual.content, uris)


def data_uri(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


@dataclass(frozen=True)
class VisualSummary:
    """A visual named for the model, without its content."""

    id: str
    title: str
    kind: str
    characters: int
    revision_of: str | None


def text_arg(args: dict[str, Any], key: str) -> str:
    """A string argument of a recorded call, or empty when it is missing or not a string."""
    value = args.get(key)
    return value if isinstance(value, str) else ""


def revised_id(call: ToolCallArgs) -> str | None:
    """The visual a `revise_visual` call changed; `None` for a drawing."""
    if call.tool_name != REVISE:
        return None
    return text_arg(call.args, "visual_id") or None


def visual_kind(value: str) -> VisualKind | None:
    """The kind a recorded call names, or `None` for anything else."""
    for kind in _KINDS:
        if value == kind:
            return kind
    return None


@dataclass(frozen=True)
class Visual:
    """One visual as it now reads: a drawing, or a drawing with its revisions applied."""

    id: str
    title: str
    kind: VisualKind
    content: str
    agent_id: UUID | None
    """The agent that first drew it, whoever revised it since: the namespace its
    app lives in, so a revision by another agent updates that app rather than
    starting a second one."""
    run_id: UUID | None
    """The run that first drew it, beside `agent_id`: the environment its app is
    published in, so a drawing made in staging never updates the default app."""
    images: Mapping[str, str]
    """Each image the visual may use, by name, and the call that brought it."""


class VisualError(Exception):
    """A visual that cannot be rebuilt, in words the model - or a person - can act on."""


Lookup = Callable[[str], Awaitable[ToolCallArgs | None]]


def _replacements(raw: object) -> list[tuple[str, str]]:
    if not isinstance(raw, list):
        return []
    pairs: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            old, new = item.get("old"), item.get("new")
            if isinstance(old, str) and isinstance(new, str):
                pairs.append((old, new))
    return pairs


async def rebuild(visual_id: str, lookup: Lookup) -> Visual:
    """The visual behind an id, with every revision on the way to it applied.

    Raises:
        VisualError: No visual has that id, a revision in the chain no longer
            applies, or the chain does not end.
    """
    chain: list[ToolCallArgs] = []
    current: str | None = visual_id.strip()
    while current is not None:
        if len(chain) >= MAX_CHAIN:
            raise VisualError(f"Visual `{visual_id}` has too many revisions. Draw it again.")
        call = await lookup(current)
        if call is None:
            if not chain:
                raise VisualError(
                    f"There is no visual `{current}` in this conversation. Use the id a "
                    "`draw` or `revise_visual` call returned."
                )
            raise VisualError(
                f"Visual `{visual_id}` revises `{current}`, which is gone. Draw it again."
            )
        chain.append(call)
        current = revised_id(call)

    origin = chain[-1].args
    kind = visual_kind(text_arg(origin, "kind"))
    if kind is None:
        raise VisualError(f"Visual `{visual_id}` has no kind it can be drawn as. Draw it again.")
    title = text_arg(origin, "title")
    content = text_arg(origin, "content")
    images = dict.fromkeys(image_names(origin), chain[-1].tool_call_id)
    for call in reversed(chain[:-1]):
        images.update(dict.fromkeys(image_names(call.args), call.tool_call_id))
        try:
            content = artifacts.apply_replacements(content, _replacements(call.args.get("edits")))
        except ValueError as missed:
            raise VisualError(
                f"A revision of `{visual_id}` no longer applies: {missed}"
            ) from missed
        title = text_arg(call.args, "title") or title
    # Only the pictures the drawing still uses: a long chain of revisions may have
    # added many, and every one kept is one more file read and inlined each time
    # the visual is shown.
    used = set(IMAGE_TOKEN.findall(content))
    images = {name: call_id for name, call_id in images.items() if name in used}
    if len(images) > MAX_IMAGES:
        raise VisualError(
            f"Visual `{visual_id}` uses more than {MAX_IMAGES} pictures. Draw it again with fewer."
        )
    return Visual(
        id=chain[0].tool_call_id,
        title=title,
        kind=kind,
        content=content,
        agent_id=chain[-1].agent_id,
        run_id=chain[-1].run_id,
        images=images,
    )


async def conversation_of_run(*, run_id: UUID, organization_id: UUID) -> UUID | None:
    """The conversation a run answers in, or `None` for one that has none."""
    async with get_db_context() as db:
        run = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
    return run.conversation_id if run is not None else None


async def stored_call(*, conversation_id: UUID, tool_call_id: str) -> ToolCallArgs | None:
    """A returned `draw` or `revise_visual` call in this conversation's transcript."""
    async with get_db_context() as db:
        return await conversation_repo.tool_call_in_conversation(
            db,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            names=VISUAL_TOOLS,
            result_prefixes=DREW,
        )


async def attachment_bytes(conversation_id: UUID, filename: str) -> bytes | None:
    """The newest attachment of this name in the thread, or `None` when there is none."""
    async with get_db_context() as db:
        attached = await chat_file_repo.latest_named_in_conversation(
            db, filename, conversation_id=conversation_id
        )
    if attached is None:
        return None
    return await get_file_storage().load(attached.storage_path)


async def record_visual(
    *,
    organization_id: UUID,
    conversation_id: UUID,
    tool_call_id: str,
    agent_id: UUID | None,
    user_id: UUID | None,
    title: str,
    kind: str,
    revision_of: str | None,
) -> None:
    """Index a drawing a run just made, on a session of its own, as a tool must."""
    async with get_db_context() as db:
        await visual_repo.record(
            db,
            organization_id=organization_id,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            agent_id=agent_id,
            user_id=user_id,
            title=title,
            kind=kind,
            revision_of=revision_of,
        )


async def earlier_visuals(*, conversation_id: UUID, limit: int) -> list[VisualSummary]:
    """The conversation's latest visuals, oldest first, named but not read."""
    async with get_db_context() as db:
        calls = await conversation_repo.tool_calls_named(
            db,
            conversation_id=conversation_id,
            names=VISUAL_TOOLS,
            result_prefixes=DREW,
            limit=limit,
        )
    titles = {call.tool_call_id: text_arg(call.args, "title") for call in calls}
    kinds = {call.tool_call_id: text_arg(call.args, "kind") for call in calls}
    summaries: list[VisualSummary] = []
    for call in calls:
        base = revised_id(call)
        title = titles[call.tool_call_id] or (titles.get(base, "") if base else "")
        kind = kinds[call.tool_call_id] or (kinds.get(base, "") if base else "")
        if base:
            titles[call.tool_call_id] = title
            kinds[call.tool_call_id] = kind
        summaries.append(
            VisualSummary(
                id=call.tool_call_id,
                title=title or "Untitled",
                kind=kind or "visual",
                characters=len(text_arg(call.args, "content")),
                revision_of=base,
            )
        )
    return summaries


SHARED_MAX_VISUALS = 12
"""How many visuals a thread shared by link shows - the newest ones."""

SHARED_MAX_BYTES = 16 * 1024 * 1024
"""How much drawing, pictures inlined, one view of a shared thread carries."""


async def shared_visuals(conversation: Conversation) -> dict[UUID, list[dict[str, str]]]:
    """Each message's visuals as finished documents, for a thread shared by link.

    A shared thread shows the text of its turns and never their tool calls - the
    arguments can carry what the agent read - so a visual is rebuilt here, with
    its revisions applied and its pictures inlined, and the page gets only the
    drawing. One that cannot be rebuilt is left out rather than shown broken.

    Bounded, because anybody holding the link can ask for it as often as they
    like: the newest :data:`SHARED_MAX_VISUALS`, and no more than
    :data:`SHARED_MAX_BYTES` of them between them. A turn past either keeps its
    text and shows no drawing.
    """
    calls = {
        call.tool_call_id: ToolCallArgs(call.tool_call_id, call.tool_name, call.args)
        for message in conversation.messages or []
        for call in message.tool_calls or []
        if call.tool_name in VISUAL_TOOLS
        and call.status == "completed"
        and (call.result or "").startswith(DREW)
    }

    async def lookup(call_id: str) -> ToolCallArgs | None:
        return calls.get(call_id)

    placed = [
        (message.id, call.tool_call_id)
        for message in conversation.messages or []
        for call in message.tool_calls or []
        if call.tool_call_id in calls
    ]
    shared: dict[UUID, list[dict[str, str]]] = {}
    budget = SHARED_MAX_BYTES
    for message_id, call_id in reversed(placed[-SHARED_MAX_VISUALS:]):
        try:
            visual = await rebuild(call_id, lookup)
        except VisualError:
            continue
        # The most it could come to once its pictures are inlined, as base64 -
        # judged before reading them, so a visual that does not fit costs nothing.
        if (
            len(visual.content.encode("utf-8")) + len(visual.images) * IMAGE_MAX_BYTES * 4 // 3
            > budget
        ):
            continue
        content = await inlined(visual, conversation.organization_id, conversation.id)
        budget -= len(content.encode("utf-8"))
        shared.setdefault(message_id, []).insert(
            0, {"id": visual.id, "title": visual.title, "kind": visual.kind, "content": content}
        )
    return shared


class VisualService:
    """What a member does with a visual from the console: save it as an app."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def publish(
        self, ctx: AuthContext, conversation_id: UUID, visual_id: str, data: VisualPublish
    ) -> VisualPublished:
        """Save a visual as a version of an app, under the agent whose turn drew it.

        The bytes are rebuilt from the transcript, never taken from the client, so
        the app is exactly what the agent drew. A name the member already has adds
        a version to that app; one belonging to somebody else is refused, as it is
        for an agent's own publication.

        Raises:
            NotFoundError: No such conversation for this member, or no such visual
                in it.
            BadRequestError: The name is not a valid app name, the visual cannot be
                rebuilt, or it is too large to be an app.
            AuthorizationError: The name is another member's app.
        """
        if ctx.user_id is None:
            raise AuthorizationError(message="Saving a visual takes a signed-in member")
        await ConversationService(self.db).get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            ctx=ctx,
            include_favourite=False,
        )

        async def lookup(call_id: str) -> ToolCallArgs | None:
            return await conversation_repo.tool_call_in_conversation(
                self.db,
                conversation_id=conversation_id,
                tool_call_id=call_id,
                names=VISUAL_TOOLS,
                result_prefixes=DREW,
            )

        try:
            visual = await rebuild(visual_id, lookup)
        except VisualError as broken:
            if await lookup(visual_id) is None:
                raise NotFoundError(
                    message="There is no such visual in this conversation",
                    details={"visual_id": visual_id},
                ) from broken
            raise BadRequestError(message=str(broken), details={"visual_id": visual_id}) from broken
        if visual.agent_id is None:
            raise BadRequestError(
                message="This visual has no agent to save it under",
                details={"visual_id": visual_id},
            )
        # The app is the agent's, in its namespace: reading the conversation is
        # not enough to put a name there, or a reader could take one the agent's
        # next run then finds taken.
        agent = await agent_repo.get(self.db, visual.agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT
        ):
            raise AuthorizationError(
                message="Saving this visual takes access to run the agent that drew it",
                details={"visual_id": visual_id},
            )
        title = (data.title or "").strip() or visual.title or data.name
        content = await inlined(visual, ctx.organization_id, conversation_id)
        document = visual_document(visual.kind, content, title=title).encode("utf-8")
        problem = artifacts.publish_problem(
            name=data.name, media_type=ArtifactMediaType.HTML, data=document
        )
        if problem is not None:
            if not artifacts.valid_name(data.name):
                raise refused_field("name", problem)
            raise BadRequestError(message=problem, details={"visual_id": visual_id})
        published = await artifacts.publish_with(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=visual.agent_id,
            owner_user_id=ctx.user_id,
            run_id=visual.run_id,
            name=data.name,
            title=title[:200],
            media_type=ArtifactMediaType.HTML,
            data=document,
        )
        indexed = await visual_repo.get_by_call(
            self.db, conversation_id=conversation_id, tool_call_id=visual_id
        )
        if indexed is not None:
            await visual_repo.update(self.db, db_visual=indexed, artifact_id=published.artifact_id)
        return VisualPublished(
            artifact_id=published.artifact_id,
            version=published.version_number,
            name=published.name,
            title=published.title,
            created=published.created,
            unchanged=published.unchanged,
            url=artifacts.console_url_for(published.artifact_id, published.organization_id),
        )

    async def image(
        self, ctx: AuthContext, conversation_id: UUID, visual_id: str, name: str
    ) -> tuple[bytes, str]:
        """One image of a visual, for the console to inline into the drawing.

        Read only for a member who may read the conversation, and only an image the
        visual's own call declared - so the path is never the caller's to choose.

        Raises:
            NotFoundError: No such conversation for this member, no such visual in it,
                or no such image of it - one answer for all three. Also when the image
                is declared but not kept yet: the console asks again.
        """
        missing = NotFoundError(
            message="There is no such image", details={"visual_id": visual_id, "name": name}
        )
        if ctx.user_id is None:
            raise missing
        await ConversationService(self.db).get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            ctx=ctx,
            include_favourite=False,
        )
        call = await conversation_repo.tool_call_in_conversation(
            self.db,
            conversation_id=conversation_id,
            tool_call_id=visual_id,
            names=VISUAL_TOOLS,
            result_prefixes=DREW,
        )
        if call is None or name not in image_names(call.args):
            raise missing
        kept = await load_image(ctx.organization_id, conversation_id, visual_id, name)
        if kept is None:
            raise missing
        return kept

    async def recent(self, ctx: AuthContext, *, limit: int) -> VisualList:
        """The caller's latest drawings in this organization, newest first."""
        if ctx.user_id is None:
            return VisualList(items=[])
        rows = await visual_repo.recent(
            self.db, organization_id=ctx.organization_id, user_id=ctx.user_id, limit=limit
        )
        return VisualList(
            items=[
                VisualListItem(
                    id=row.id,
                    conversation_id=row.conversation_id,
                    tool_call_id=row.tool_call_id,
                    agent_id=row.agent_id,
                    title=row.title,
                    kind=row.kind,
                    revision_of=row.revision_of,
                    artifact_id=row.artifact_id,
                    has_thumbnail=row.thumbnail_path is not None,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )

    async def thumbnail(self, ctx: AuthContext, visual_id: UUID) -> bytes:
        """A drawing's thumbnail, for the person it was drawn for.

        One the console kept is read back. A drawing it could not photograph - a
        page, whose pixels its frame does not hand over - is drawn by the
        deployment's browser the first time it is asked for, and kept.

        Raises:
            NotFoundError: No such drawing of theirs, or no thumbnail to be had -
                one answer for both, so an id says nothing about anybody else's.
        """
        missing = NotFoundError(
            message="There is no such thumbnail", details={"visual_id": visual_id}
        )
        row = await visual_repo.get(self.db, visual_id, organization_id=ctx.organization_id)
        if row is None or row.user_id is None or row.user_id != ctx.user_id:
            raise missing
        if row.thumbnail_path:
            return await get_file_storage().load(row.thumbnail_path)
        # Imported here: the renderer reaches the browser capability's endpoint
        # helpers, which a request that never draws has no reason to load.
        from app.services import visual_render

        if not visual_render.available():
            raise missing

        async def lookup(call_id: str) -> ToolCallArgs | None:
            return await conversation_repo.tool_call_in_conversation(
                self.db,
                conversation_id=row.conversation_id,
                tool_call_id=call_id,
                names=VISUAL_TOOLS,
                result_prefixes=DREW,
            )

        try:
            visual = await rebuild(row.tool_call_id, lookup)
            content = await inlined(visual, row.organization_id, row.conversation_id)
            png = await visual_render.render_png(
                visual.kind,
                content,
                title=visual.title,
                width=THUMBNAIL_WIDTH,
                aspect=svg_aspect(content) if visual.kind == "svg" else None,
            )
        except (VisualError, visual_render.RenderUnavailableError, TimeoutError) as failed:
            logger.warning("visual_thumbnail_not_drawn", extra={"visual_id": str(visual_id)})
            raise missing from failed
        path = image_path(row.organization_id, row.conversation_id, row.tool_call_id, THUMBNAIL)
        await get_file_storage().save_at(path, png)
        await visual_repo.update(self.db, db_visual=row, thumbnail_path=path)
        return png

    async def save_thumbnail(
        self, ctx: AuthContext, conversation_id: UUID, visual_id: str, data: bytes
    ) -> None:
        """Keep the thumbnail the console made of a drawing it just rendered.

        Only the person the drawing was made for sets it - the tile is on their
        dashboard - and only a small PNG is taken.

        Raises:
            NotFoundError: No such drawing of theirs in this conversation.
            BadRequestError: Not a PNG, or too large for a thumbnail.
        """
        row = await visual_repo.get_by_call(
            self.db, conversation_id=conversation_id, tool_call_id=visual_id
        )
        if (
            row is None
            or row.organization_id != ctx.organization_id
            or row.user_id is None
            or row.user_id != ctx.user_id
        ):
            raise NotFoundError(message="There is no such visual", details={"visual_id": visual_id})
        if image_type(data) != "image/png" or len(data) > THUMBNAIL_MAX_BYTES:
            raise BadRequestError(
                message=f"A thumbnail is a PNG of at most {THUMBNAIL_MAX_BYTES:,} bytes",
                details={"visual_id": visual_id},
            )
        path = image_path(ctx.organization_id, conversation_id, visual_id, THUMBNAIL)
        await get_file_storage().save_at(path, data)
        await visual_repo.update(self.db, db_visual=row, thumbnail_path=path)


def visual_document(kind: VisualKind, content: str, *, title: str) -> str:
    """The self-contained page a visual is, as a saved app stores it."""
    if kind == "html":
        return content
    template = _SVG_PAGE if kind == "svg" else _MERMAID_PAGE
    body = content if kind == "svg" else escape(content, quote=False)
    return template.replace("{{title}}", escape(title)).replace("{{content}}", body)


async def frame_document() -> bytes:
    """The renderer page, with the visual templates and the runtime it writes first.

    Read once and kept: it is the same page for every visual.
    """
    global _frame
    if _frame is None:
        page = await asyncio.to_thread(_FRAME_PATH.read_text, "utf-8")
        _frame = page.replace("</head>", _composer() + "\n</head>", 1).encode("utf-8")
    return _frame


def _composer() -> str:
    """The frame's `__agenticosVisualDocument`, built from the templates above.

    The templates travel as JSON in a script, so a `</script>` inside one is
    written `<\\/script>` to keep the script element whole.
    """
    data = json.dumps(
        {
            "svg": _SVG_PAGE,
            "mermaid": _MERMAID_PAGE,
            "runtime": platform_script() + VISUAL_RUNTIME,
        }
    ).replace("</", "<\\/")
    return f"""<script>(function () {{
  "use strict";
  var T = {data};
  var LEAD = /^(?:\\uFEFF)?(?:\\s+|<!--(?:[^-]|-(?!->))*-->)*(?:<!doctype\\b[^>]*>)?/i;
  function esc(text, attribute) {{
    var out = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return attribute ? out.replace(/"/g, "&quot;").replace(/'/g, "&#x27;") : out;
  }}
  window.__agenticosVisualDocument = function (kind, content, title) {{
    var page = content;
    if (kind === "svg" || kind === "mermaid") {{
      var body = kind === "svg" ? content : esc(content, false);
      page = T[kind].split("{{{{title}}}}").join(esc(title || "", true)).split("{{{{content}}}}").join(body);
    }}
    var lead = LEAD.exec(page)[0].length;
    return page.slice(0, lead) + T.runtime + page.slice(lead);
  }};
}})();</script>"""
