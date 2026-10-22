"""The `publish_artifact` tool: where the page comes from, and how a wrong call is answered.

What the tool must never let the model choose - the organization, the agent, the
owner - comes off `ctx.deps`, and the assertions below are on what reaches
`publish`. A mistake the model can fix is steered (and never ends the run on the
last attempt); a run with nothing to publish under is told so as a result.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import BinaryContent, ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import WorkspaceError

from app.agents.audience import RunAudience
from app.agents.capabilities import _registry as registry
from app.agents.capabilities.artifacts import Artifacts, ArtifactsConfig
from app.agents.capabilities.artifacts._toolset import (
    PAGE_CONTRACT,
    PAGES_GUIDE,
    READ_LIMIT,
    ArtifactEdit,
    PageList,
    PublishedArtifactResult,
    apply_edits,
    build_artifacts_toolset,
    parse_published_artifact,
)
from app.agents.capabilities.virtual_tables import TABLE_GRANTS_RESOURCE, table_grants_of
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
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
from app.db.models.artifact import ArtifactMediaType
from app.db.models.resource_grant import Visibility
from app.schemas.artifact import BindingData, BindingDisclosure, BindingRequest
from app.services.artifact import (
    ARTIFACT_LIBRARY,
    ArtifactListing,
    ArtifactPreview,
    ArtifactSource,
    ListedArtifact,
    PublishedArtifact,
    RunShare,
)
from app.services.artifact_lint import KIT_CLASSES, lint_page
from app.services.artifact_render import Rendered

pytestmark = pytest.mark.anyio

PUBLISH = "app.services.artifact.publish"


def _deps(**overrides: Any) -> AgentDeps:
    person = uuid.uuid4()
    values: dict[str, Any] = {
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "user_id": str(person),
        "run_id": uuid.uuid4(),
        "audience": RunAudience(user_id=person),
    }
    values.update(overrides)
    return AgentDeps(**values)


def _ctx(deps: AgentDeps, *, retry: int = 0, workspace: Any = None) -> RunContext[AgentDeps]:
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=1)
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _tool() -> Any:
    return build_artifacts_toolset(table_grants={}).tools["publish_artifact"].function


def _published(**overrides: Any) -> PublishedArtifact:
    values: dict[str, Any] = {
        "artifact_id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "version_id": uuid.uuid4(),
        "version_number": 1,
        "name": "weekly-report",
        "title": "Weekly report",
        "created": True,
        "unchanged": False,
        "visibility": "private",
        "public": False,
    }
    values.update(overrides)
    return PublishedArtifact(**values)


_DISCLOSED = BindingDisclosure(
    table="Support tickets",
    filters=['Status is "Open"'],
    sort="when created, descending",
    limit=50,
    fields={"status": "Status (single_select)", "band": "Pay band: formula over Salary, Level"},
)


def _page(body: str, *, kit: int = 3) -> str:
    """A page with the skeleton the contract asks for, so the lint has nothing to say."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<link rel="stylesheet" href="lib/agenticos-{kit}.css">'
        f'<script src="lib/agenticos-{kit}.js"></script></head>'
        f'<body><main class="ao-page">{body}</main></body></html>'
    )


def _workspace(data: bytes | Exception) -> MagicMock:
    """The run's workspace, holding `data` at every path - or raising it."""
    workspace = MagicMock(attached=True)
    if isinstance(data, Exception):
        workspace.read_bytes = AsyncMock(side_effect=data)
    else:
        workspace.read_bytes = AsyncMock(return_value=data)
    return workspace


