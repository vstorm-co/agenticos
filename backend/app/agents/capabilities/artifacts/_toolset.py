"""The artifact tools - publish, read back, list, preview and ask to share - and the text the model reads first.

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

import logging
from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.messages import BinaryContent, ToolReturn
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from app.agents.audience import RunAudience
from app.agents.capabilities._failures import steer
from app.agents.deps import AgentDeps
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
)
from app.db.models.artifact import ArtifactMediaType, ConsentState
from app.db.models.resource_grant import Visibility
from app.schemas.artifact import (
    ActionDisclosure,
    ActionRequest,
    BindingData,
    BindingDisclosure,
    BindingRequest,
)
from app.services.artifact_lint import lint_page

if TYPE_CHECKING:
    from app.services.artifact import ArtifactPreview, PublishedArtifact
    from app.services.artifact_render import Rendered

logger = logging.getLogger(__name__)

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
_NO_LISTER = (
    "Listing published pages is not available here: nobody is signed in on this "
    "surface, so there is no one the pages could be opened for."
)
_NO_SHARER = (
    "Sharing a page is not available here: no signed-in person is behind this run, so "
    "there is nobody who could ask for it. Tell the user to share the page from its Share "
    "dialog in the console."
)
_NO_SHARE_ARGUMENTS = "Pass `visibility`, `people`, or both: there is nothing to share."
_NO_PREVIEWER = (
    "Previewing a published page is not available here: nobody is signed in on this "
    "surface, so there is no one the page could be opened for."
)
_NO_RENDERER = (
    "Screenshot: not available on this deployment - it has no page renderer, so the "
    "page was checked without being drawn."
)
_NO_IMAGES = (
    "Screenshot: not attached - this agent is set up for a model that does not read images."
)

PAGES_GUIDE = "artifact-pages"
"""The bundled skill that holds the page templates and every kit component.

A skill reaches a run as a deferred capability whose id is the skill's name, so
this is also the id `load_capability` takes."""

_LOAD_THE_GUIDE = (
    f"Before publishing a new page, load the `{PAGES_GUIDE}` guide with "
    f"`load_capability` (id `{PAGES_GUIDE}`), rebuild the page from its template and "
    "components, then publish again under the same name."
)

PAGE_CONTRACT = f"""\
Every HTML page you publish with `publish_artifact` follows this contract.

Skeleton, in this order:
<!doctype html>
<html lang="en">  <!-- the reader's language -->
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What and when</title>
<link rel="stylesheet" href="lib/agenticos-3.css">
<script src="lib/chart-4.5.1.umd.min.js"></script>  <!-- only with a chart -->
<script src="lib/lucide-1.46.0.min.js"></script>
<script src="lib/agenticos-3.js"></script>
</head>
<body><main class="ao-page">
<header class="ao-header"><div>
<div class="ao-eyebrow">Label</div>
<h1>Title</h1>
<p class="ao-subtitle">The answer in one sentence</p>
<div class="ao-meta"><span><i data-lucide="calendar"></i>Period</span></div>
</div></header>
<section class="ao-section">...</section>
</main></body></html>

Rules:
- Classes: the kit's only, plus inline styles. The common ones - ao-page, ao-page-narrow, ao-header, \
ao-header-actions, ao-eyebrow, ao-subtitle, ao-meta, ao-section, ao-section-header, \
ao-section-title, ao-section-desc, ao-grid-2, ao-grid-3, ao-grid-4, ao-card, ao-card-header, \
ao-card-title, ao-card-flush, ao-stat, ao-stat-label, ao-stat-value, ao-stat-foot, ao-delta, \
ao-up, ao-down, ao-table-wrap, ao-table, ao-num, ao-strong, ao-badge, ao-badge-success, \
ao-badge-warning, ao-badge-danger, ao-callout, ao-kv, ao-empty, ao-loading, ao-note, ao-muted, \
ao-chart, ao-footer. Any other class in the `{PAGES_GUIDE}` guide's class table is fine \
too; never one outside the kit.
- A table is `table.ao-table` inside `div.ao-table-wrap`, with `<thead>` and `<tbody>`; \
`ao-num` on the `th` and every `td` of a number column, nowhere else.
- Icons are `<i data-lucide="name"></i>` with Lucide names, never emoji unless asked for.
- Bound data: `agenticos.onData(function (data) {{ AO.records("#id", data.<binding>); }})` \
draws a binding as a finished table with its loading, empty and unavailable states. Write \
record text with `textContent`, never `innerHTML`.
- When `{PAGES_GUIDE}` is listed as a capability to load, load it before your first page: \
it has the templates and every component.
"""
"""What a page must look like, in the system prompt of every Artifacts agent.

