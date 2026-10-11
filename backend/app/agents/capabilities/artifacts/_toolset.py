"""The `publish_artifact` and `read_artifact` tools, and the text the model reads first.

The page comes from one of three places: a file the agent built in its workspace
(the usual case - it writes `report.html`, runs whatever renders it, then
publishes the file), content passed inline, for an agent with no workspace, or
edits to the version already published, so a small change does not cost the
whole document again in output tokens. Whichever it is, the tool reads the bytes
and hands them to :func:`app.services.artifact.publish`, which owns identity,
versions and storage.

Nothing the model passes chooses the organization, the agent, the environment or
the owner: all of them come off `ctx.deps` and the run row, so the name is the
only handle it has, and it is a handle within this agent's own artifacts - one
that reaches an existing page only when the run's person may open it (to read)
or edit it (to publish).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from app.agents.audience import RunAudience
from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.exceptions import AuthorizationError, ConcurrentChangeError, NotFoundError
from app.db.models.artifact import ArtifactMediaType
from app.services import artifact as artifacts

_FORMATS: dict[str, ArtifactMediaType] = {
    "html": ArtifactMediaType.HTML,
    "markdown": ArtifactMediaType.MARKDOWN,
}

_SUFFIXES: dict[str, ArtifactMediaType] = {
    ".html": ArtifactMediaType.HTML,
    ".htm": ArtifactMediaType.HTML,
    ".md": ArtifactMediaType.MARKDOWN,
    ".markdown": ArtifactMediaType.MARKDOWN,
}

_ONE_SOURCE = (
    "Pass exactly one of `path` (a workspace file), `content` (the whole page) or "
    "`edits` (changes to the page already published under this name)."
)

_NO_AGENT = (
    "Publishing is not available here: this run has no saved agent to publish under. "
    "Tell the user the page could not be published, and give them the content instead."
)
_NO_READER = (
    "Reading a published page is not available here: nobody is signed in on this "
    "surface, so there is no one the page could be opened for."
)

READ_LIMIT = 100_000
"""How much of a page `read_artifact` returns, in characters.

