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
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities.artifacts._toolset import ArtifactEdit, apply_edits
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.repositories.conversation import ToolCallArgs
from app.services import visual as visuals
from app.services.visual import DRAW, REVISE, VISUAL_TOOLS, VisualError, VisualKind

READ_LIMIT = 100_000
"""How much of a visual `read_visual` returns, in characters - `read_artifact`'s cut."""


# Leading XML declaration, comments and whitespace, then the element itself.
_SVG_START = re.compile(
    r"\A\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*<svg[\s>]", re.DOTALL | re.IGNORECASE
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
            "would not load. Use the served library set by its relative path (`lib/...`), and "
            "inline images as `data:` URIs and fonts as system fonts."
        )
    return None


@dataclass
class VisualsToolset:
    """The three tools, and which of this run's drawings actually returned."""

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

        The frame has no network. No CDN, no `fetch`, no web fonts, no remote images:
        inline images as `data:` URIs and use system fonts. The deployment serves a
        library set by relative path, free to use:
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
            content: The whole drawing, written last. Up to the app size limit.

        Returns:
            A line naming the drawing and its visual id, and - when somebody is
            watching - how it rendered in their browser: cleanly, or the script
            errors, failed loads and refused requests to fix with `revise_visual`.
            The user is already looking at it: do not repeat its source or describe
            it at length. Pass the id to `read_visual` to read it back.
        """
        found = visuals.visual_kind(kind)
        if found is None:
            return steer(ctx, "`kind` must be `svg`, `mermaid` or `html`.")
        if not title.strip():
            return steer(ctx, "`title` is empty. Say in a few words what the drawing shows.")
        problem = content_problem(found, content)
        if problem is not None:
            return steer(ctx, problem)
        visual_id = ctx.tool_call_id or ""
        self.drawn.add(visual_id)
        checked = await _checked(ctx, visual_id)
        return f"Drew {title.strip()!r} as visual `{visual_id}`. {checked}"

    async def revise_visual(
        self,
        ctx: RunContext[AgentDeps],
        visual_id: str,
        edits: list[ArtifactEdit],
        title: str | None = None,
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

        Returns:
            A line naming the revision and its own visual id, which later revisions
            build on, and how it rendered when somebody is watching. When an edit
            does not apply, what to fix.
        """
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
        problem = content_problem(base.kind, content)
        if problem is not None:
            return steer(ctx, problem)
        revision_id = ctx.tool_call_id or ""
        self.drawn.add(revision_id)
        shown = (title or "").strip() or base.title
        checked = await _checked(ctx, revision_id)
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
        return "It is shown under your message; refer to it, do not repeat it."
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


async def _conversation(deps: AgentDeps) -> UUID | None:
    if deps.run_id is None or deps.organization_id is None:
        return None
    return await visuals.conversation_of_run(
        run_id=deps.run_id, organization_id=deps.organization_id
    )