Static, so it stays in the cached prefix; short, because it is paid on every
request. The skill holds the rest, and `tests/test_artifacts_capability.py` holds
every class named here to `agenticos-3.css`."""

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
    bindings: dict[str, BindingDisclosure | Literal["kept"]] = Field(
        default_factory=dict,
        description="Each binding's page query in words, or `kept` when carried unchanged",
    )
    actions: list[ActionDisclosure] | Literal["kept"] = Field(
        default_factory=list,
        description="The workflows the page may start, or `kept` when carried unchanged",
    )
    consent: Literal["not_needed", "pending", "consented", "declined", "withdrawn"] = Field(
        default="not_needed",
        description="Where the version's data stands with the page's owner",
    )
    audience: str | None = Field(
        default=None,
        description="What everyone else who opens the page sees while this version waits",
    )
    warning: str | None = Field(
        default=None,
        description="What to fix in the published page, one problem per line, if anything",
    )


class ListedPage(BaseModel):
    """One page in `list_artifacts`' answer."""

    name: str
    title: str
    version: int
    format: Literal["html", "markdown"]
    live: bool
    bindings: list[str]
    visibility: str
    public: bool
    published_at: datetime
    url: str
    may_edit: bool


class PageList(BaseModel):
    """What `list_artifacts` returns."""

    pages: list[ListedPage]
    total: int


def _guide_unloaded(ctx: RunContext[AgentDeps]) -> bool:
    """Whether the run offers the page guide as a skill to load, and it is not loaded."""
    guide = ctx.capabilities.get(PAGES_GUIDE)
    return (
        guide is not None
        and guide.defer_loading is True
        and PAGES_GUIDE not in ctx.active_capability_ids
    )


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