A page with an inlined library can be megabytes, and all of it would land in the
context. The start of a page is its structure and its styles; a longer page is cut
there and says so, and an edit can still name any exact text in the whole of it.
"""


class ArtifactEdit(BaseModel):
    """One exact replacement in the published page."""

    old: str = Field(
        min_length=1,
        description="Text that appears exactly once in the page, copied from `read_artifact`",
    )
    new: str = Field(description="What replaces it; empty to delete it")


class PublishedArtifactResult(BaseModel):
    """What `publish_artifact` returns - a reference the interface renders as a card."""

    kind: Literal["artifact"] = "artifact"
    artifact_id: UUID
    version_id: UUID
    version: int
    name: str
    title: str
    url: str
    created: bool
    unchanged: bool
    visibility: str
    public: bool


def parse_published_artifact(result: str) -> PublishedArtifactResult | None:
    """Parse a `publish_artifact` result back into a model, or `None` for any other text."""
    try:
        payload = PublishedArtifactResult.model_validate_json(result)
    except ValidationError:
        return None
    return payload if payload.kind == "artifact" else None


def _media_type(path: str | None, fmt: str | None) -> ArtifactMediaType | str:
    """The format to publish as, or the reason it cannot be told."""
    if fmt is not None:
        return _FORMATS[fmt]
    if path is None:
        return ArtifactMediaType.HTML
    found = _SUFFIXES.get(PurePosixPath(path).suffix.lower())
    if found is None:
        return (
            f"Cannot tell the format of {path!r} from its extension. Publish an `.html` or "
            "`.md` file, or pass `format`."
        )
    return found


def apply_edits(source: str, edits: list[ArtifactEdit]) -> str:
    """The page with every edit applied in order.

    Each `old` must occur exactly once in the page as the edits before it left it:
    not at all means the model is editing from a memory of the page rather than the
    page, and more than once means the edit does not say which one it means.

    Raises:
        ValueError: The first edit that does not name exactly one place, in words
            the model can act on.
    """
    text = source
    for number, edit in enumerate(edits, start=1):
        found = text.count(edit.old)
        if found == 0:
            raise ValueError(
                f"Edit {number}: its `old` text is not in the page. Copy it exactly from "
                "`read_artifact`, whitespace included."
            )
        if found > 1:
            raise ValueError(
                f"Edit {number}: its `old` text appears {found} times. Include more of the "
                "surrounding text so it names one place."
            )
        text = text.replace(edit.old, edit.new, 1)
    return text


def build_artifacts_toolset() -> FunctionToolset[AgentDeps]:
    """`publish_artifact` and `read_artifact`, reading from the run's workspace when it has one."""

    async def publish_artifact(
        ctx: RunContext[AgentDeps],
        name: str,
        title: str | None = None,
        path: str | None = None,
        content: str | None = None,
        edits: list[ArtifactEdit] | None = None,
        format: Literal["html", "markdown"] | None = None,  # noqa: A002 - the model's word for it
    ) -> str:
        """Publish a finished page - a report, a small dashboard, a summary - under a stable link.

        Use this when the result is something a person should *open*, share or come back
        to, rather than read once in the chat. Publishing again under the same `name`
        updates that page in place: the link stays the same and the previous version is
        kept, so reuse the name every time you refresh the same report. A new name makes
        a new page. To change part of a page you published, read it with `read_artifact`
        and pass `edits` rather than the whole page again.

        The page must be self-contained. It is shown in an isolated frame with no network
        access: inline your data, images (as `data:` URIs) and any script of your own, and
        do not rely on a CDN or an API call - anything fetched from elsewhere will not
        load. The deployment serves a small library set the page may load by a relative
        address, which costs nothing to include:
        `<link rel="stylesheet" href="lib/agenticos-2.css">` (the product's look, light
        and dark, with `ao-` components), `lib/chart-4.5.1.umd.min.js` (Chart.js,
        `window.Chart`), `lib/d3-7.9.0.min.js` (d3, `window.d3`),
        `lib/lucide-1.46.0.min.js` (icons: write `<i data-lucide="calendar"></i>`) and,
        after those, `lib/agenticos-2.js` (`window.AO`: chart defaults in the product's
        style, number formatting, icons, tabs); `lib/agenticos-1.css` stays served for
        pages published against it. Keep to the product's look: graphite,
        no accent colour, green and red only for better and worse, icons rather than
        emoji unless the person asked for emoji. Before building a page, load the
        `artifact-pages` skill if it is available - it has the components and two
        templates. Links to other sites work: the person is asked before one opens.
        For tabular numbers you only want shown in the chat, use `create_chart` instead.

        Pass exactly one of `path`, `content` or `edits`.

        Args:
            name: The page's handle within this agent - lower-case letters, digits and
                hyphens, e.g. `weekly-sales-report`. Same name, same link.
            title: What the page is called where people find it, e.g.
                `Weekly sales - 22 Sep 2026`. Omit to keep the current title, or to use
                the name for a new page.
            path: A file in your workspace to publish, ending in `.html` or `.md`.
            content: The whole page, when you have no workspace or it is short.
            edits: Exact replacements in the page already published under `name`, applied
                in order. Each `old` must appear exactly once.
            format: `html` or `markdown`. Inferred from `path`'s extension; for
                `content` it defaults to `html`. An edit keeps the page's format.

        Returns:
            A JSON reference to the published page - its `url`, the `version` number,
            whether it was `created` or updated, and `unchanged` when the content was
            identical to the current version (nothing new was stored). The interface
            shows the user a card with the link; tell them in one line what you
            published. New pages are private to the person this run is for until they
            share it.
        """
        deps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return _NO_AGENT
        if sum(source is not None for source in (path, content, edits)) > 1:
            return steer(ctx, _ONE_SOURCE)
        owner_user_id = UUID(deps.user_id) if deps.user_id else None
        expected_version: int | None = None

        if edits is not None:
            if not edits:
                return steer(ctx, "`edits` is empty. Pass at least one replacement.")
            try:
                source = await artifacts.read_source(
                    organization_id=deps.organization_id,
                    agent_id=deps.agent_id,
                    reader_user_id=owner_user_id,
                    run_id=deps.run_id,
                    name=name,
                )
            except NotFoundError as missing:
                # One answer for "no such page" and "not yours to open", as the console
                # gives; a refusal, so returned rather than steered.
                return f"{missing.message} Publish it with `content` or `path` instead."
            if format is not None and _FORMATS[format] != source.media_type:
                return steer(ctx, "An edit keeps the page's format. Leave `format` out.")
            try:
                data = apply_edits(source.text, edits).encode("utf-8")
            except ValueError as missed:
                return steer(ctx, str(missed))
            media_type = source.media_type
            expected_version = source.version_number
        else:
            found = _media_type(path, format)
            # The enum first: it is a `StrEnum`, so a `str` check would match both.
            if not isinstance(found, ArtifactMediaType):
                return steer(ctx, found)
            media_type = found
            if content is not None:
                data = content.encode("utf-8")
            elif path is None:
                return steer(ctx, _ONE_SOURCE)
            elif not ctx.workspace.attached:
                return steer(
                    ctx,
                    "This agent has no workspace to read a file from. Pass the page as "
                    "`content` instead.",
                )
            else:
                try:
                    data = await ctx.workspace.read_bytes(path)
                except PermissionError as exc:
                    return f"Reading {path!r} was refused: {exc}"
                except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                    data = b""
                except WorkspaceError as exc:
                    # A container's shell could not produce the file - the
                    # session went away, its output came back damaged. The
                    # model can retry or publish inline; the run goes on.
                    return f"Reading {path!r} failed: {exc}"
                if not data:
                    return steer(
                        ctx,
                        f"There is no file at {path!r}, or it is empty. Check the path with `ls`.",
                    )

        problem = artifacts.publish_problem(name=name, media_type=media_type, data=data)
        if problem is not None:
            return steer(ctx, problem)
        clean_title = title.strip()[:200] if title is not None else None

        try:
            published = await artifacts.publish(
                organization_id=deps.organization_id,
                agent_id=deps.agent_id,
                owner_user_id=owner_user_id,
                run_id=deps.run_id,
                name=name,
                title=clean_title or None,
                media_type=media_type,
                data=data,
                expected_version=expected_version,
            )
        except AuthorizationError as refused:
            # A refusal, so returned rather than steered: the name is somebody
            # else's page, and the model picks another one or says so.
            return refused.message
        except ConcurrentChangeError as moved:
            return steer(ctx, moved.message)
        return PublishedArtifactResult(
            artifact_id=published.artifact_id,
            version_id=published.version_id,
            version=published.version_number,
            name=published.name,
            title=published.title,
            url=f"{settings.FRONTEND_URL.rstrip('/')}"
            f"{artifacts.console_url_for(published.artifact_id, published.organization_id)}",
            created=published.created,
            unchanged=published.unchanged,
            visibility=published.visibility,
            public=published.public,
        ).model_dump_json()

    async def read_artifact(ctx: RunContext[AgentDeps], name: str) -> str:
        """Read the current version of a page this agent published, as it was written.

        Use this before changing part of a published page, then pass `edits` to
        `publish_artifact` with text copied exactly from what this returns. Not for
        answering a question about the page's numbers - rebuild those from the data.

        Args:
            name: The page's handle, as it was published - e.g. `weekly-sales-report`.

        Returns:
            A header line with the version, the format and the size, then the page's
            source. A page over 100,000 characters is cut there and the header says so;
            an edit can still name text past the cut. When there is no page of that
            name this run may open, a sentence saying so.
        """
        deps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return _NO_AGENT
        # Read as the person listening, never as `user_id`: on a public widget or
        # an embed that is the publisher standing in for an anonymous visitor, who
        # could otherwise have any page the publisher may open read out to them.
        reader = (deps.audience or RunAudience()).user_id
        if reader is None:
            return _NO_READER
        try:
            source = await artifacts.read_source(
                organization_id=deps.organization_id,
                agent_id=deps.agent_id,
                reader_user_id=reader,
                run_id=deps.run_id,
                name=name,
            )
        except NotFoundError as missing:
            return missing.message
        shown = source.text[:READ_LIMIT]
        cut = (
            f" Showing the first {READ_LIMIT:,} of {len(source.text):,} characters."
            if len(source.text) > READ_LIMIT
            else ""
        )
        header = (
            f"`{source.name}` - {source.title!r}, version {source.version_number}, "
            f"{_extension(source.media_type)}, {len(source.text):,} characters.{cut}"
        )
        return f"{header}\n\n{shown}"

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(publish_artifact, takes_ctx=True)
    toolset.add_function(read_artifact, takes_ctx=True)
    return toolset


def _extension(media_type: ArtifactMediaType) -> str:
    return "HTML" if media_type == ArtifactMediaType.HTML else "Markdown"