class TestPublishing:
    async def test_inline_content_is_published_under_the_run_s_own_identity(self) -> None:
        deps = _deps()
        published = _published()
        with patch(PUBLISH, new=AsyncMock(return_value=published)) as publish:
            result = await _tool()(
                _ctx(deps), name="weekly-report", title="Weekly report", content="<p>hi</p>"
            )

        kwargs = publish.await_args.kwargs
        assert kwargs["organization_id"] == deps.organization_id
        assert kwargs["agent_id"] == deps.agent_id
        assert kwargs["owner_user_id"] == uuid.UUID(deps.user_id)
        assert kwargs["run_id"] == deps.run_id
        assert kwargs["media_type"] is ArtifactMediaType.HTML
        assert kwargs["data"] == b"<p>hi</p>"
        parsed = parse_published_artifact(result)
        assert parsed is not None
        assert parsed.artifact_id == published.artifact_id
        assert parsed.url.endswith(
            f"/artifacts/{published.artifact_id}?org={published.organization_id}"
        )

    @pytest.mark.security
    async def test_a_name_somebody_else_s_page_holds_is_a_refusal_not_a_retry(self) -> None:
        """Returned, not steered: a retry prompt on a refusal invites the model to
        look for a way round it, and the answer here is simply another name."""
        refused = AuthorizationError(message="Publish under a different name.")
        with patch(PUBLISH, new=AsyncMock(side_effect=refused)):
            result = await _tool()(
                _ctx(_deps()), name="weekly-report", title="Weekly", content="<p>x</p>"
            )
        assert result == "Publish under a different name."

    async def test_a_workspace_file_is_published_as_the_file_it_is(self) -> None:
        workspace = _workspace(b"# Report\n")
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(
                _ctx(_deps(), workspace=workspace), name="r", title="R", path="out/report.md"
            )

        workspace.read_bytes.assert_awaited_once_with("out/report.md")
        assert publish.await_args.kwargs["media_type"] is ArtifactMediaType.MARKDOWN
        assert publish.await_args.kwargs["data"] == b"# Report\n"

    async def test_an_explicit_format_wins_over_the_extension(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps()), name="r", title="R", content="# x", format="markdown")
        assert publish.await_args.kwargs["media_type"] is ArtifactMediaType.MARKDOWN

    @pytest.mark.parametrize("title", ["   ", None])
    async def test_a_blank_or_missing_title_leaves_it_to_the_service(
        self, title: str | None
    ) -> None:
        """The service titles a new page with its name and keeps an existing page's."""
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps()), name="r", title=title, content="<p>x</p>")
        assert publish.await_args.kwargs["title"] is None

    async def test_a_title_is_trimmed_and_capped(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps()), name="r", title=f"  {'t' * 300} ", content="<p>x</p>")
        assert publish.await_args.kwargs["title"] == "t" * 200

    async def test_bindings_are_resolved_and_echoed(self) -> None:
        """The run's person and the spec's grants come from the run, never from the model."""
        table_id, person = uuid.uuid4(), uuid.uuid4()
        grants = {table_id: frozenset({"read"})}
        requested = {"tickets": BindingRequest(view=uuid.uuid4(), fields={"status": "Status"})}
        echo: dict[str, BindingDisclosure | str] = {
            "tickets": _DISCLOSED,
            "kept_one": "kept",
        }
        tool = build_artifacts_toolset(table_grants=grants).tools["publish_artifact"].function
        with patch(PUBLISH, new=AsyncMock(return_value=_published(bindings=echo))) as publish:
            result = await tool(
                _ctx(_deps(run_person=person)), name="r", content="<p>x</p>", bindings=requested
            )

        kwargs = publish.await_args.kwargs
        assert (kwargs["bindings"], kwargs["run_person"]) == (requested, person)
        assert kwargs["table_grants"] == grants
        parsed = parse_published_artifact(result)
        assert parsed is not None
        assert parsed.bindings == echo
        assert json.loads(result)["bindings"]["tickets"] == {
            "table": "Support tickets",
            "filters": ['Status is "Open"'],
            "sort": "when created, descending",
            "limit": 50,
            "fields": {
                "status": "Status (single_select)",
                "band": "Pay band: formula over Salary, Level",
            },
        }

    @pytest.mark.parametrize(
        ("script", "kit", "warned"),
        [
            # The slip a real model made: AO is the styling kit, not the bridge.
            ("window.AO.chart(c, {});", 3, True),
            ("", 3, True),
            ("agenticos.onData(render);", 2, False),
            ("window.agenticos.data.then(render);", 2, False),
            # Only version 3 has `AO.onData`; on version 2 it throws before asking.
            ("AO.onData(render);", 2, True),
            ("AO.onData(render);", 3, False),
        ],
    )
    async def test_a_bound_page_that_never_asks_for_its_data_is_warned(
        self, script: str, kit: int, warned: bool
    ) -> None:
        echo: dict[str, BindingDisclosure | str] = {"tickets": _DISCLOSED}
        with patch(PUBLISH, new=AsyncMock(return_value=_published(bindings=echo))):
            result = await _tool()(
                _ctx(_deps(run_person=uuid.uuid4())),
                name="r",
                content=_page(f"<script>{script}</script>", kit=kit),
                bindings={
                    "tickets": BindingRequest(view=uuid.uuid4(), fields={"status": "Status"})
                },
            )

        parsed = parse_published_artifact(result)
        assert parsed is not None
        never_asks = "never calls `agenticos.onData`" in (parsed.warning or "")
        assert never_asks is warned

    async def test_a_well_built_page_is_not_warned(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())):
            result = await _tool()(_ctx(_deps()), name="r", content=_page("<p>x</p>"))
        parsed = parse_published_artifact(result)
        assert parsed is not None
        assert parsed.warning is None

    async def test_every_problem_the_lint_finds_is_a_line_of_the_warning(self) -> None:
        """The page a model actually wrote first: no doctype, no viewport, a bare table."""
        page = "<h1>Tickets</h1><table><tr><td>x</td></tr></table>"
        with patch(PUBLISH, new=AsyncMock(return_value=_published())):
            result = await _tool()(_ctx(_deps()), name="r", content=page)
        parsed = parse_published_artifact(result)
        assert parsed is not None and parsed.warning is not None
        lines = parsed.warning.split("\n")
        assert lines == lint_page(page.encode())
        assert len(lines) == 4

    async def test_a_markdown_page_is_not_linted(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())):
            result = await _tool()(_ctx(_deps()), name="r", content="# x", format="markdown")
        parsed = parse_published_artifact(result)
        assert parsed is not None
        assert parsed.warning is None

    async def test_a_result_from_before_bindings_still_parses(self) -> None:
        stored = _published()
        payload = json.loads(
            PublishedArtifactResult(
                artifact_id=stored.artifact_id,
                version_id=stored.version_id,
                version=1,
                name="r",
                title="R",
                url="/artifacts/x",
                created=True,
                unchanged=False,
                visibility="private",
                public=False,
            ).model_dump_json()
        )
        del payload["bindings"]
        parsed = parse_published_artifact(json.dumps(payload))
        assert parsed is not None
        assert parsed.bindings == {}

    async def test_a_markdown_page_with_bindings_is_steered(self) -> None:
        refused = BadRequestError(
            message="Bindings need an HTML page; a Markdown page runs no scripts."
        )
        with (
            patch(PUBLISH, new=AsyncMock(side_effect=refused)),
            pytest.raises(ModelRetry, match="Bindings need an HTML page"),
        ):
            await _tool()(
                _ctx(_deps()),
                name="r",
                content="# x",
                format="markdown",
                bindings={"t": BindingRequest(view=uuid.uuid4(), fields={"a": "A"})},
            )

    @pytest.mark.security
    async def test_a_live_page_refusal_is_returned_not_steered(self) -> None:
        refused = AuthorizationError(
            message="This page reads live data; only a run acting for a member can republish it."
        )
        with patch(PUBLISH, new=AsyncMock(side_effect=refused)):
            result = await _tool()(_ctx(_deps(run_person=None)), name="r", content="<p>x</p>")
        assert result == refused.message

    async def test_a_run_for_nobody_publishes_with_no_owner(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps(user_id=None)), name="r", title="R", content="<p>x</p>")
        assert publish.await_args.kwargs["owner_user_id"] is None