def build_artifacts_toolset(
    *,
    table_grants: Mapping[UUID, frozenset[str]],
    workflow_ids: frozenset[UUID] = frozenset(),
    screenshot: bool = True,
) -> FunctionToolset[AgentDeps]:
    """The artifact tools, `publish_artifact` reading from the run's workspace when it has one.

    `table_grants` is what the agent's spec grants in each Virtual Table; a page binding
    needs read on its table there. `screenshot` is whether `preview_artifact` hands the
    model its picture. The toolset is built once per run, so `guided` - whether this
    run was already sent to the page guide - is per run too.
    """
    guided = False

    async def publish_artifact(
        ctx: RunContext[AgentDeps],
        name: str,
        title: str | None = None,
        path: str | None = None,
        content: str | None = None,
        edits: list[ArtifactEdit] | None = None,
        format: Literal["html", "markdown"] | None = None,  # noqa: A002 - the model's word for it
        bindings: dict[str, BindingRequest] | None = None,
        actions: list[ActionRequest] | None = None,
    ) -> str:
        """Publish a finished page - a report, a small dashboard, a summary - under a stable link.

        Use this when the result is something a person should *open*, share or come back
        to, rather than read once in the chat. Publishing again under the same `name`
        updates that page in place: the link stays the same and the previous version is
        kept, so reuse the name every time you refresh the same report. A new name makes
        a new page, so before choosing one, check `list_artifacts` for a page of yours
        that this should update instead. To change part of a page you published, read it
        with `read_artifact` and pass `edits` rather than the whole page again.

        The page is shown in an isolated frame with no network access: it cannot fetch
        anything, so images go in as `data:` URIs and scripts inline, and a CDN or an API
        call will not load. For records that should stay current, bind the page to table
        queries with `bindings` instead of copying the records in: an HTML page then
        calls `agenticos.onData(render)`, and `render(data)` runs with
        `data.<binding>` = `{status: "ok" | "unavailable", records: [{id, <field>: value}],
        fields: {<field>: {label, type, options, state}}, count, truncated, limit}` each
        time the page is loaded or refreshed. Everyone who opens the page reads the same
        records, read with its owner's access - bind only what all of them may see. Draw
        an `unavailable` binding as "no data"; when `truncated` is true, say the list is
        cut (`limit` is `records` or `bytes`). Write record text with `textContent`,
        never `innerHTML`. Data you only need once still goes inline. The deployment serves a
        small library set the page may load by a relative address, which costs nothing
        to include:
        `<link rel="stylesheet" href="lib/agenticos-3.css">` (the product's look, light
        and dark, with `ao-` components), `lib/chart-4.5.1.umd.min.js` (Chart.js,
        `window.Chart`), `lib/d3-7.9.0.min.js` (d3, `window.d3`),
        `lib/lucide-1.46.0.min.js` (icons: write `<i data-lucide="calendar"></i>`) and,
        after those, `lib/agenticos-3.js` (`window.AO`: chart defaults in the product's
        style, number formatting, icons, tabs, and `AO.records(target, data.<binding>)`,
        which draws bound records as a finished table). `lib/agenticos-2.css`,
        `lib/agenticos-2.js` and `lib/agenticos-1.css` stay served for pages published
        against them; build new pages on version 3. Follow the page contract in your
        instructions: doctype and viewport, `main.ao-page`, the header, only the kit's
        classes, tables with `<thead>`. Keep to the product's look: graphite,
        no accent colour, green and red only for better and worse, icons rather than
        emoji unless the person asked for emoji. Before building a page, load the
        `artifact-pages` skill if it is listed - it has the templates and every
        component. Links to other sites work: the person is asked before one opens.
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
            bindings: Live data for an HTML page, as `{name: query}`. A query names a
                `table` (id or exact name, from `list_tables`) or a saved `view` (id or
                exact name, from `list_views`), whose filters and sort are copied - later
                edits to the view change nothing. `fields` maps each name the page reads
                to a column, by id or label. Optional: `filters` (`[{column, op, value}]`,
                all must hold, added to the view's; a choice by its label), `sort`
                (`{by, direction}`) and `limit` (at most and by default 1,000), which
                replace the view's. E.g. `{"tickets": {"view": "Open tickets", "fields":
                {"status": "Status"}, "limit": 50}}`. Binding names are lower-case letters,
                digits and `_`; a field may be named as its column is labelled (`Status`,
                `Created At`). Omit to keep the page's current bindings - the usual case
                when changing a page's look. `{}` removes them.
            actions: Workflows a member may start from the page, at most 5, as
                `[{"workflow": id or exact name, "label": "Approve"}]`. Only workflows
                from `list_workflows` (bound to this agent) that start from a Manual or
                API trigger, and that the person you act for may run. The member confirms
                every run. Omit to keep the current ones; `[]` removes them. Needs a
                person behind the run.

        Returns:
            A JSON reference to the published page - its `url`, the `version` number,
            whether it was `created` or updated, `unchanged` when the content and
            bindings were identical to the current version (nothing new was stored), and
            `bindings`: each query in words - its `table`, `filters`, `sort`, `limit` and
            each field and what it reads (`Status (single_select)`, `Pay band: formula
            over Salary, Level`) - or `kept` for one carried from the previous version.
            Check it is what you meant: it is what everyone who opens the page reads. A
            `warning`, when present, lists what looks wrong in the page, one problem per
            line: fix each and publish again. The interface shows the user a card with
            the link; tell them in one line what you published. New pages are private to
            the person this run is for until they share it. `consent` says whether the
            page's owner has agreed to share this version's data: `pending` means
            everyone else still sees what `audience` says until the owner confirms it in
            the console - tell the person so. `actions` lists each declared workflow by its
            name and label, or `kept`.
        """
        # Function-local: `app.services.artifact` imports virtual tables, which reach this
        # package through the factory (an import cycle).
        from app.services import artifact as artifacts

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
        warnings: list[str] = []
        # Once per run, and only for a whole page: an edit changes a page that
        # already exists. On the last attempt a steer would end the call without
        # publishing, so the page goes out and the advice rides along instead.
        nonlocal guided
        if (
            edits is None
            and media_type == ArtifactMediaType.HTML
            and not guided
            and _guide_unloaded(ctx)
        ):
            guided = True
            if not ctx.last_attempt:
                return steer(ctx, _LOAD_THE_GUIDE)
            warnings.append(_LOAD_THE_GUIDE)
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
                bindings=bindings,
                run_person=deps.run_person,
                impersonated=deps.impersonated,
                table_grants=table_grants,
                actions=actions,
                workflow_ids=workflow_ids,
            )
        except AuthorizationError as refused:
            # A refusal, so returned rather than steered: the name is somebody
            # else's page, or a page reading live data and nobody behind this run,
            # and the model picks another name or says so.
            return refused.message
        except (BadRequestError, ConcurrentChangeError) as fixable:
            return steer(ctx, fixable.message)
        if media_type == ArtifactMediaType.HTML:
            warnings = lint_page(data, bound=published.bindings) + warnings
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
            bindings=published.bindings,
            actions="kept" if isinstance(published.actions, str) else published.actions,
            consent=published.consent.value,
            audience=_audience_note(published),
            warning="\n".join(warnings) or None,
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
        # Function-local: `app.services.artifact` imports virtual tables, which reach this
        # package through the factory (an import cycle).
        from app.services import artifact as artifacts

        deps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return _NO_AGENT
        # Read as the person listening, never as `user_id`: on a public widget or
        # an embed that is the publisher standing in for an anonymous visitor, who
        # could otherwise have any page the publisher may open read out to them.
        audience = deps.audience or RunAudience()
        reader = audience.user_id
        if reader is None:
            return _NO_READER
        try:
            source = await artifacts.read_source(
                organization_id=deps.organization_id,
                agent_id=deps.agent_id,
                reader_user_id=reader,
                run_id=deps.run_id,
                name=name,
                room=not audience.private,
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

    async def list_artifacts(ctx: RunContext[AgentDeps]) -> str:
        """List the pages this agent published that this run may open, newest first.

        Use before publishing under a name you have not used in this conversation, to
        find a page that should be updated instead of a new one made beside it, and
        to find a page's name for `read_artifact` or `preview_artifact`. In a group
        chat only organization-wide pages are listed.

        Returns:
            JSON: `pages`, newest publication first, each with its `name`, `title`,
            current `version`, `format` (`html` or `markdown`), `live` and the names of
            its `bindings`, `visibility` (`private`, `team` or `org`), `public` (a
            public link is on), `published_at`, its console `url`, and `may_edit` -
            whether publishing under that name from this run updates it rather than
            being refused. At most 50 are listed; `total` says how many there are.
            When nobody is signed in on this surface, a sentence saying so.
        """
        # Function-local: `app.services.artifact` imports virtual tables, which reach this
        # package through the factory (an import cycle).
        from app.services import artifact as artifacts

        deps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return _NO_AGENT
        # Read as the person listening, as `read_artifact` reads; `may_edit` as the
        # identity a publish is checked as.
        audience = deps.audience or RunAudience()
        if audience.user_id is None:
            return _NO_LISTER
        listing = await artifacts.list_for_run(
            organization_id=deps.organization_id,
            agent_id=deps.agent_id,
            reader_user_id=audience.user_id,
            editor_user_id=UUID(deps.user_id) if deps.user_id else None,
            run_id=deps.run_id,
            room=not audience.private,
        )
        origin = settings.FRONTEND_URL.rstrip("/")
        return PageList(
            pages=[
                ListedPage(
                    name=item.name,
                    title=item.title,
                    version=item.version_number,
                    format="html" if item.media_type == ArtifactMediaType.HTML else "markdown",
                    live=bool(item.bindings),
                    bindings=item.bindings,
                    visibility=item.visibility,
                    public=item.public,
                    published_at=item.published_at,
                    url=f"{origin}{item.console_path}",
                    may_edit=item.may_edit,
                )
                for item in listing.items
            ],
            total=listing.total,
        ).model_dump_json()

    async def share_artifact(
        ctx: RunContext[AgentDeps],
        name: str,
        visibility: Literal["team", "org"] | None = None,
        people: list[str] | None = None,
    ) -> str:
        """Ask for a page you published to be shared with more people; this shares nothing itself.

        The request waits for the page's owner to approve it in the console, even when the
        person asking is the owner. Use when the person asks to share a page - with their
        team, the whole organization, or named colleagues or groups. Tell them it still needs approval, and by whom.
        Not for a public link: that is only ever set up in the console.

        Args:
            name: The page's handle, as it was published - e.g. `weekly-sales-report`.
            visibility: `team` or `org` to let everyone on the team, or in the organization,
                open it. Leave out to leave visibility as it is.
            people: Colleagues, by full name or email address, and groups, by name, to
                give view access. A name that matches nobody or several is reported, not
                guessed.

        Returns:
            A sentence naming who must approve the request, in the page's Share dialog,
            and what it asks for; then any names it could not match, and anything the
            page was shared with already. When there is nothing left to ask for, a
            sentence saying so. When there is no page of that name this run may open,
            this person may not change its sharing, or nobody is signed in, a sentence
            saying so.
        """
        # Function-local: `app.services.artifact` imports virtual tables, which reach this
        # package through the factory (an import cycle).
        from app.services import artifact as artifacts

        deps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return _NO_AGENT
        if deps.run_person is None:
            return _NO_SHARER
        if visibility is None and not people:
            return steer(ctx, _NO_SHARE_ARGUMENTS)
        try:
            shared = await artifacts.request_share(
                organization_id=deps.organization_id,
                agent_id=deps.agent_id,
                run_person=deps.run_person,
                run_id=deps.run_id,
                name=name,
                visibility=Visibility(visibility) if visibility is not None else None,
                people=people or [],
                room=not (deps.audience or RunAudience()).private,
            )
        except (NotFoundError, AuthorizationError, ConflictError, RateLimitError) as refused:
            return refused.message
        lines = [
            f"Waiting for {shared.waiting_for or 'an Owner or Admin'} to approve in the "
            f"page's Share dialog: `{shared.name}` would be shared with "
            f"{', '.join(shared.asked)}."
            if shared.filed
            else f"Nothing to ask for: `{shared.name}` is shared that widely already."
        ]
        if shared.already and shared.filed:
            lines.append(f"Already shared with {', '.join(shared.already)}.")
        if shared.unknown:
            lines.append(f"No member or group is named {', '.join(map(repr, shared.unknown))}.")
        if shared.ambiguous:
            lines.append(
                f"More than one member or group is named {', '.join(map(repr, shared.ambiguous))}"
                "; name a group by its exact name, or a person by email address."
            )
        return " ".join(lines)

    async def preview_artifact(ctx: RunContext[AgentDeps], name: str) -> str | ToolReturn:
        """See a page you published as somebody opening it would: a picture, and what went wrong.

        Use after publishing or changing an HTML page, before telling the person it is
        done, and whenever they say it looks wrong. The page is drawn 1280 pixels wide,
        with the live data the person this run is for would be served (in a group
        chat, or for a run nobody answers for, without data), and checked as `publish_artifact` checks it. Fix what the
        report names, publish again and preview once more. Not for reading the page's
        source - that is `read_artifact`.

        Args:
            name: The page's handle, as it was published - e.g. `weekly-sales-report`.

        Returns:
            A text report: the version drawn and the picture's size; each binding's
            data - records, cut, or unavailable and why; whether the page asked for
            its data; uncaught errors with their line, console errors and warnings,
            what the page's security policy refused, requests refused (a page loads
            nothing but itself and the library set) and dialogs dismissed - at most
            10 of each; then the problems `publish_artifact` warns about. The picture
            follows as an image, at most 2400 pixels tall. Without a renderer on this
            deployment, for a model set up without images, or for a page still
            running after 15 seconds, the report says so and comes without it. When
            there is no page of that name this run may open, a sentence saying so.
        """
        # Function-local, as above; and the renderer imports the artifact service.
        from app.services import artifact as artifacts
        from app.services import artifact_render as renderer

        deps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return _NO_AGENT
        audience = deps.audience or RunAudience()
        if audience.user_id is None:
            return _NO_PREVIEWER
        try:
            preview = await artifacts.preview_source(
                organization_id=deps.organization_id,
                agent_id=deps.agent_id,
                reader_user_id=audience.user_id,
                run_id=deps.run_id,
                name=name,
                room=not audience.private,
                has_person=deps.run_person is not None,
            )
        except NotFoundError as missing:
            return missing.message
        drawn: Rendered | None = None
        try:
            drawn = await renderer.render(
                renderer.RenderRequest(
                    document=preview.document,
                    nonce=preview.nonce,
                    bindings=preview.bindings,
                    injected_lines=preview.injected_lines,
                )
            )
        except ConfigurationError as absent:
            logger.info("artifact_preview_without_renderer", extra={"reason": absent.message})
            outcome = _NO_RENDERER
        except ExternalServiceError as failed:
            outcome = f"Screenshot: not taken - {failed.message}"
        else:
            outcome = _drawn_outcome(drawn, screenshot=screenshot)
        problems = (
            lint_page(preview.source, bound=preview.binding_names)
            if preview.media_type == ArtifactMediaType.HTML
            else []
        )
        report = _preview_report(preview, drawn, problems=problems, outcome=outcome)
        if drawn is None or drawn.image is None or not screenshot:
            return report
        return ToolReturn(
            return_value=report,
            content=[
                f"`{preview.name}`, version {preview.version_number}, as drawn:",
                BinaryContent(data=drawn.image, media_type="image/jpeg"),
            ],
        )

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(publish_artifact, takes_ctx=True)
    toolset.add_function(read_artifact, takes_ctx=True)
    toolset.add_function(list_artifacts, takes_ctx=True)
    toolset.add_function(preview_artifact, takes_ctx=True)
    toolset.add_function(share_artifact, takes_ctx=True)
    return toolset


def _audience_note(published: PublishedArtifact) -> str | None:
    """What the audience sees while a version waits for its owner's consent, in a sentence.

    Names the owner, and the version the audience still sees - or that it sees nothing.
    """
    if published.consent in (ConsentState.CONSENTED, ConsentState.NOT_NEEDED):
        return None
    owner = published.owner_name or "the page's owner"
    if published.audience_version is None:
        return (
            "Only its owner, its editors and the roles that open every page (Owner, Admin, "
            f"Builder, Operator) can open this page until {owner} confirms its data in the console."
        )
    return (
        f"The audience still sees v{published.audience_version} until {owner} confirms this "
        "version's data in the console."
    )


def _drawn_outcome(drawn: Rendered, *, screenshot: bool) -> str:
    """The report's last line: what became of the picture."""
    if drawn.timed_out:
        return (
            "Screenshot: not taken - the page was still running after 15 seconds. Look for a "
            "loop that never ends, or a script waiting on something that never comes."
        )
    if not screenshot:
        return _NO_IMAGES
    return "Screenshot: attached."


def _binding_line(name: str, binding: BindingData) -> str:
    if binding.status != "ok":
        cause = binding.reason
        if cause is not None and binding.changed is not None:
            cause += f": {binding.changed}"
        return f"- {name}: unavailable" + (f" ({cause})" if cause else "")
    line = f"- {name}: {binding.count} record{'' if binding.count == 1 else 's'}"
    if binding.truncated:
        line += f", cut at the {binding.limit} limit"
    return line


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"{title}:", *(f"- {line}" for line in lines)] if lines else []


