"""Voice assembly: what a call can and cannot carry over from an agent (#54)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import Capability, HandleDeferredToolCalls, ToolSearch
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.realtime.openai import OpenAIRealtimeModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import load_builtins
from app.agents.capabilities.clock import Clock
from app.agents.capabilities.skills import Skills
from app.agents.factory import BuiltAgent, build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SubagentRef
from app.agents.voice import (
    SPOKEN_STYLE,
    VoiceOptions,
    WithoutApprovalTools,
    thinking_effort,
    voice_configured,
    voice_instructions,
    voice_skills,
    voice_unavailable,
    without_voice_unavailable,
)
from app.core.secret_kinds import ApiKeySecret

_REALTIME = OpenAIRealtimeModel("gpt-realtime", provider=OpenAIProvider(api_key="sk-dummy"))


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _spec(*ids: str, enabled: bool = True) -> AgentSpec:
    return AgentSpec(
        name="a",
        capabilities=[CapabilityBindingSpec(id=cap, enabled=enabled) for cap in ids],
    )


def test_the_builder_lists_what_a_call_cannot_use():
    assert voice_unavailable(_spec("clock", "sandbox", "browser_use")) == ["browser_use", "sandbox"]


def test_a_disabled_binding_is_not_listed():
    assert voice_unavailable(_spec("sandbox", enabled=False)) == []


def test_stripping_removes_the_unavailable_bindings_and_every_delegate():
    spec = _spec("clock", "sandbox", "subagents").model_copy(
        update={"subagents": [SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())]}
    )

    stripped = without_voice_unavailable(spec)

    assert [b.id for b in stripped.capabilities] == ["clock"]
    assert stripped.subagents == []
    assert spec.subagents  # the original is untouched


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


async def _deny(ctx, requests):
    return requests.build_results(approve_all=False)


async def _resolved(built: BuiltAgent) -> tuple[list[str], str]:
    """What a session would be given. `_resolve_realtime_session` is private: it is
    the only offline view of the tools and instructions a call connects with."""
    async with built.agent._resolve_realtime_session(_REALTIME, deps=built.deps) as resolved:
        return [
            t.name for t in resolved.model_request_parameters.function_tools
        ], resolved.instructions or ""


def _voice_agent(spec: AgentSpec, **kwargs: object) -> BuiltAgent:
    return build_agent(
        spec,
        _model_spec(),
        organization_id=uuid4(),
        voice=VoiceOptions(on_deferred=_deny),
        **kwargs,
    )


@pytest.mark.anyio
async def test_a_voice_agent_reads_its_instructions_and_the_spoken_style_as_instructions():
    spec = AgentSpec(name="a", instructions="You answer refunds.")
    built = build_agent(
        spec,
        _model_spec(),
        organization_id=uuid4(),
        voice=VoiceOptions(on_deferred=_deny, voice_note="Spell names back."),
    )

    _, instructions = await _resolved(built)

    assert "You answer refunds." in instructions
    assert SPOKEN_STYLE.splitlines()[0] in instructions
    assert "Spell names back." in instructions


@pytest.mark.anyio
async def test_mcp_toolsets_are_not_deferred_in_a_call_even_with_tool_search():
    mcp = FunctionToolset()

    @mcp.tool_plain
    def crm_lookup(name: str) -> str:
        """Look a customer up."""
        return name

    spec = AgentSpec(name="a", capabilities=[CapabilityBindingSpec(id="tool_search")])
    built = _voice_agent(spec, extra_toolsets=[mcp])

    tools, _ = await _resolved(built)

    assert "crm_lookup" in tools
    assert not any(isinstance(c, ToolSearch) for c in built.capabilities)


@pytest.mark.anyio
async def test_skills_reach_a_call_as_toolless_leaves_with_their_file_tool():
    stored = [
        SimpleNamespace(
            name="refunds",
            description="How refunds work",
            content="Step 1",
            resources=[SimpleNamespace(name="tpl.md", description="t", content="x")],
        )
    ]
    adapted = voice_skills(Skills(skills=stored))
    assert adapted is not None
    agent = Agent(capabilities=[adapted])

    async with agent._resolve_realtime_session(_REALTIME) as resolved:
        built_tools = sorted(t.name for t in resolved.model_request_parameters.function_tools)

    assert built_tools == ["load_capability", "read_skill_resource"]


@pytest.mark.security
@pytest.mark.anyio
async def test_an_anonymous_call_leaves_approval_tools_out():
    gate = WithoutApprovalTools(names=frozenset({"send_email"}))
    defs = [SimpleNamespace(name="send_email"), SimpleNamespace(name="get_weather")]

    kept = await gate.prepare_tools(SimpleNamespace(), defs)

    assert [d.name for d in kept] == ["get_weather"]


def test_a_voice_agent_resolves_approvals_inline():
    built = _voice_agent(AgentSpec(name="a"))
    found: list[object] = []
    built.agent.root_capability.apply(found.append)
    assert any(isinstance(c, HandleDeferredToolCalls) for c in found)


def test_a_sandbox_binding_never_reaches_a_call():
    spec = AgentSpec(name="a", capabilities=[CapabilityBindingSpec(id="sandbox")])
    built = _voice_agent(spec)
    assert built.capabilities == []


@pytest.mark.parametrize(
    ("config", "expected"),
    [({}, True), ({"effort": "high"}, "high"), (None, None)],
)
def test_thinking_maps_to_the_realtime_setting(config, expected):
    capabilities = [] if config is None else [CapabilityBindingSpec(id="thinking", config=config)]
    assert thinking_effort(AgentSpec(name="a", capabilities=capabilities)) == expected


def test_a_pinned_language_is_spoken_unless_the_caller_asks_otherwise():
    instructions = voice_instructions("Help.", VoiceOptions(on_deferred=_deny, language="pl"))

    assert "ISO-639-1 code 'pl'" in instructions


def _stored_skill() -> SimpleNamespace:
    return SimpleNamespace(
        name="refunds", description="How refunds work", content="Step 1", resources=[]
    )


def test_a_call_carries_no_tool_search_and_skills_without_toolsets():
    clock = Clock()

    carried = voice_configured([ToolSearch(), clock, Skills(skills=[_stored_skill()])])

    assert carried[0] is clock
    leaves: list[object] = []
    carried[1].apply(leaves.append)
    assert len(carried) == 2
    assert all(
        leaf.get_toolset() is None for leaf in leaves if getattr(leaf, "defer_loading", False)
    )


def test_a_capability_loaded_up_front_keeps_its_tools():
    eager = Capability(id="eager", instructions="Always here.")

    assert voice_skills(eager) is eager
