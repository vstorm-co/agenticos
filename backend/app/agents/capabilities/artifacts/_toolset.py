"""The `publish_artifact` tool, and the text the model reads before calling it.

The page comes from one of two places: a file the agent built in its workspace
(the usual case - it writes `report.html`, runs whatever renders it, then
publishes the file), or content passed inline, for an agent with no workspace.
Either way the tool reads the bytes and hands them to
:func:`app.services.artifact.publish`, which owns identity, versions and storage.

Nothing the model passes chooses the organization, the agent or the owner: all
three come off `ctx.deps`, so the name is the only handle it has, and it is a
handle within this agent's own artifacts.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import ensure_async

from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.core.config import settings
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

_ONE_SOURCE = "Pass exactly one of `path` (a workspace file) or `content`."

_NO_AGENT = (
    "Publishing is not available here: this run has no saved agent to publish under. "
    "Tell the user the page could not be published, and give them the content instead."
)


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


def build_artifacts_toolset(*, workspace_backend: Any | None) -> FunctionToolset[AgentDeps]:
    """A `publish_artifact` tool, reading from the run's workspace when it has one."""

    async def publish_artifact(
        ctx: RunContext[AgentDeps],
        name: str,
        title: str,
        path: str | None = None,
        content: str | None = None,
        format: Literal["html", "markdown"] | None = None,  # noqa: A002 - the model's word for it
    ) -> str:
        """Publish a finished page - a report, a small dashboard, a summary - under a stable link.

        Use this when the result is something a person should *open*, share or come back
        to, rather than read once in the chat. Publishing again under the same `name`
        updates that page in place: the link stays the same and the previous version is
        kept, so reuse the name every time you refresh the same report. A new name makes
        a new page.

        The page must be self-contained. It is shown in an isolated frame with no network
        access: inline every script, stylesheet, font and image (as `data:` URIs), embed
        the data the page shows, and do not rely on a CDN or an API call - anything
        fetched from elsewhere will not load. Script runs, so charts drawn by an inlined
        library work. For tabular numbers you only want shown in the chat, use
        `create_chart` instead.

        Pass either `path` or `content`, not both.

        Args:
            name: The page's handle within this agent - lower-case letters, digits and
                hyphens, e.g. `weekly-sales-report`. Same name, same link.
            title: What the page is called where people find it, e.g.
                `Weekly sales - 22 Sep 2026`.
            path: A file in your workspace to publish, ending in `.html` or `.md`.
            content: The page itself, when you have no workspace or it is short.
            format: `html` or `markdown`. Inferred from `path`'s extension; for
                `content` it defaults to `html`.

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
        if path is not None and content is not None:
            return steer(ctx, _ONE_SOURCE)
        media_type = _media_type(path, format)
        # The enum first: it is a `StrEnum`, so a `str` check would match both.
        if not isinstance(media_type, ArtifactMediaType):
            return steer(ctx, media_type)

        if content is not None:
            data = content.encode("utf-8")
        elif path is None:
            return steer(ctx, _ONE_SOURCE)
        elif workspace_backend is None:
            return steer(
                ctx,
                "This agent has no workspace to read a file from. Pass the page as "
                "`content` instead.",
            )
        else:
            try:
                data = await ensure_async(workspace_backend).read_bytes(path)
            except PermissionError as exc:
                return f"Reading {path!r} was refused: {exc}"
            if not data:
                return steer(
                    ctx,
                    f"There is no file at {path!r}, or it is empty. Check the path with `ls`.",
                )

        problem = artifacts.publish_problem(name=name, media_type=media_type, data=data)
        if problem is not None:
            return steer(ctx, problem)
        clean_title = title.strip()[:200] or name

        published = await artifacts.publish(
            organization_id=deps.organization_id,
            agent_id=deps.agent_id,
            owner_user_id=UUID(deps.user_id) if deps.user_id else None,
            run_id=deps.run_id,
            name=name,
            title=clean_title,
            media_type=media_type,
            data=data,
        )
        return PublishedArtifactResult(
            artifact_id=published.artifact_id,
            version_id=published.version_id,
            version=published.version_number,
            name=published.name,
            title=published.title,
            url=f"{settings.FRONTEND_URL.rstrip('/')}"
            f"{artifacts.console_url_for(published.artifact_id)}",
            created=published.created,
            unchanged=published.unchanged,
            visibility=published.visibility,
            public=published.public,
        ).model_dump_json()

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(publish_artifact, takes_ctx=True)
    return toolset
