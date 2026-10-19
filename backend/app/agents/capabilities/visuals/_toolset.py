"""The `draw`, `revise_visual` and `read_visual` tools, and the text the model reads first.

A visual's content is the `content` argument of the `draw` call that carried it,
streamed to the console while the model writes it and stored with the call in the
transcript. Nothing else holds it. So rebuilding one - to revise it, to read it
back - finds the call: in this run's own messages first, then in the
conversation's earlier turns, and applies any revisions in the order they were
made. Nothing the model passes reaches past the run's conversation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from pydantic import BaseModel, Field
from pydantic_ai._ssrf import safe_download
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities._failures import steer
from app.agents.capabilities.artifacts._toolset import ArtifactEdit, apply_edits
from app.agents.capabilities.visuals._reach import WebReach
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.repositories.conversation import ToolCallArgs
from app.services import visual as visuals
from app.services.visual import (
    DRAW,
    IMAGE_MAX_BYTES,
    IMAGE_NAME,
    IMAGE_TOKEN,
    MAX_IMAGES,
    REVISE,
    VISUAL_TOOLS,
    VisualError,
    VisualKind,
)

READ_LIMIT = 100_000
"""How much of a visual `read_visual` returns, in characters - `read_artifact`'s cut."""


# Leading XML declaration, comments and whitespace, then the element itself. A
# comment's body is matched one way only - a non-dash, or a dash not opening `-->`
# - so a run of `--><!--` cannot be split between repetitions in exponentially
# many ways.
_SVG_START = re.compile(
    r"\A\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--(?:[^-]|-(?!->))*-->\s*)*<svg[\s>]", re.IGNORECASE
)

# A script, stylesheet, image or font loaded from another site, which the frame
# refuses. Caught here so the model hears it before anyone sees a broken drawing.
_REMOTE = re.compile(
    r"""<(?:script|link|img|iframe|source|video|audio)\b[^>]*?\b(?:src|href)\s*=\s*["']?\s*(?:https?:)?//"""
    r"""|@import\s+(?:url\()?\s*["']?(?:https?:)?//"""
    r"""|url\(\s*["']?(?:https?:)?//""",
    re.IGNORECASE,
)

REPORT_TIMEOUT = 10.0
"""How long a drawing waits for the person's browser to say how it rendered, in seconds.

Long enough for the frame to load the libraries and run the drawing's scripts;
short enough that a tab closed mid-turn costs the run a pause, not a stall.
"""

IMAGE_DOWNLOAD_TIMEOUT = 20
"""Seconds one image from the web may take to arrive."""


class VisualImage(BaseModel):
    """A picture the drawing uses, by the name the drawing calls it."""

    name: str = Field(
        description="How the drawing refers to it, as `{{image:NAME}}` - lower-case letters, "
        "digits, `-` and `_`, e.g. `logo` or `team-photo`"
    )
    source: str = Field(
        description="Where it comes from: the file name of an image attached to this "
        "conversation, a path in your workspace, or an `https://` address"
    )


_NO_CONVERSATION = (
    "There is no earlier visual to reach here: this run is not part of a conversation. "
    "Draw it again with `draw`."
)


def content_problem(kind: VisualKind, content: str) -> str | None:
    """Why this content would not draw, in words the model can act on; `None` when it would."""
    if not content.strip():
        return "`content` is empty. Pass the whole drawing."
    size = len(content.encode("utf-8"))
    if size > settings.ARTIFACT_MAX_BYTES:
        return (
            f"The drawing is {size:,} bytes, over the {settings.ARTIFACT_MAX_BYTES:,}-byte limit. "
            "Draw less, or generate repeated shapes with a script instead of writing each one."
        )
    if kind == "svg" and _SVG_START.match(content) is None:
        return (
            "A `svg` visual is one `<svg>` element with a `viewBox`, starting with `<svg`. "
            "For a whole page with script, use `kind` `html`."
        )
    if _REMOTE.search(content) is not None:
        return (
            "The drawing loads something from another site, and the frame has no network: it "
            "would not load. Use the served library set by its relative path (`lib/...`), list "
            "pictures in `images` and write `{{image:NAME}}` where each goes, and use system "
            "fonts."
        )
    return None


