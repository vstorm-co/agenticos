"""The `publish_artifact` tool: where the page comes from, and how a wrong call is answered.

What the tool must never let the model choose - the organization, the agent, the
owner - comes off `ctx.deps`, and the assertions below are on what reaches
`publish`. A mistake the model can fix is steered (and never ends the run on the
last attempt); a run with nothing to publish under is told so as a result.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage

from app.agents.audience import RunAudience
from app.agents.capabilities import _registry as registry
from app.agents.capabilities.artifacts import Artifacts
from app.agents.capabilities.artifacts._toolset import (
    READ_LIMIT,
    ArtifactEdit,
    apply_edits,
    build_artifacts_toolset,
    parse_published_artifact,
)
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError, ConcurrentChangeError, NotFoundError
from app.db.models.artifact import ArtifactMediaType
from app.services.artifact import ArtifactSource, PublishedArtifact

pytestmark = pytest.mark.anyio

PUBLISH = "app.agents.capabilities.artifacts._toolset.artifacts.publish"


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
    return build_artifacts_toolset().tools["publish_artifact"].function


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
        assert set(toolset.tools) == {"publish_artifact", "read_artifact"}


READ_SOURCE = "app.agents.capabilities.artifacts._toolset.artifacts.read_source"


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
    return build_artifacts_toolset().tools["read_artifact"].function


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