class TestRefusals:
    @pytest.mark.parametrize("missing", ["organization_id", "agent_id"])
    async def test_a_run_with_nothing_to_publish_under_is_told_so(self, missing: str) -> None:
        with patch(PUBLISH, new=AsyncMock()) as publish:
            result = await _tool()(
                _ctx(_deps(**{missing: None})), name="r", title="R", content="<p>x</p>"
            )
        publish.assert_not_awaited()
        assert "no saved agent" in result

    async def test_a_refused_read_is_a_result_not_a_retry(self) -> None:
        workspace = _workspace(PermissionError("secrets/ is not readable"))
        with patch(PUBLISH, new=AsyncMock()) as publish:
            result = await _tool()(
                _ctx(_deps(), workspace=workspace), name="r", title="R", path="secrets/x.html"
            )
        publish.assert_not_awaited()
        assert result == "Reading 'secrets/x.html' was refused: secrets/ is not readable"


class TestAFailedRead:
    async def test_a_container_that_cannot_produce_the_file_is_a_result_not_a_crash(self) -> None:
        """The shell under a container's file read can fail - the session gone,
        its output cut short. The model is told and can publish inline instead."""
        with patch(PUBLISH, new=AsyncMock()) as publish:
            result = await _tool()(
                _ctx(_deps(), workspace=_workspace(WorkspaceError("the sandbox is gone"))),
                name="r",
                title="R",
                path="report.html",
            )
        publish.assert_not_awaited()
        assert result == "Reading 'report.html' failed: the sandbox is gone"


class TestSteering:
    @pytest.mark.parametrize(
        ("arguments", "says"),
        [
            ({}, "exactly one of"),
            ({"path": "a.html", "content": "<p>x</p>"}, "exactly one of"),
            ({"path": "report.pdf"}, "Cannot tell the format"),
            ({"content": "<p>x</p>", "name": "Bad Name"}, "not a valid artifact name"),
            ({"content": ""}, "The page is empty"),
            ({"content": "   "}, "The page is empty"),
        ],
    )
    async def test_a_call_the_model_can_fix_is_steered(
        self, arguments: dict[str, str], says: str
    ) -> None:
        call: dict[str, Any] = {"name": "r", "title": "R", **arguments}
        with (
            patch(PUBLISH, new=AsyncMock()) as publish,
            pytest.raises(ModelRetry, match=says),
        ):
            await _tool()(_ctx(_deps(), workspace=_workspace(b"<p>x</p>")), **call)
        publish.assert_not_awaited()

    async def test_a_path_with_no_workspace_asks_for_inline_content(self) -> None:
        with pytest.raises(ModelRetry, match="no workspace"):
            await _tool()(_ctx(_deps()), name="r", title="R", path="report.html")

    @pytest.mark.parametrize("stored", [b"", FileNotFoundError("nope.html")])
    async def test_a_missing_or_empty_file_says_to_look(self, stored: bytes | Exception) -> None:
        with pytest.raises(ModelRetry, match="Check the path"):
            await _tool()(
                _ctx(_deps(), workspace=_workspace(stored)), name="r", title="R", path="nope.html"
            )

    async def test_on_the_last_attempt_the_steer_is_returned_rather_than_ending_the_run(
        self,
    ) -> None:
        result = await _tool()(_ctx(_deps(), retry=1), name="r", title="R")
        assert "exactly one of" in result


class TestTheWireFormat:
    def test_another_tool_s_text_is_not_an_artifact(self) -> None:
        assert parse_published_artifact("Reading 'x' was refused") is None
        assert parse_published_artifact(json.dumps({"kind": "generated_image"})) is None


class TestRegistration:
    def test_the_capability_reads_the_run_s_workspace_and_is_not_side_effecting(self) -> None:
        definition = registry.get("artifacts")
        assert definition.side_effecting is False
        (built,) = registry.build([registry.CapabilityBinding(capability_id="artifacts")])
        assert isinstance(built, Artifacts)
        toolset = built.get_toolset()
        assert toolset is built.get_toolset()
        assert set(toolset.tools) == {
            "publish_artifact",
            "read_artifact",
            "list_artifacts",
            "preview_artifact",
            "share_artifact",
        }


class TestThePageContract:
    """Reaches the model before its first page, whether or not the skill is bound."""

    def test_it_is_the_capability_s_standing_instruction(self) -> None:
        (built,) = registry.build([registry.CapabilityBinding(capability_id="artifacts")])
        assert built.get_instructions() == PAGE_CONTRACT

    def test_every_class_it_names_is_one_kit_3_defines(self) -> None:
        named = set(re.findall(r"(?<![\w-])ao-[a-z0-9]+(?:-[a-z0-9]+)*", PAGE_CONTRACT))
        assert len(named) > 30
        assert named <= KIT_CLASSES[3]

    def test_it_admits_the_kit_classes_the_guide_teaches_beyond_its_list(self) -> None:
        """The guide's templates use kit classes the contract does not name, so the
        contract has to defer to the guide's class table rather than contradict it."""
        from app.services import skill_library

        guide = skill_library.get(PAGES_GUIDE)
        assert guide is not None
        pattern = r"(?<![\w-])ao-[a-z0-9]+(?:-[a-z0-9]+)*"
        used = {name for res in guide.resources for name in re.findall(pattern, res.content)}
        assert used - set(re.findall(pattern, PAGE_CONTRACT))
        assert used <= KIT_CLASSES[3]
        assert "only these" not in PAGE_CONTRACT
        assert f"`{PAGES_GUIDE}` guide's class table" in PAGE_CONTRACT
        assert "never one outside the kit" in PAGE_CONTRACT

    def test_every_file_it_loads_is_one_the_deployment_serves(self) -> None:
        loaded = set(re.findall(r"lib/([\w.-]+\.(?:js|css))", PAGE_CONTRACT))
        assert loaded == {
            "agenticos-3.css",
            "agenticos-3.js",
            "chart-4.5.1.umd.min.js",
            "lucide-1.46.0.min.js",
        }
        assert loaded <= set(ARTIFACT_LIBRARY)

    def test_its_own_skeleton_passes_the_lint(self) -> None:
        skeleton = PAGE_CONTRACT[PAGE_CONTRACT.index("<!doctype") : PAGE_CONTRACT.index("Rules:")]
        assert lint_page(skeleton.encode()) == []

    def test_it_stays_short_enough_to_pay_for_on_every_request(self) -> None:
        # About four characters a token: the brief is under 600 tokens.
        assert len(PAGE_CONTRACT) < 2400