def image_problem(content: str, available: set[str]) -> str | None:
    """A `{{image:NAME}}` the drawing uses with no image of that name; `None` when all have one."""
    missing = sorted({name for name in IMAGE_TOKEN.findall(content) if name not in available})
    if not missing:
        return None
    return (
        f"The drawing uses {', '.join(f'{{{{image:{name}}}}}' for name in missing)} but "
        "`images` names no such image. Add each to `images` with its source, or remove it."
    )


def images_problem(images: list[VisualImage]) -> str | None:
    """Why this list of images is refused before anything is fetched; `None` when it is not."""
    if len(images) > MAX_IMAGES:
        return f"A drawing carries at most {MAX_IMAGES} images. Use fewer, or smaller ones."
    names = [image.name for image in images]
    for name in names:
        if re.fullmatch(IMAGE_NAME, name) is None:
            return (
                f"Image name {name!r} is not valid. Use 1-40 lower-case letters, digits, `-` "
                "and `_`, starting with a letter or digit, e.g. `logo`."
            )
    if len(set(names)) != len(names):
        return "Two images share a name. Give each its own."
    if any(not image.source.strip() for image in images):
        return (
            "An image has no `source`. Name the attached file, the workspace path or the address."
        )
    return None


DELEGATED = (
    "You are working for another agent, and a drawing made here is never shown to "
    "the person: it stays in this delegation. Say in your result what the drawing "
    "should show - the parts, the flow, the numbers - so the agent you work for can "
    "draw it in the conversation."
)
"""What `draw` and `revise_visual` answer in a delegated run - an answer, not a
retry: drawing again from the same delegation could never be seen either."""