def _preview_report(
    preview: ArtifactPreview,
    drawn: Rendered | None,
    *,
    problems: list[str],
    outcome: str,
) -> str:
    """What `preview_artifact` tells the model, a section per kind of problem."""
    lines = [
        f"`{preview.name}` - {preview.title!r}, version {preview.version_number}, "
        f"{_extension(preview.media_type)}."
    ]
    if drawn is not None and drawn.shown_height is not None:
        size = f"Drawn {drawn.width} x {drawn.shown_height} pixels"
        if drawn.height is not None and drawn.height > drawn.shown_height:
            size += f"; the page is {drawn.height} pixels tall, so the picture shows its top"
        lines.append(f"{size}.")
    if preview.bindings is None:
        lines.append("Data: none - the page has no bindings.")
    elif preview.data_note is not None:
        lines.append(f"Data: {preview.data_note}")
    else:
        lines.append("Data, as the person this run is for is served it:")
        lines.extend(_binding_line(name, binding) for name, binding in preview.bindings.items())
    findings: list[str] = []
    if drawn is not None and not drawn.timed_out:
        if preview.bindings is not None and not drawn.asked:
            findings.append(
                "The page never asked for its data: call `agenticos.onData(render)` in its script."
            )
        findings += _section("Uncaught errors", drawn.errors)
        findings += _section("Console errors and warnings", drawn.console)
        findings += _section("Refused by the page's security policy", drawn.policy)
        findings += _section(
            "Requests refused - a page loads nothing but itself and the library set",
            drawn.blocked,
        )
        findings += _section("Dialogs dismissed", drawn.dialogs)
    findings += _section("To fix, as publishing checks it", problems)
    ran = drawn is not None and not drawn.timed_out
    lines.extend(findings or ["No problems found." if ran else "No problems in the markup."])
    lines.append(outcome)
    return "\n".join(lines)


def _extension(media_type: ArtifactMediaType) -> str:
    return "HTML" if media_type == ArtifactMediaType.HTML else "Markdown"