def _guide(*, loaded: bool = False, deferred: bool = True) -> dict[str, Any]:
    return {
        "capabilities": {PAGES_GUIDE: MagicMock(defer_loading=deferred)},
        "loaded_capability_ids": {PAGES_GUIDE} if loaded else set(),
    }


def _guided_ctx(*, retry: int = 0, **guide: Any) -> RunContext[AgentDeps]:
    ctx = _ctx(_deps(), retry=retry)
    for name, value in _guide(**guide).items():
        setattr(ctx, name, value)
    return ctx


class TestSendingTheModelToTheGuide:
    """A run that offers `artifact-pages` and has not loaded it is sent there once."""

    async def test_the_first_whole_page_is_steered_to_load_the_guide(self) -> None:
        with (
            patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish,
            pytest.raises(ModelRetry, match="load_capability"),
        ):
            await _tool()(_guided_ctx(), name="r", content=_page("<p>x</p>"))
        publish.assert_not_awaited()

    async def test_only_once_a_run_so_the_next_page_publishes(self) -> None:
        tool = _tool()
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            with pytest.raises(ModelRetry):
                await tool(_guided_ctx(), name="r", content=_page("<p>x</p>"))
            result = await tool(_guided_ctx(), name="r", content=_page("<p>x</p>"))
        publish.assert_awaited_once()
        parsed = parse_published_artifact(result)
        assert parsed is not None and parsed.warning is None

    async def test_on_the_last_attempt_the_page_publishes_with_the_advice(self) -> None:
        """A steer on the last attempt would publish nothing; the page goes out instead."""
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            result = await _tool()(_guided_ctx(retry=1), name="r", content=_page("<p>x</p>"))
        publish.assert_awaited_once()
        parsed = parse_published_artifact(result)
        assert parsed is not None and parsed.warning is not None
        assert f"`load_capability` (id `{PAGES_GUIDE}`)" in parsed.warning

    @pytest.mark.parametrize(
        "guide",
        [{"loaded": True}, {"deferred": False}],
        ids=["already-loaded", "always-on"],
    )
    async def test_a_guide_already_in_force_is_not_asked_for(self, guide: dict[str, Any]) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_guided_ctx(**guide), name="r", content=_page("<p>x</p>"))
        publish.assert_awaited_once()

    async def test_a_run_without_the_skill_is_never_asked_to_load_it(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps()), name="r", content=_page("<p>x</p>"))
        publish.assert_awaited_once()

    async def test_a_markdown_page_is_not_sent_to_a_guide_for_html(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_guided_ctx(), name="r", content="# x", format="markdown")
        publish.assert_awaited_once()

    async def test_an_edit_to_a_published_page_is_not_sent_to_the_guide(self) -> None:
        with (
            patch(READ_SOURCE, new=AsyncMock(return_value=_source())),
            patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish,
        ):
            await _tool()(_guided_ctx(), name="r", edits=[ArtifactEdit(old="Old", new="New")])
        publish.assert_awaited_once()


READ_SOURCE = "app.services.artifact.read_source"


def _source(text: str = "<h1>Old</h1><p>body</p>", **overrides: Any) -> ArtifactSource:
    values: dict[str, Any] = {
        "name": "weekly-report",
        "title": "Weekly report",
        "version_number": 3,
        "media_type": ArtifactMediaType.HTML,
        "text": text,
    }
    values.update(overrides)
    return ArtifactSource(**values)


def _reader() -> Any:
    return build_artifacts_toolset(table_grants={}).tools["read_artifact"].function


class TestEditing:
    async def test_edits_change_the_current_version_and_carry_the_version_they_read(
        self,
    ) -> None:
        deps = _deps()
        with (
            patch(READ_SOURCE, new=AsyncMock(return_value=_source())) as read,
            patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish,
        ):
            await _tool()(
                _ctx(deps),
                name="weekly-report",
                edits=[ArtifactEdit(old="Old", new="New"), ArtifactEdit(old="body", new="")],
            )
        assert read.await_args.kwargs == {
            "organization_id": deps.organization_id,
            "agent_id": deps.agent_id,
            "reader_user_id": uuid.UUID(deps.user_id),
            "run_id": deps.run_id,
            "name": "weekly-report",
        }
        kwargs = publish.await_args.kwargs
        assert kwargs["data"] == b"<h1>New</h1><p></p>"
        assert kwargs["expected_version"] == 3
        assert kwargs["media_type"] is ArtifactMediaType.HTML
        assert kwargs["title"] is None

    async def test_a_markdown_page_stays_markdown(self) -> None:
        source = _source("# Old", media_type=ArtifactMediaType.MARKDOWN)
        with (
            patch(READ_SOURCE, new=AsyncMock(return_value=source)),
            patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish,
        ):
            await _tool()(
                _ctx(_deps()),
                name="r",
                edits=[ArtifactEdit(old="Old", new="New")],
                format="markdown",
            )
        assert publish.await_args.kwargs["media_type"] is ArtifactMediaType.MARKDOWN

    @pytest.mark.parametrize(
        ("text", "old", "says"),
        [
            ("<p>a</p>", "missing", "is not in the page"),
            ("<p>a</p><p>a</p>", "<p>a</p>", "appears 2 times"),
        ],
    )
    async def test_an_edit_that_does_not_name_one_place_is_steered(
        self, text: str, old: str, says: str
    ) -> None:
        with (
            patch(READ_SOURCE, new=AsyncMock(return_value=_source(text))),
            patch(PUBLISH, new=AsyncMock()) as publish,
            pytest.raises(ModelRetry, match=says),
        ):
            await _tool()(_ctx(_deps()), name="r", edits=[ArtifactEdit(old=old, new="x")])
        publish.assert_not_awaited()

    async def test_no_edits_at_all_is_steered(self) -> None:
        with pytest.raises(ModelRetry, match="at least one"):
            await _tool()(_ctx(_deps()), name="r", edits=[])

    async def test_changing_the_format_with_an_edit_is_steered(self) -> None:
        with (
            patch(READ_SOURCE, new=AsyncMock(return_value=_source())),
            pytest.raises(ModelRetry, match="keeps the page's format"),
        ):
            await _tool()(
                _ctx(_deps()),
                name="r",
                edits=[ArtifactEdit(old="Old", new="x")],
                format="markdown",
            )

    @pytest.mark.security
    async def test_a_page_the_run_may_not_open_is_a_refusal_not_a_retry(self) -> None:
        missing = NotFoundError(message="There is no artifact named 'r' that this run may open.")
        with patch(READ_SOURCE, new=AsyncMock(side_effect=missing)):
            result = await _tool()(_ctx(_deps()), name="r", edits=[ArtifactEdit(old="a", new="b")])
        assert result.startswith("There is no artifact named 'r'")
        assert "`content` or `path`" in result

    async def test_a_page_that_moved_on_meanwhile_is_steered_to_read_again(self) -> None:
        moved = ConcurrentChangeError(message="Read it again with `read_artifact`.")
        with (
            patch(READ_SOURCE, new=AsyncMock(return_value=_source())),
            patch(PUBLISH, new=AsyncMock(side_effect=moved)),
            pytest.raises(ModelRetry, match="Read it again"),
        ):
            await _tool()(_ctx(_deps()), name="r", edits=[ArtifactEdit(old="Old", new="x")])

    async def test_edits_beside_content_is_one_source_too_many(self) -> None:
        with pytest.raises(ModelRetry, match="exactly one of"):
            await _tool()(
                _ctx(_deps()),
                name="r",
                content="<p>x</p>",
                edits=[ArtifactEdit(old="a", new="b")],
            )


