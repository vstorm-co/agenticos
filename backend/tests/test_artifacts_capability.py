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

from app.agents.capabilities import _registry as registry
from app.agents.capabilities.artifacts import Artifacts
from app.agents.capabilities.artifacts._toolset import (
    build_artifacts_toolset,
    parse_published_artifact,
)
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError
from app.db.models.artifact import ArtifactMediaType
from app.services.artifact import PublishedArtifact

pytestmark = pytest.mark.anyio

PUBLISH = "app.agents.capabilities.artifacts._toolset.artifacts.publish"


def _deps(**overrides: Any) -> AgentDeps:
    values: dict[str, Any] = {
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "user_id": str(uuid.uuid4()),
        "run_id": uuid.uuid4(),
    }
    values.update(overrides)
    return AgentDeps(**values)


def _ctx(deps: AgentDeps, *, retry: int = 0) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=1)


def _tool(workspace: Any = None) -> Any:
    toolset = build_artifacts_toolset(workspace_backend=workspace)
    return toolset.tools["publish_artifact"].function


def _published(**overrides: Any) -> PublishedArtifact:
    values: dict[str, Any] = {
        "artifact_id": uuid.uuid4(),
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
    backend = MagicMock()
    if isinstance(data, Exception):
        backend.read_bytes = AsyncMock(side_effect=data)
    else:
        backend.read_bytes = AsyncMock(return_value=data)
    return backend


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
        assert parsed.url.endswith(f"/artifacts/{published.artifact_id}")

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
            await _tool(workspace)(_ctx(_deps()), name="r", title="R", path="out/report.md")

        workspace.read_bytes.assert_awaited_once_with("out/report.md")
        assert publish.await_args.kwargs["media_type"] is ArtifactMediaType.MARKDOWN
        assert publish.await_args.kwargs["data"] == b"# Report\n"

    async def test_an_explicit_format_wins_over_the_extension(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps()), name="r", title="R", content="# x", format="markdown")
        assert publish.await_args.kwargs["media_type"] is ArtifactMediaType.MARKDOWN

    async def test_a_blank_title_falls_back_to_the_name(self) -> None:
        with patch(PUBLISH, new=AsyncMock(return_value=_published())) as publish:
            await _tool()(_ctx(_deps()), name="r", title="   ", content="<p>x</p>")
        assert publish.await_args.kwargs["title"] == "r"

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
            result = await _tool(workspace)(
                _ctx(_deps()), name="r", title="R", path="secrets/x.html"
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
            await _tool(_workspace(b"<p>x</p>"))(_ctx(_deps()), **call)
        publish.assert_not_awaited()

    async def test_a_path_with_no_workspace_asks_for_inline_content(self) -> None:
        with pytest.raises(ModelRetry, match="no workspace"):
            await _tool()(_ctx(_deps()), name="r", title="R", path="report.html")

    async def test_a_missing_file_says_to_look(self) -> None:
        with pytest.raises(ModelRetry, match="Check the path"):
            await _tool(_workspace(b""))(_ctx(_deps()), name="r", title="R", path="nope.html")

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
        workspace = object()
        (built,) = registry.build(
            [registry.CapabilityBinding(capability_id="artifacts")],
            resources={WORKSPACE_BACKEND_RESOURCE: workspace},
        )
        assert isinstance(built, Artifacts)
        assert built.workspace_backend is workspace
        toolset = built.get_toolset()
        assert toolset is built.get_toolset()
        assert "publish_artifact" in toolset.tools
