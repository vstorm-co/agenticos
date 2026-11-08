"""Renamed calls keep their server-owned renderer identity through the runtime."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import load_builtins
from app.agents.deps import AgentDeps
from app.agents.mcp import NEEDS_APPROVAL
from app.agents.spec import AgentSpec
from app.agents.tool_identity import CaptureToolIdentity
from app.core.tool_identity import GENERIC_TOOL, ToolIdentity
from app.services.run_stream import RunFrames
from app.services.transcript import tool_calls_in

pytestmark = pytest.mark.anyio


@dataclass
class RenamedDrawing(AbstractCapability[AgentDeps]):
    id: str = "visuals"

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        tools = FunctionToolset[AgentDeps]()

        @tools.tool_plain
        def sketch(content: str) -> str:
            return "Drew " + content

        return tools


async def test_a_real_run_keeps_identity_in_frames_and_the_recorded_transcript() -> None:
    load_builtins()
    spec = AgentSpec(
        name="Artist",
        capabilities=[
            {
                "id": "visuals",
                "tool_overrides": {"draw": {"name": "sketch"}},
            }
        ],
    )
    capture = CaptureToolIdentity.for_spec(spec)
    deps = AgentDeps()

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, ToolReturnPart) for msg in messages for part in msg.parts):
            return ModelResponse(parts=[TextPart("Done")])
        return ModelResponse(
            parts=[ToolCallPart("sketch", {"content": "a tree"}, tool_call_id="drawing")]
        )

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        response = respond(messages, info)
        part = response.parts[0]
        if isinstance(part, ToolCallPart):
            yield {
                0: DeltaToolCall(
                    name=part.tool_name,
                    json_args=part.args_as_json_str(),
                    tool_call_id=part.tool_call_id,
                )
            }
        else:
            yield "Done"

    agent = Agent[AgentDeps, str](
        FunctionModel(respond, stream_function=stream), capabilities=[capture, RenamedDrawing()]
    )
    emitted = AsyncMock()
    frames = RunFrames(emit=emitted)
    async with agent.iter("Draw", deps=deps) as run:
        await frames.drive(run)
    assert run.result is not None
    recorded = tool_calls_in(
        run.result.new_messages(),
        identities=deps.tool_identities,
        definitions=deps.tool_definitions,
    )
    assert [(call.tool_id, call.tool_name, call.result) for call in recorded] == [
        ("draw", "sketch", "Drew a tree")
    ]
    starts = [
        call.args[1]
        for call in emitted.await_args_list
        if call.args[0] == "part_start" and "tool_name" in call.args[1]
    ]
    assert starts[0]["tool_id"] == "draw"
    assert frames.tool_calls[0]["tool_id"] == "draw"
    assert deps.tool_identities["drawing"] == ToolIdentity("draw")


@pytest.mark.security
@pytest.mark.parametrize(
    "name", ["draw", "create_chart", "publish_artifact", "write_draft", "read_skill"]
)
def test_an_mcp_name_cannot_claim_a_builtin_renderer(name: str) -> None:
    capture = CaptureToolIdentity(registered={name: name})
    definition = ToolDefinition(name=name, metadata={NEEDS_APPROVAL: False})
    assert capture.identity(definition) == GENERIC_TOOL


@pytest.mark.parametrize(
    ("name", "owner", "kind", "expected"),
    [
        ("compose", "drafts", None, ToolIdentity("write_draft", "draft")),
        ("load_capability", None, None, ToolIdentity()),
        ("read_skill", None, None, ToolIdentity()),
        ("unknown", None, None, GENERIC_TOOL),
        ("show_setup", "setup", None, ToolIdentity()),
        ("native_read", None, "read_skill", ToolIdentity()),
    ],
)
def test_registered_native_and_unknown_tools_are_distinguished(
    name: str, owner: str | None, kind: str | None, expected: ToolIdentity
) -> None:
    capture = CaptureToolIdentity(registered={"compose": "write_draft"})
    definition = ToolDefinition(name=name, capability_id=owner, tool_kind=kind)
    assert capture.identity(definition) == expected


def test_old_transcripts_still_have_no_inferred_registry_id() -> None:
    calls = tool_calls_in([ModelResponse(parts=[ToolCallPart("draw", {}, tool_call_id="old")])])
    assert calls[0].tool_id is None
    assert calls[0].presentation_kind is None


async def test_a_stream_without_runtime_dependencies_retains_the_legacy_shape() -> None:
    frames = RunFrames(emit=AsyncMock())
    assert frames.identity("draw", "old") == ToolIdentity()


async def test_unknown_definition_and_a_pending_call_use_the_prepared_identity() -> None:
    frames = RunFrames(emit=AsyncMock())
    frames._deps = AgentDeps(tool_definitions={"compose": ToolIdentity("write_draft", "draft")})
    assert frames.identity("compose", "pending") == ToolIdentity("write_draft", "draft")
    assert frames.identity("unknown", "pending") == ToolIdentity()


@pytest.mark.security
def test_stamped_mcp_origin_wins_even_if_an_owner_is_present() -> None:
    import uuid

    from app.agents.mcp import MCP_ORIGIN, McpSourceIdentity, McpToolOrigin

    origin = McpToolOrigin(uuid.uuid4(), McpSourceIdentity("endpoint", uuid.uuid4()), "draw")
    definition = ToolDefinition(name="draw", capability_id="visuals", metadata={MCP_ORIGIN: origin})
    assert CaptureToolIdentity(registered={"draw": "draw"}).identity(definition) == GENERIC_TOOL


def test_framework_and_disabled_bindings_never_receive_registry_ids() -> None:
    load_builtins()
    spec = AgentSpec(
        name="Reader", capabilities=[{"id": "skills"}, {"id": "visuals", "enabled": False}]
    )
    assert CaptureToolIdentity.for_spec(spec).registered == {
        "read_skill_resource": "read_skill_resource"
    }


def test_delivery_uses_stored_identity_and_legacy_names_but_never_external_names() -> None:
    from app.services.transcript import RecordedToolCall

    assert RecordedToolCall("old", "draw", {}).renderer_name == "draw"
    assert RecordedToolCall("new", "sketch", {}, tool_id="draw").renderer_name == "draw"
    assert (
        RecordedToolCall("external", "draw", {}, presentation_kind="generic").renderer_name is None
    )


def test_a_parked_transcript_round_trips_the_original_tool_identity() -> None:
    import uuid

    from app.agents.ephemeral_media import dump_messages
    from app.db.models.agent_run import AgentRun
    from app.services.agent_runner import PausedRunState
    from app.services.channels.prompts import ChannelPrompts

    state = PausedRunState(
        messages=dump_messages(
            [ModelResponse(parts=[ToolCallPart("sketch", {}, tool_call_id="drawing")])]
        ),
        tool_call_ids={"approval": "drawing"},
        tool_identities={"drawing": ToolIdentity("draw")},
    )
    run = AgentRun(id=uuid.uuid4(), paused_state=state.model_dump(mode="json"))
    inherited = ChannelPrompts.inherited_calls(run)
    assert inherited[0].tool_name == "sketch"
    assert inherited[0].tool_id == "draw"


@pytest.mark.security
def test_the_in_process_platform_keeps_its_views_without_claiming_a_registry_id() -> None:
    from app.agents.mcp import PLATFORM_TOOL

    definition = ToolDefinition(
        name="agenticos_create_project", metadata={PLATFORM_TOOL: True, NEEDS_APPROVAL: False}
    )
    identity = CaptureToolIdentity(registered={}).identity(definition)
    assert identity == ToolIdentity(presentation_kind="platform")
    assert identity.wire() == {"presentation_kind": "platform"}