class TestApplyEdits:
    def test_edits_apply_in_order_each_to_what_the_last_left(self) -> None:
        edits = [ArtifactEdit(old="a", new="bb"), ArtifactEdit(old="bbc", new="d")]
        assert apply_edits("ac", edits) == "d"

    def test_the_failing_edit_is_named_by_its_position(self) -> None:
        with pytest.raises(ValueError, match="Edit 2"):
            apply_edits("abc", [ArtifactEdit(old="a", new="x"), ArtifactEdit(old="a", new="y")])


class TestReadingBack:
    async def test_the_page_comes_back_with_a_header_naming_its_version(self) -> None:
        deps = _deps()
        with patch(READ_SOURCE, new=AsyncMock(return_value=_source("<p>hi</p>"))) as read:
            result = await _reader()(_ctx(deps), name="weekly-report")
        assert read.await_args.kwargs["reader_user_id"] == uuid.UUID(deps.user_id)
        header, body = result.split("\n\n", 1)
        assert header == "`weekly-report` - 'Weekly report', version 3, HTML, 9 characters."
        assert body == "<p>hi</p>"

    async def test_a_long_page_is_cut_and_says_so(self) -> None:
        text = "x" * (READ_LIMIT + 5)
        source = _source(text, media_type=ArtifactMediaType.MARKDOWN)
        with patch(READ_SOURCE, new=AsyncMock(return_value=source)):
            result = await _reader()(_ctx(_deps()), name="r")
        header, body = result.split("\n\n", 1)
        assert "Markdown" in header
        assert f"Showing the first {READ_LIMIT:,} of {READ_LIMIT + 5:,} characters." in header
        assert len(body) == READ_LIMIT

    @pytest.mark.security
    @pytest.mark.parametrize(("room_key", "room"), [(None, False), ("room:slack:C1", True)])
    async def test_a_group_chat_reads_only_what_a_room_may_see(
        self, room_key: str | None, room: bool
    ) -> None:
        audience = RunAudience(user_id=uuid.uuid4(), room_key=room_key)
        read = AsyncMock(return_value=_source("<p>hi</p>"))
        with patch(READ_SOURCE, new=read):
            await _reader()(_ctx(_deps(audience=audience)), name="r")
        assert read.await_args.kwargs["room"] is room

    @pytest.mark.security
    async def test_a_page_the_run_may_not_open_is_answered_like_a_missing_one(self) -> None:
        missing = NotFoundError(message="There is no artifact named 'r' that this run may open.")
        with patch(READ_SOURCE, new=AsyncMock(side_effect=missing)):
            result = await _reader()(_ctx(_deps()), name="r")
        assert result == "There is no artifact named 'r' that this run may open."

    @pytest.mark.security
    @pytest.mark.parametrize(
        "audience",
        [RunAudience(), None],
        ids=["anonymous-visitor", "no-audience"],
    )
    async def test_an_anonymous_surface_reads_nothing(self, audience: RunAudience | None) -> None:
        """On a public widget `user_id` is the publisher standing in for a visitor,
        who could otherwise have any page the publisher may open read out."""
        with patch(READ_SOURCE, new=AsyncMock()) as read:
            result = await _reader()(_ctx(_deps(audience=audience)), name="r")
        assert "nobody is signed in" in result
        read.assert_not_awaited()

    @pytest.mark.parametrize("missing", ["organization_id", "agent_id"])
    async def test_a_run_with_no_agent_has_nothing_to_read(self, missing: str) -> None:
        result = await _reader()(_ctx(_deps(**{missing: None})), name="r")
        assert "no saved agent" in result


def _artifacts_built_for(spec: AgentSpec) -> Artifacts[Any]:
    ctx = registry.CapabilityBuildContext(
        binding=registry.CapabilityBinding(capability_id="artifacts"),
        config=None,
        resources={TABLE_GRANTS_RESOURCE: table_grants_of(spec)},
    )
    built = registry.get("artifacts").builder(ctx)
    assert isinstance(built, Artifacts)
    return built


def test_an_agent_with_tables_hands_their_grants_to_publishing():
    table_id = uuid.uuid4()
    spec = AgentSpec(
        name="Clerk",
        capabilities=[
            {
                "id": "virtual_tables",
                "config": {"tables": [{"table_id": str(table_id), "operations": ["read"]}]},
            }
        ],
    )

    assert _artifacts_built_for(spec).table_grants == {table_id: frozenset({"read"})}


def test_an_agent_without_tables_hands_no_grants():
    assert _artifacts_built_for(AgentSpec(name="Clerk")).table_grants == {}