@dataclass
class VisualsToolset:
    """The three tools, and which of this run's drawings actually returned."""

    web_reach: tuple[WebReach, ...] = ()
    """Where the agent's web readers may go. An image comes from an `https://` address
    only on a host one of them admits - see `_reach.py`."""

    drawn: set[str] = field(default_factory=set)
    """Ids of this run's calls that produced a visual, so a steered call is not one."""

    def build(self) -> FunctionToolset[AgentDeps]:
        toolset: FunctionToolset[AgentDeps] = FunctionToolset()
        toolset.add_function(self.draw, name=DRAW, takes_ctx=True)
        toolset.add_function(self.revise_visual, name=REVISE, takes_ctx=True)
        toolset.add_function(self.read_visual, name="read_visual", takes_ctx=True)
        return toolset

    async def draw(
        self,
        ctx: RunContext[AgentDeps],
        title: str,
        kind: Literal["svg", "html", "mermaid"],
        height: int,
        content: str,
        images: list[VisualImage] | None = None,
    ) -> str:
        """Draw a picture in the conversation: a diagram, a map, a flow, an explainer, a 3D scene.

        Use it whenever a picture explains the answer better than prose - an
        architecture, a process, a comparison, a timeline, how something moves - or the
        user asks for one. It renders live under your message while you write it, and
        stays in the conversation. For a plain chart of numbers you already have, use
        `create_chart` if you have it; for a page people should open, share and come back
        to, `publish_artifact`.

        Pick the `kind`:
        - `svg`: one `<svg>` element with a `viewBox`, for diagrams and illustrations. It
          grows on screen as you write it, so write it in reading order, background first.
        - `mermaid`: Mermaid source - `flowchart`, `sequenceDiagram`, `erDiagram`,
          `classDiagram`, `stateDiagram-v2`, `gantt`, `mindmap`, `timeline` - the
          shortest way to a correct flow or sequence.
        - `html`: a whole self-contained HTML document, for anything interactive -
          sliders, hover, tabs, `<canvas>`, WebGL. Its scripts run once the call is
          complete, so a half-written scene never starts.

        The frame has no network. No CDN, no `fetch`, no web fonts, no remote images,
        and use system fonts. A picture - a photo the person attached, an image in your
        workspace, a picture from the web - goes in `images` with a name, and the
        drawing uses it as `{{image:NAME}}` wherever a URL goes: `<img src="{{image:logo}}">`,
        an SVG `<image href="{{image:logo}}">`, or CSS `url({{image:logo}})`. The
        deployment serves a library set by relative path, free to use:
        - `<link rel="stylesheet" href="lib/agenticos-2.css">` - the product's look,
          light and dark, with `ao-` components;
        - `lib/chart-4.5.1.umd.min.js` (`window.Chart`), `lib/d3-7.9.0.min.js`
          (`window.d3`), `lib/lucide-1.46.0.min.js` (icons), `lib/agenticos-2.js`;
        - three.js as ES modules, through an import map placed before your module:
          `<script type="importmap">{"imports": {"three": "./lib/three-0.186.0/three.module.js",
          "three/addons/": "./lib/three-0.186.0/addons/"}}</script>`, then
          `import * as THREE from "three"` and
          `import { OrbitControls } from "three/addons/controls/OrbitControls.js"`.

        Make it read in light and dark (`prefers-color-scheme`, or `agenticos-2.css`) and
        at phone width. Before a first drawing, load the `visual-design` skill if it is
        available - it has the house style and worked templates.

        Args:
            title: What the drawing shows, in a few words, e.g. `Order flow`.
            kind: `svg`, `mermaid` or `html`, as above.
            height: How tall to start the frame, in pixels, 160-1200 - about 480 for a
                diagram, 600 for a scene. The frame then fits the drawing.
            content: The whole drawing. Up to the app size limit.
            images: Pictures the drawing uses, each with the `name` it is used by and its
                `source`: the file name of an image attached to this conversation, a path
                in your workspace, or an `https://` address when you can read the web. Up
                to 6, 2 MB each; PNG, JPEG, GIF, WebP, AVIF or SVG.

        Returns:
            A line naming the drawing and its visual id, and - when somebody is
            watching - how it rendered in their browser: cleanly, or the script
            errors, failed loads and refused requests to fix with `revise_visual`.
            The user is already looking at it: do not repeat its source or describe
            it at length. Pass the id to `read_visual` to read it back.
        """
        if ctx.deps.delegated:
            return DELEGATED
        found = visuals.visual_kind(kind)
        if found is None:
            return steer(ctx, "`kind` must be `svg`, `mermaid` or `html`.")
        if not title.strip():
            return steer(ctx, "`title` is empty. Say in a few words what the drawing shows.")
        problem = content_problem(found, content) or image_problem(
            content, {image.name for image in images or []}
        )
        if problem is not None:
            return steer(ctx, problem)
        visual_id = ctx.tool_call_id or ""
        try:
            await self._keep_images(ctx, visual_id, images or [])
        except VisualError as refused:
            return steer(ctx, str(refused))
        self.drawn.add(visual_id)
        checked = await _checked(ctx, visual_id)
        # Indexed once the call has an answer: a run stopped while the browser was
        # still reporting leaves no row for a visual the transcript never finished.
        await _index(ctx, visual_id, title=title.strip(), kind=found, revision_of=None)
        return f"Drew {title.strip()!r} as visual `{visual_id}`. {checked}"

    async def revise_visual(
        self,
        ctx: RunContext[AgentDeps],
        visual_id: str,
        edits: list[ArtifactEdit],
        title: str | None = None,
        images: list[VisualImage] | None = None,
    ) -> str:
        """Change a visual by exact replacements, without drawing it again.

        Use it for a correction or a small change to a visual in this conversation - a
        label, a colour, a missing step. The changed visual is shown as a new revision
        under your message, and the original stays where it was. For a different
        drawing, call `draw`. If you do not have the visual's current text in front of
        you, read it with `read_visual` first.

        Args:
            visual_id: The id a `draw` or `revise_visual` call returned.
            edits: Exact replacements, applied in order. Each `old` must appear exactly
                once in the visual as the edits before it left it.
            title: A new title; omit to keep the current one.
            images: Pictures to add, as for `draw`. The visual's own images stay
                available by their names; one of the same name replaces it.

        Returns:
            A line naming the revision and its own visual id, which later revisions
            build on, and how it rendered when somebody is watching. When an edit
            does not apply, what to fix.
        """
        if ctx.deps.delegated:
            return DELEGATED
        if not edits:
            return steer(ctx, "`edits` is empty. Pass at least one replacement.")
        try:
            base = await self._resolve(ctx, visual_id)
        except VisualError as missing:
            return steer(ctx, str(missing))
        try:
            content = apply_edits(base.content, edits)
        except ValueError as missed:
            return steer(ctx, f"{missed} Read it with `read_visual` to copy the text exactly.")
        added = images or []
        problem = content_problem(base.kind, content) or image_problem(
            content, set(base.images) | {image.name for image in added}
        )
        if problem is None and len(set(IMAGE_TOKEN.findall(content))) > MAX_IMAGES:
            problem = f"A drawing uses at most {MAX_IMAGES} images. Use fewer."
        if problem is not None:
            return steer(ctx, problem)
        revision_id = ctx.tool_call_id or ""
        try:
            await self._keep_images(ctx, revision_id, added)
        except VisualError as refused:
            return steer(ctx, str(refused))
        self.drawn.add(revision_id)
        shown = (title or "").strip() or base.title
        checked = await _checked(ctx, revision_id)
        await _index(ctx, revision_id, title=shown, kind=base.kind, revision_of=base.id)
        return f"Revised {shown!r} as visual `{revision_id}` (a revision of `{base.id}`). {checked}"

    async def read_visual(self, ctx: RunContext[AgentDeps], visual_id: str) -> str:
        """Read a visual in this conversation as it now is, revisions applied.

        Use it before `revise_visual` when the visual was drawn in an earlier turn, so
        each edit's `old` text is copied exactly.

        Args:
            visual_id: The id a `draw` or `revise_visual` call returned.

        Returns:
            A header line with the title, the kind and the size, then the source. A
            visual over 100,000 characters is cut there and the header says so; an edit
            can still name text past the cut.
        """
        try:
            found = await self._resolve(ctx, visual_id)
        except VisualError as missing:
            return steer(ctx, str(missing))
        shown = found.content[:READ_LIMIT]
        cut = (
            f" Showing the first {READ_LIMIT:,} of {len(found.content):,} characters."
            if len(found.content) > READ_LIMIT
            else ""
        )
        return (
            f"Visual `{found.id}` - {found.title!r}, {found.kind}, "
            f"{len(found.content):,} characters.{cut}\n\n{shown}"
        )

    async def _keep_images(
        self, ctx: RunContext[AgentDeps], visual_id: str, images: list[VisualImage]
    ) -> None:
        """Fetch, check and keep a drawing's images, and hand them to the watching console.

        Raises:
            VisualError: An image that is refused - its list, its source, its size or
                its type - in words the model can act on. Nothing is kept then.
        """
        if not images:
            return
        problem = images_problem(images)
        if problem is not None:
            raise VisualError(problem)
        organization_id = ctx.deps.organization_id
        conversation_id = await _conversation(ctx.deps)
        if organization_id is None or conversation_id is None:
            raise VisualError(
                "Images need a conversation to keep them in, and this run has none. Draw "
                "without `images`."
            )
        fetched: dict[str, tuple[bytes, str]] = {}
        for image in images:
            data = await self._image_bytes(ctx, conversation_id, image.source.strip())
            if len(data) > IMAGE_MAX_BYTES:
                raise VisualError(
                    f"Image {image.name!r} is {len(data):,} bytes, over the "
                    f"{IMAGE_MAX_BYTES:,}-byte limit. Use a smaller one."
                )
            media_type = visuals.image_type(data)
            if media_type is None:
                raise VisualError(
                    f"{image.source!r} is not an image this can show - PNG, JPEG, GIF, WebP, "
                    "AVIF or SVG."
                )
            fetched[image.name] = (data, media_type)
        for name, (data, _media_type) in fetched.items():
            await visuals.save_image(organization_id, conversation_id, visual_id, name, data)
        reports = ctx.deps.visual_reports
        if reports is not None and reports.send_images is not None:
            uris: Mapping[str, str] = {
                name: visuals.data_uri(data, media_type)
                for name, (data, media_type) in fetched.items()
            }
            await reports.send_images(visual_id, uris)

    async def _image_bytes(
        self, ctx: RunContext[AgentDeps], conversation_id: UUID, source: str
    ) -> bytes:
        """One image's bytes: from the web, an attachment of this thread, or the workspace.

        Raises:
            VisualError: The source names nothing that can be read, in words the
                model can act on.
        """
        if source.lower().startswith(("http://", "https://")):
            if not self.web_reach:
                raise VisualError(
                    "This agent cannot read the web, so it cannot fetch an image by address. "
                    "Use an image attached to the conversation or a file in your workspace."
                )
            host = urlsplit(source).hostname or ""
            if not any(reach.admits(host) for reach in self.web_reach):
                raise VisualError(
                    f"This agent may not read {host!r}, so it cannot fetch an image from there. "
                    "Use an image from a site it may read, one attached to the conversation, "
                    "or a file in your workspace."
                )
            try:
                # Pinned to the host just admitted, so a redirect cannot carry the
                # request somewhere the agent's readers may not go.
                response = await safe_download(
                    source,
                    max_bytes=IMAGE_MAX_BYTES,
                    timeout=IMAGE_DOWNLOAD_TIMEOUT,
                    allowed_domains=[host],
                )
            except (ValueError, httpx2.HTTPError) as failed:
                raise VisualError(f"{source!r} could not be downloaded: {failed}") from failed
            if response.status_code >= 400:
                raise VisualError(f"{source!r} answered {response.status_code}. Use another image.")
            return response.content
        attached = await visuals.attachment_bytes(conversation_id, source)
        if attached is not None:
            return attached
        if ctx.workspace.attached:
            try:
                return await ctx.workspace.read_bytes(source)
            except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                pass
            except PermissionError as refused:
                raise VisualError(f"Reading {source!r} was refused: {refused}") from refused
            except WorkspaceError as failed:
                raise VisualError(f"Reading {source!r} failed: {failed}") from failed
        raise VisualError(
            f"There is no image called {source!r} attached to this conversation"
            + (" or in your workspace." if ctx.workspace.attached else ".")
            + " Use the file name exactly as it was attached, or a workspace path."
        )

    async def _resolve(self, ctx: RunContext[AgentDeps], visual_id: str) -> visuals.Visual:
        """The visual behind an id: this run's own calls first, then the conversation's.

        Raises:
            VisualError: See :func:`visuals.rebuild`.
        """
        in_run = self._calls_in_run(ctx)
        conversation: list[UUID | None] = []

        async def lookup(call_id: str) -> ToolCallArgs | None:
            if call_id in in_run:
                return in_run[call_id]
            if not conversation:
                conversation.append(await _conversation(ctx.deps))
            if conversation[0] is None:
                raise VisualError(_NO_CONVERSATION)
            return await visuals.stored_call(conversation_id=conversation[0], tool_call_id=call_id)

        return await visuals.rebuild(visual_id, lookup)

    def _calls_in_run(self, ctx: RunContext[AgentDeps]) -> dict[str, ToolCallArgs]:
        """This run's visual calls that produced one, by id."""
        calls: dict[str, ToolCallArgs] = {}
        for message in ctx.messages:
            if not isinstance(message, ModelResponse):
                continue
            for part in message.parts:
                if (
                    isinstance(part, ToolCallPart)
                    and part.tool_name in VISUAL_TOOLS
                    and part.tool_call_id in self.drawn
                ):
                    calls[part.tool_call_id] = ToolCallArgs(
                        tool_call_id=part.tool_call_id,
                        tool_name=part.tool_name,
                        args=part.args_as_dict(),
                    )
        return calls


