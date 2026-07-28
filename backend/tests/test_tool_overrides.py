"""Tests for per-agent tool names and descriptions.

A tool's description is the last thing a model reads before deciding to act, and
its name is read alongside it - so both are per-agent settings rather than
properties of the code that wrote the tool.

The half of this that matters is not cosmetic. Approval is keyed on a tool's
stable id, the gate matches the name the model called, and once a binding can
rename a tool those are different strings. Resolve it the wrong way and a gated,
side-effecting tool runs unapproved with nothing reporting it - which is why
`TestARenamedToolIsStillGated` drives a real agent through a real rename rather
than asserting on a set of strings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from app.agents.capabilities import (
    REGISTRY,
    CapabilityBuildContext,
    CapabilityToolInfo,
    ToolOverrides,
    load_builtins,
    register,
)
from app.agents.capabilities.approval import approval_required_tools
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_runner import ApprovalChannel

SIDE_EFFECTING = "test_overridable_action"
SIDE_EFFECTING_TOOL = "do_the_thing"


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


@pytest.fixture
def side_effecting_capability():
    """A capability whose one tool acts on the world, so gating it is meaningful."""

    @register(
        id=SIDE_EFFECTING,
        name="Overridable action",
        category="test",
        description="An action worth asking about first",
        side_effecting=True,
        tools=(CapabilityToolInfo(id=SIDE_EFFECTING_TOOL, description="Does the thing."),),
    )
    def _build(ctx: CapabilityBuildContext) -> _Action:
        return _Action()

    yield SIDE_EFFECTING
    REGISTRY.pop(SIDE_EFFECTING)


@dataclass
class _Action(AbstractCapability[Any]):
    """One tool that records whether it ran, so an ungated call is visible."""

    ran: list[bool] = field(default_factory=list)

    def get_toolset(self) -> AbstractToolset[Any]:
        def do_the_thing() -> str:
            """Do the thing that needs a human to say yes first."""
            self.ran.append(True)
            return "done"

        toolset: FunctionToolset[Any] = FunctionToolset()
        toolset.add_function(do_the_thing, takes_ctx=False)
        return toolset


def _model_spec() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1 (prod)",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
        fallbacks=[],
    )


def _seeing_model(seen: list[ToolDefinition]) -> FunctionModel:
    """A model that records the tools it was offered and then answers."""

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.extend(info.function_tools)
        return ModelResponse(parts=[TextPart("noted")])

    return FunctionModel(respond)


def _calling_model(tool_name: str) -> FunctionModel:
    """A model that calls one named tool once, then answers.

    It has to be able to finish: if the gate were to let the call through, an
    agent that only ever called the tool would loop rather than fail, and the
    test would hang instead of reporting what went wrong.
    """

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        answered = any(isinstance(part, ToolReturnPart) for m in messages for part in m.parts)
        if answered:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool_name, args={}, tool_call_id="call-1")]
        )

    return FunctionModel(respond)


async def _tools_offered(spec: AgentSpec, **kwargs: Any) -> list[ToolDefinition]:
    """The tool definitions an agent built from this spec puts in front of a model."""
    seen: list[ToolDefinition] = []
    built = build_agent(spec, _model_spec(), organization_id=uuid.uuid4(), **kwargs)
    with built.agent.override(model=_seeing_model(seen)):
        await built.agent.run("hello", deps=built.deps)
    return seen


class TestWhatTheModelSees:
    @pytest.mark.anyio
    async def test_a_rename_reaches_the_model(self):
        """`search_refund_policy` is not `search_documents`, and models behave accordingly."""
        spec = AgentSpec(
            name="Refunds",
            capabilities=[
                {
                    "id": "knowledge",
                    "tool_overrides": {"search_documents": {"name": "search_refund_policy"}},
                }
            ],
        )

        offered = await _tools_offered(spec, resources={"kb_collection_names": ["kb_1"]})

        assert [tool.name for tool in offered] == ["search_refund_policy"]

    @pytest.mark.anyio
    async def test_a_reworded_description_reaches_the_model(self):
        """The highest-leverage prompt in the product, and it is per agent."""
        spec = AgentSpec(
            name="Refunds",
            capabilities=[
                {
                    "id": "knowledge",
                    "tool_overrides": {
                        "search_documents": {
                            "description": "Search the refund policy before quoting a window."
                        }
                    },
                }
            ],
        )

        offered = await _tools_offered(spec, resources={"kb_collection_names": ["kb_1"]})

        assert [tool.description for tool in offered] == [
            "Search the refund policy before quoting a window."
        ]
        assert [tool.name for tool in offered] == ["search_documents"]

    @pytest.mark.anyio
    async def test_a_renamed_tool_still_belongs_to_the_capability_that_owns_it(self):
        """Losing `capability_id` would take the approval gate down with it."""
        spec = AgentSpec(
            name="Refunds",
            capabilities=[
                {
                    "id": "knowledge",
                    "tool_overrides": {"search_documents": {"name": "search_refund_policy"}},
                }
            ],
        )

        offered = await _tools_offered(spec, resources={"kb_collection_names": ["kb_1"]})

        assert [tool.capability_id for tool in offered] == ["knowledge"]

    @pytest.mark.anyio
    async def test_an_override_cannot_reach_another_capabilitys_tool(self):
        """A rename is scoped to the capability whose binding stated it.

        The same rule the approval gate follows for a tool nobody owns: a tool
        another capability - or an MCP server - happens to expose is not this
        binding's to rewrite, and a mechanism that matched on name alone would
        change what one agent's model sees because of what a different
        capability declared. Publishing refuses a key like this outright; at
        build time it must simply do nothing.
        """
        spec = AgentSpec(
            name="Analyst",
            capabilities=[
                {"id": "knowledge", "tool_overrides": {"create_chart": {"name": "draw"}}},
                {"id": "charts"},
            ],
        )

        offered = await _tools_offered(spec, resources={"kb_collection_names": ["kb_1"]})

        assert {tool.name: tool.capability_id for tool in offered} == {
            "search_documents": "knowledge",
            "create_chart": "charts",
        }

    @pytest.mark.anyio
    async def test_a_capability_that_resolves_its_toolset_per_run_is_refused(self):
        """A rename that silently did not apply is the whole bug, restated.

        The gate would be watching for a name the model never calls. Better to
        fail while the agent is being assembled than to run one that is wrong in
        exactly the way this feature exists to prevent.
        """

        @dataclass
        class _PerRun(AbstractCapability[Any]):
            def get_toolset(self):
                return lambda ctx: FunctionToolset()

        overridden = ToolOverrides(wrapped=_PerRun(id="per_run"), names={"a": "b"})

        with pytest.raises(TypeError, match="per run"):
            overridden.get_toolset()

    def test_a_capability_with_no_toolset_has_nothing_to_rename(self):
        """The clock contributes instructions; wrapping it must stay harmless."""

        @dataclass
        class _NoTools(AbstractCapability[Any]):
            pass

        assert (
            ToolOverrides(wrapped=_NoTools(id="no_tools"), names={"a": "b"}).get_toolset() is None
        )


class TestARenamedToolIsStillGated:
    """The correctness crux: decide by id, answer with the effective name.

    `tool_approval` is keyed on a tool's stable id; `ApprovalGate` matches
    `tool_def.name`. Reading the *declared* name off the registry - which is
    what the policy did before renames existed - leaves the gate waiting for a
    tool the model never calls, and the tool it does call is precisely the
    side-effecting one somebody deliberately gated.
    """

    @staticmethod
    def _spec(name: str) -> AgentSpec:
        return AgentSpec(
            name="Clerk",
            capabilities=[
                {
                    "id": SIDE_EFFECTING,
                    "approval": "required",
                    "tool_overrides": {SIDE_EFFECTING_TOOL: {"name": name}},
                }
            ],
        )

    def test_the_gate_is_told_the_name_the_model_will_call(self, side_effecting_capability):
        assert approval_required_tools(self._spec("dispatch_the_order")) == frozenset(
            {"dispatch_the_order"}
        )

    @pytest.mark.anyio
    async def test_the_renamed_tool_parks_instead_of_running(self, side_effecting_capability):
        """End to end: the model calls the new name and nothing happens without a human."""
        run_id = uuid.uuid4()
        channel = ApprovalChannel(
            approvals=MagicMock(request=AsyncMock(return_value=MagicMock(id=uuid.uuid4()))),
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=run_id,
        )
        built = build_agent(
            self._spec("dispatch_the_order"),
            _model_spec(),
            organization_id=uuid.uuid4(),
            run_id=run_id,
            request_approval=channel,
        )

        with built.agent.override(model=_calling_model("dispatch_the_order")):
            result = await built.agent.run("go", deps=built.deps)

        assert isinstance(result.output, DeferredToolRequests)
        assert [call.tool_name for call in result.output.approvals] == ["dispatch_the_order"]
        # The capability instance is behind the override wrapper; what matters is
        # that its tool never ran.
        assert built.capabilities[0].wrapped.ran == []

    def test_an_ungated_tool_is_not_gated_by_being_renamed(self, side_effecting_capability):
        """A rename changes presentation, never the decision attached to the id."""
        spec = AgentSpec(
            name="Clerk",
            capabilities=[
                {
                    "id": SIDE_EFFECTING,
                    "tool_approval": {SIDE_EFFECTING_TOOL: "never"},
                    "tool_overrides": {SIDE_EFFECTING_TOOL: {"name": "dispatch_the_order"}},
                }
            ],
        )

        assert approval_required_tools(spec) == frozenset()


class TestSpecsPublishedBeforeThisExisted:
    """A stored spec must keep producing the agent it produced yesterday."""

    def test_a_spec_with_no_overrides_is_unchanged(self):
        spec = AgentSpec.model_validate(
            {
                "spec_version": 3,
                "name": "Support",
                "capabilities": [{"id": "knowledge", "config": {"default_top_k": 8}}],
            }
        )

        assert spec.capabilities[0].tool_overrides == {}
        assert spec.capabilities[0].config == {"default_top_k": 8}

    @pytest.mark.anyio
    async def test_a_version_3_knowledge_rename_still_reaches_the_model(self):
        """`knowledge` invented per-agent renaming for itself, in its own config.

        Those keys are gone, and a Pydantic model ignores what it does not
        declare - so without the fold, every agent published against version 3
        would quietly lose its rename and start offering a tool its instructions
        never mention.
        """
        spec = AgentSpec.model_validate(
            {
                "spec_version": 3,
                "name": "Orders",
                "capabilities": [
                    {
                        "id": "knowledge",
                        "config": {
                            "default_top_k": 8,
                            "tool_name": "search_orders",
                            "tool_description": "Search the order archive.",
                        },
                    }
                ],
            }
        )

        offered = await _tools_offered(spec, resources={"kb_collection_names": ["kb_1"]})

        assert [(tool.name, tool.description) for tool in offered] == [
            ("search_orders", "Search the order archive.")
        ]

    def test_the_old_keys_are_rewritten_rather_than_kept_alongside(self):
        """Two ways to rename one tool is the arrangement this replaced."""
        spec = AgentSpec.model_validate(
            {
                "name": "Orders",
                "capabilities": [{"id": "knowledge", "config": {"tool_name": "search_orders"}}],
            }
        )
        binding = spec.capabilities[0]

        assert binding.config == {}
        assert binding.tool_overrides["search_documents"].name == "search_orders"
        assert "tool_name" not in spec.to_yaml()

    def test_an_explicit_override_wins_over_the_legacy_key(self):
        """Re-reading an already-migrated spec must not undo the migration."""
        spec = AgentSpec.model_validate(
            {
                "name": "Orders",
                "capabilities": [
                    {
                        "id": "knowledge",
                        "config": {"tool_name": "stale"},
                        "tool_overrides": {"search_documents": {"name": "current"}},
                    }
                ],
            }
        )

        assert spec.capabilities[0].tool_overrides["search_documents"].name == "current"

    def test_the_fold_only_applies_to_the_capability_that_had_it(self):
        """No other capability ever carried these keys; none should gain them."""
        spec = AgentSpec.model_validate(
            {
                "name": "x",
                "capabilities": [{"id": "web_research", "config": {"tool_name": "look_it_up"}}],
            }
        )

        assert spec.capabilities[0].tool_overrides == {}

    def test_a_binding_that_is_not_a_mapping_is_left_to_pydantic(self):
        """The before-validator must not swallow a malformed hand-written spec."""
        with pytest.raises(ValueError):
            AgentSpec.from_yaml("name: x\ncapabilities: [[not, a, mapping]]\n")


class TestSerialisation:
    """What a saved spec holds, which is what comes back on the next open."""

    def test_a_field_nobody_set_is_absent_rather_than_null(self):
        """`null` is not "no name", but it reads as a value to anything asking.

        The Builder marks a field overridden when the binding has one for it.
        A `null` written on save came back looking like an override nobody
        could clear - the reset button stayed on a field already reset.
        """
        spec = AgentSpec.model_validate(
            {
                "name": "S",
                "capabilities": [
                    {"id": "knowledge", "tool_overrides": {"search_documents": {"name": "s_o"}}}
                ],
            }
        )

        stored = spec.model_dump(mode="json")["capabilities"][0]["tool_overrides"]

        assert stored == {"search_documents": {"name": "s_o"}}

    def test_both_fields_survive_when_both_were_set(self):
        spec = AgentSpec.model_validate(
            {
                "name": "S",
                "capabilities": [
                    {
                        "id": "knowledge",
                        "tool_overrides": {"search_documents": {"name": "s", "description": "d"}},
                    }
                ],
            }
        )

        stored = spec.model_dump(mode="json")["capabilities"][0]["tool_overrides"]

        assert stored == {"search_documents": {"name": "s", "description": "d"}}

    def test_a_stored_null_still_loads_as_no_override(self):
        """Specs saved before this behaved differently; they must still open."""
        spec = AgentSpec.model_validate(
            {
                "name": "S",
                "capabilities": [
                    {
                        "id": "knowledge",
                        "tool_overrides": {"search_documents": {"name": "s", "description": None}},
                    }
                ],
            }
        )

        assert spec.capabilities[0].tool_overrides["search_documents"].description is None
        assert spec.model_dump(mode="json")["capabilities"][0]["tool_overrides"] == {
            "search_documents": {"name": "s"}
        }