def test_a_model_without_images_is_handed_no_picture():
    ctx = registry.CapabilityBuildContext(
        binding=registry.CapabilityBinding(capability_id="artifacts"),
        config=ArtifactsConfig(preview_screenshot=False),
        resources={},
    )
    built = registry.get("artifacts").builder(ctx)
    assert isinstance(built, Artifacts)
    assert built.screenshot is False
    assert _artifacts_built_for(AgentSpec(name="Clerk")).screenshot is True


LIST_FOR_RUN = "app.services.artifact.list_for_run"


def _lister() -> Any:
    return build_artifacts_toolset(table_grants={}).tools["list_artifacts"].function


def _listed(**overrides: Any) -> ListedArtifact:
    values: dict[str, Any] = {
        "name": "weekly-report",
        "title": "Weekly report",
        "version_number": 4,
        "media_type": ArtifactMediaType.HTML,
        "bindings": ["tickets"],
        "visibility": "org",
        "public": True,
        "published_at": datetime(2026, 10, 1, tzinfo=UTC),
        "console_path": "/artifacts/abc?org=def",
        "may_edit": True,
    }
    values.update(overrides)
    return ListedArtifact(**values)


class TestListing:
    async def test_pages_come_back_with_what_the_model_needs_to_choose_one(self) -> None:
        deps = _deps()
        listing = ArtifactListing(
            items=[
                _listed(),
                _listed(name="notes", media_type=ArtifactMediaType.MARKDOWN, bindings=[]),
            ],
            total=7,
        )
        with patch(LIST_FOR_RUN, new=AsyncMock(return_value=listing)) as listed:
            result = await _lister()(_ctx(deps))

        payload = PageList.model_validate_json(result)
        assert payload.total == 7
        first, second = payload.pages
        assert (first.format, first.live, first.bindings, first.may_edit) == (
            "html",
            True,
            ["tickets"],
            True,
        )
        assert first.url.endswith("/artifacts/abc?org=def")
        assert first.url.startswith("http")
        assert (second.format, second.live) == ("markdown", False)
        kwargs = listed.await_args.kwargs
        assert kwargs["organization_id"] == deps.organization_id
        assert kwargs["agent_id"] == deps.agent_id
        assert kwargs["run_id"] == deps.run_id
        assert kwargs["room"] is False

    @pytest.mark.security
    async def test_the_reader_is_the_audience_and_the_editor_the_publishing_identity(
        self,
    ) -> None:
        listener, publisher = uuid.uuid4(), uuid.uuid4()
        deps = _deps(user_id=str(publisher), audience=RunAudience(user_id=listener))
        empty = ArtifactListing(items=[], total=0)
        with patch(LIST_FOR_RUN, new=AsyncMock(return_value=empty)) as listed:
            assert json.loads(await _lister()(_ctx(deps))) == {"pages": [], "total": 0}
        kwargs = listed.await_args.kwargs
        assert (kwargs["reader_user_id"], kwargs["editor_user_id"]) == (listener, publisher)

    @pytest.mark.security
    async def test_a_group_chat_is_listed_as_a_room(self) -> None:
        person = uuid.uuid4()
        deps = _deps(user_id=None, audience=RunAudience(user_id=person, room_key="room:slack:C1"))
        with patch(
            LIST_FOR_RUN, new=AsyncMock(return_value=ArtifactListing(items=[], total=0))
        ) as listed:
            await _lister()(_ctx(deps))
        assert listed.await_args.kwargs["room"] is True
        assert listed.await_args.kwargs["editor_user_id"] is None

    @pytest.mark.security
    @pytest.mark.parametrize("audience", [None, RunAudience()])
    async def test_an_anonymous_surface_lists_nothing(self, audience: RunAudience | None) -> None:
        with patch(LIST_FOR_RUN, new=AsyncMock()) as listed:
            result = await _lister()(_ctx(_deps(audience=audience)))
        assert "nobody is signed in" in result
        listed.assert_not_awaited()

    @pytest.mark.parametrize("missing", ["organization_id", "agent_id"])
    async def test_a_run_with_no_agent_has_nothing_to_list(self, missing: str) -> None:
        assert "no saved agent" in await _lister()(_ctx(_deps(**{missing: None})))


PREVIEW_SOURCE = "app.services.artifact.preview_source"
RENDER = "app.services.artifact_render.render"


def _previewer(*, screenshot: bool = True) -> Any:
    toolset = build_artifacts_toolset(table_grants={}, screenshot=screenshot)
    return toolset.tools["preview_artifact"].function


def _binding_data(**overrides: Any) -> BindingData:
    values: dict[str, Any] = {
        "status": "ok",
        "truncated": False,
        "count": 2,
        "fields": {},
        "records": [],
    }
    values.update(overrides)
    return BindingData(**values)


def _preview(**overrides: Any) -> ArtifactPreview:
    values: dict[str, Any] = {
        "name": "weekly-report",
        "title": "Weekly report",
        "version_number": 5,
        "media_type": ArtifactMediaType.HTML,
        "source": _page("<h1>Hi</h1><script>agenticos.onData(function () {});</script>").encode(),
        "document": b"<served>",
        "nonce": "n0nce",
        "injected_lines": 12,
        "binding_names": ["tickets"],
        "bindings": {"tickets": _binding_data()},
        "data_note": None,
    }
    values.update(overrides)
    return ArtifactPreview(**values)


async def _previewed(
    preview: ArtifactPreview | Exception,
    drawn: Rendered | Exception,
    *,
    deps: AgentDeps | None = None,
    screenshot: bool = True,
) -> tuple[Any, AsyncMock, AsyncMock]:
    source = AsyncMock(
        side_effect=preview if isinstance(preview, Exception) else None, return_value=preview
    )
    render = AsyncMock(
        side_effect=drawn if isinstance(drawn, Exception) else None, return_value=drawn
    )
    with patch(PREVIEW_SOURCE, new=source), patch(RENDER, new=render):
        result = await _previewer(screenshot=screenshot)(
            _ctx(deps or _deps()), name="weekly-report"
        )
    return result, source, render


def _drawn(**overrides: Any) -> Rendered:
    values: dict[str, Any] = {
        "image": b"jpeg",
        "height": 900,
        "shown_height": 900,
        "asked": True,
    }
    values.update(overrides)
    return Rendered(**values)