async def _checked(ctx: RunContext[AgentDeps], call_id: str) -> str:
    """What the person's browser said about the drawing, for the end of the tool's answer."""
    reports = ctx.deps.visual_reports
    if reports is None:
        # Not "under your message": where nobody watches the web chat, the person
        # sees it later, or as a picture in a chat app.
        return (
            "It is kept with the conversation and shown where the person reads it. "
            "Refer to it, do not repeat it."
        )
    report = await reports.wait(call_id, REPORT_TIMEOUT)
    if report is None:
        return (
            "It is shown under your message, but no browser reported how it rendered. "
            "Refer to it, do not repeat it."
        )
    if not report.errors:
        return (
            "It rendered in the person's browser without errors and is on screen under "
            "your message; refer to it, do not repeat it."
        )
    problems = "\n".join(f"- {error}" for error in report.errors)
    return (
        "It is on screen, but the person's browser reported errors while drawing it:\n"
        f"{problems}\n"
        "Fix them now with `revise_visual` on this id, or draw it again - then tell the "
        "person in one line what you changed."
    )


async def _index(
    ctx: RunContext[AgentDeps], visual_id: str, *, title: str, kind: str, revision_of: str | None
) -> None:
    """List the drawing for the person it was made for; a run outside a thread lists nothing."""
    deps = ctx.deps
    conversation_id = await _conversation(deps)
    if deps.organization_id is None or conversation_id is None:
        return
    await visuals.record_visual(
        organization_id=deps.organization_id,
        conversation_id=conversation_id,
        tool_call_id=visual_id,
        agent_id=deps.agent_id,
        user_id=UUID(deps.user_id) if deps.user_id else None,
        title=title,
        kind=kind,
        revision_of=revision_of,
    )


async def _conversation(deps: AgentDeps) -> UUID | None:
    if deps.run_id is None or deps.organization_id is None:
        return None
    return await visuals.conversation_of_run(
        run_id=deps.run_id, organization_id=deps.organization_id
    )