class TestPreviewing:
    async def test_the_picture_goes_to_the_model_and_the_report_to_the_transcript(
        self,
    ) -> None:
        deps = _deps()
        result, source, render = await _previewed(_preview(), _drawn(), deps=deps)

        assert isinstance(result, ToolReturn)
        assert "Screenshot: attached." in result.return_value
        assert "Drawn 1280 x 900 pixels." in result.return_value
        assert "- tickets: 2 records" in result.return_value
        assert "No problems found." in result.return_value
        caption, image = result.content
        assert "`weekly-report`, version 5" in caption
        assert isinstance(image, BinaryContent)
        assert (image.data, image.media_type) == (b"jpeg", "image/jpeg")
        kwargs = source.await_args.kwargs
        assert kwargs["reader_user_id"] == deps.audience.user_id
        assert kwargs["room"] is False
        (request,) = render.await_args.args
        assert (request.document, request.nonce, request.injected_lines) == (
            b"<served>",
            "n0nce",
            12,
        )
        assert request.bindings == {"tickets": _binding_data()}

    async def test_everything_the_page_did_wrong_is_a_section_of_the_report(self) -> None:
        drawn = _drawn(
            height=3000,
            shown_height=2400,
            asked=False,
            errors=["Error: boom (line 3)"],
            console=["error: bad"],
            policy=["Refused to load the image"],
            blocked=["https://evil.example/x"],
            dialogs=["alert: hi"],
        )
        source = _page("<table><tr><td>1</td></tr></table>").replace("<!doctype html>", "")
        result, _, _ = await _previewed(_preview(source=source.encode()), drawn)
        report = result.return_value
        assert "the page is 3000 pixels tall, so the picture shows its top" in report
        assert "never asked for its data" in report
        for section, line in [
            ("Uncaught errors:", "- Error: boom (line 3)"),
            ("Console errors and warnings:", "- error: bad"),
            ("Refused by the page's security policy:", "- Refused to load the image"),
            ("Requests refused", "- https://evil.example/x"),
            ("Dialogs dismissed:", "- alert: hi"),
            ("To fix, as publishing checks it:", "- It does not start with `<!doctype html>`"),
        ]:
            assert section in report
            assert line in report
        assert "No problems found." not in report

    async def test_each_binding_says_what_it_was_served(self) -> None:
        bindings = {
            "one": _binding_data(count=1),
            "cut": _binding_data(truncated=True, limit="records"),
            "hidden": _binding_data(status="unavailable", reason="creator_lost_access", count=0),
            "moved": _binding_data(
                status="unavailable", reason="source_changed", changed="Status", count=0
            ),
            "gone": _binding_data(status="unavailable", count=0),
        }
        result, _, _ = await _previewed(_preview(bindings=bindings), _drawn())
        report = result.return_value
        assert "- one: 1 record\n" in report
        assert "- cut: 2 records, cut at the records limit\n" in report
        assert "- hidden: unavailable (creator_lost_access)" in report
        assert "- moved: unavailable (source_changed: Status)" in report
        assert "- gone: unavailable\n" in report

    async def test_data_that_was_not_read_says_why(self) -> None:
        preview = _preview(bindings={}, data_note="This conversation is a group chat.")
        result, _, _ = await _previewed(preview, _drawn())
        assert "Data: This conversation is a group chat." in result.return_value

    async def test_a_page_with_no_bindings_is_not_asked_about_its_data(self) -> None:
        preview = _preview(bindings=None, binding_names=[])
        result, _, _ = await _previewed(preview, _drawn(asked=False))
        assert "Data: none - the page has no bindings." in result.return_value
        assert "never asked" not in result.return_value

    async def test_without_a_renderer_the_report_still_comes_back(self) -> None:
        source = _page("<p>x</p>").replace("<!doctype html>", "").encode()
        result, _, _ = await _previewed(
            _preview(source=source),
            ConfigurationError(message="ARTIFACT_RENDER_CDP_URL is not set"),
        )
        assert isinstance(result, str)
        assert "not available on this deployment" in result
        assert "ARTIFACT_RENDER_CDP_URL" not in result
        assert "<!doctype html>" in result
        assert "Drawn" not in result

    async def test_a_renderer_that_fails_is_said_so(self) -> None:
        result, _, _ = await _previewed(
            _preview(), ExternalServiceError(message="The page renderer did not answer.")
        )
        assert isinstance(result, str)
        assert "Screenshot: not taken - The page renderer did not answer." in result

    async def test_a_page_still_running_at_the_deadline_is_told_to_look_for_a_loop(
        self,
    ) -> None:
        result, _, _ = await _previewed(_preview(), _drawn(image=None, timed_out=True))
        assert isinstance(result, str)
        assert "still running after 15 seconds" in result
        assert "never asked" not in result
        assert "No problems in the markup." in result

    async def test_a_model_without_images_gets_the_report_alone(self) -> None:
        result, _, _ = await _previewed(_preview(), _drawn(), screenshot=False)
        assert isinstance(result, str)
        assert "not attached" in result

    async def test_a_markdown_page_is_not_held_to_the_html_checks(self) -> None:
        preview = _preview(
            media_type=ArtifactMediaType.MARKDOWN,
            source=b"# Notes",
            bindings=None,
            binding_names=[],
        )
        result, _, _ = await _previewed(preview, _drawn())
        assert "Markdown" in result.return_value
        assert "To fix" not in result.return_value

    @pytest.mark.security
    async def test_a_group_chat_previews_as_a_room(self) -> None:
        deps = _deps(audience=RunAudience(user_id=uuid.uuid4(), room_key="room:slack:C1"))
        _, source, _ = await _previewed(_preview(), _drawn(), deps=deps)
        assert source.await_args.kwargs["room"] is True

    async def test_a_page_the_run_may_not_open_is_answered_like_a_missing_one(self) -> None:
        missing = NotFoundError(message="There is no artifact named 'x' that this run may open.")
        result, _, render = await _previewed(missing, _drawn())
        assert result == missing.message
        render.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize("audience", [None, RunAudience()])
    async def test_an_anonymous_surface_previews_nothing(
        self, audience: RunAudience | None
    ) -> None:
        result, source, _ = await _previewed(_preview(), _drawn(), deps=_deps(audience=audience))
        assert "nobody is signed in" in result
        source.assert_not_awaited()

    @pytest.mark.parametrize("missing", ["organization_id", "agent_id"])
    async def test_a_run_with_no_agent_has_nothing_to_preview(self, missing: str) -> None:
        result, _, _ = await _previewed(_preview(), _drawn(), deps=_deps(**{missing: None}))
        assert "no saved agent" in result


REQUEST_SHARE = "app.services.artifact.request_share"


def _sharer() -> Any:
    return build_artifacts_toolset(table_grants={}).tools["share_artifact"].function


def _shared(**overrides: Any) -> RunShare:
    values: dict[str, Any] = {
        "name": "weekly-report",
        "asked": ["org", "Ada Lovelace"],
        "already": [],
        "unknown": [],
        "ambiguous": [],
        "waiting_for": "Grace Hopper",
        "filed": True,
    }
    values.update(overrides)
    return RunShare(**values)


class TestSharing:
    async def test_it_files_a_request_and_says_who_decides_it(self) -> None:
        person = uuid.uuid4()
        deps = _deps(run_person=person)
        with patch(REQUEST_SHARE, new=AsyncMock(return_value=_shared())) as filed:
            result = await _sharer()(_ctx(deps), "weekly-report", "org", ["Ada Lovelace"])

        assert result == (
            "Waiting for Grace Hopper to approve in the page's Share dialog: `weekly-report` "
            "would be shared with org, Ada Lovelace."
        )
        kwargs = filed.await_args.kwargs
        assert kwargs["run_person"] == person
        assert kwargs["visibility"] == Visibility.ORG
        assert kwargs["people"] == ["Ada Lovelace"]
        assert kwargs["room"] is False

    async def test_an_ownerless_page_waits_for_an_owner_or_admin(self) -> None:
        deps = _deps(run_person=uuid.uuid4())
        with patch(REQUEST_SHARE, new=AsyncMock(return_value=_shared(waiting_for=None))):
            result = await _sharer()(_ctx(deps), "weekly-report", "team")
        assert result.startswith("Waiting for an Owner or Admin to approve")

    async def test_names_it_could_not_match_are_reported_not_guessed(self) -> None:
        deps = _deps(run_person=uuid.uuid4())
        shared = _shared(already=["team"], unknown=["Nobody"], ambiguous=["Sam"])
        with patch(REQUEST_SHARE, new=AsyncMock(return_value=shared)):
            result = await _sharer()(_ctx(deps), "weekly-report", None, ["Nobody", "Sam"])
        assert "Already shared with team." in result
        assert "No member or group is named 'Nobody'." in result
        assert (
            "More than one member or group is named 'Sam'; name a group by its exact name, or a person by email address."
            in result
        )

    async def test_with_nothing_left_to_ask_no_request_is_reported(self) -> None:
        deps = _deps(run_person=uuid.uuid4())
        shared = _shared(asked=[], already=["org"], filed=False, waiting_for=None)
        with patch(REQUEST_SHARE, new=AsyncMock(return_value=shared)):
            result = await _sharer()(_ctx(deps), "weekly-report", "org")
        assert result == "Nothing to ask for: `weekly-report` is shared that widely already."

    @pytest.mark.security
    async def test_a_run_with_nobody_behind_it_cannot_ask(self) -> None:
        with patch(REQUEST_SHARE, new=AsyncMock()) as filed:
            result = await _sharer()(_ctx(_deps(run_person=None)), "weekly-report", "org")
        assert "no signed-in person" in result
        filed.assert_not_awaited()

    @pytest.mark.parametrize("missing", ["organization_id", "agent_id"])
    async def test_a_run_with_no_agent_has_nothing_to_share(self, missing: str) -> None:
        deps = _deps(run_person=uuid.uuid4(), **{missing: None})
        with patch(REQUEST_SHARE, new=AsyncMock()) as filed:
            result = await _sharer()(_ctx(deps), "weekly-report", "org")
        assert result.startswith("Publishing is not available here")
        filed.assert_not_awaited()

    async def test_asking_for_nothing_steers_the_model(self) -> None:
        deps = _deps(run_person=uuid.uuid4())
        with patch(REQUEST_SHARE, new=AsyncMock()) as filed, pytest.raises(ModelRetry):
            await _sharer()(_ctx(deps), "weekly-report", None, [])
        filed.assert_not_awaited()

    @pytest.mark.security
    async def test_a_group_chat_is_asked_as_a_room(self) -> None:
        person = uuid.uuid4()
        deps = _deps(
            run_person=person,
            audience=RunAudience(user_id=person, room_key="room:slack:C1"),
        )
        with patch(REQUEST_SHARE, new=AsyncMock(return_value=_shared())) as filed:
            await _sharer()(_ctx(deps), "weekly-report", "org")
        assert filed.await_args.kwargs["room"] is True

    @pytest.mark.parametrize(
        "refusal",
        [
            NotFoundError(message="There is no artifact named 'x' that this run may open."),
            AuthorizationError(message="This run's person may not change its sharing."),
            ConflictError(message="This page is archived."),
            RateLimitError(message="Too many requests in the last hour."),
        ],
    )
    async def test_a_refusal_is_returned_not_retried(self, refusal: Exception) -> None:
        deps = _deps(run_person=uuid.uuid4())
        with patch(REQUEST_SHARE, new=AsyncMock(side_effect=refusal)):
            result = await _sharer()(_ctx(deps), "x", "org")
        assert result == refusal.message

    def test_there_is_no_public_value_and_it_is_never_gated_for_approval(self) -> None:
        tool = build_artifacts_toolset(table_grants={}).tools["share_artifact"]
        visibility = tool.function_schema.json_schema["properties"]["visibility"]
        assert {"enum": ["team", "org"], "type": "string"} in visibility["anyOf"]
        assert "public" not in tool.function_schema.json_schema["properties"]
        (info,) = [info for info in registry.get("artifacts").tools if info.id == "share_artifact"]
        assert info.side_effecting is False
