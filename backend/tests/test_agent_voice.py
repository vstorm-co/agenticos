"""Voice assembly: what a call can and cannot carry over from an agent (#54)."""

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import anyio
import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import Capability, HandleDeferredToolCalls, ToolSearch
from pydantic_ai.messages import FunctionToolResultEvent, ModelMessage
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.realtime.codec import (
    RealtimeCodecEvent,
    RealtimeConnection,
    RealtimeInput,
    ResponseDone,
    ToolCall,
    ToolResult,
)
from pydantic_ai.realtime.lifecycle import InferredLifecycle, RealtimeFrame
from pydantic_ai.realtime.model import RealtimeModel
from pydantic_ai.realtime.openai import OpenAIRealtimeModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import get as capability_def
from app.agents.capabilities import load_builtins
from app.agents.capabilities.clock import Clock
from app.agents.capabilities.skills import Skills
from app.agents.factory import BuiltAgent, build_agent
from app.agents.mcp import NEEDS_APPROVAL
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SubagentRef
from app.agents.voice import (
    CALL_BRIEFING,
    SPOKEN_STYLE,
    UNAVAILABLE_TOOL,
    AnswerUnknownTools,
    VoiceOptions,
    WithoutApprovalTools,
    enabled_binding,
    handed_off,
    thinking_effort,
    voice_configured,
    voice_instructions,
    voice_skills,
    without_voice_unavailable,
)
from app.core.secret_kinds import ApiKeySecret
from app.services.embed_session import SUPPLIED_HEADER

_REALTIME = OpenAIRealtimeModel("gpt-realtime", provider=OpenAIProvider(api_key="sk-dummy"))


@pytest.fixture(autouse=True)
def _builtins_loaded() -> None:
    load_builtins()


def _spec(*ids: str, enabled: bool = True) -> AgentSpec:
    return AgentSpec(
        name="a",
        capabilities=[CapabilityBindingSpec(id=cap, enabled=enabled) for cap in ids],
    )


def test_a_call_hands_off_what_its_realtime_model_cannot_carry():
    spec = _spec("clock", "sandbox", "browser_use", "subagents", "background_tools", "ask_user")
    assert handed_off(spec) == ["background_tools", "browser_use", "sandbox", "subagents"]


def test_channel_lookups_are_not_offered_in_a_call():
    """A call is never made on a channel, so there is nothing for them to look up."""
    assert capability_def("channel_tools").voice == "never"


def test_next_step_buttons_are_not_offered_in_a_call():
    """A call has nowhere to show them, and reading them aloud is the habit they replace."""
    assert capability_def("follow_ups").voice == "never"


def test_a_disabled_binding_is_not_handed_off():
    assert handed_off(_spec("sandbox", enabled=False)) == []


def test_stripping_keeps_what_the_text_twin_works_with():
    """The sandbox opens and the delegates resolve for the twin; only what a call
    can never use goes."""
    spec = _spec("clock", "sandbox", "subagents", "channel_tools").model_copy(
        update={"subagents": [SubagentRef(agent_id=uuid4(), agent_version_id=uuid4())]}
    )

    stripped = without_voice_unavailable(spec)

    assert [b.id for b in stripped.capabilities] == ["clock", "sandbox", "subagents"]
    assert stripped.subagents == spec.subagents


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
    defs = [
        SimpleNamespace(name="send_email", capability_id="email", metadata=None),
        SimpleNamespace(name="get_weather", capability_id="weather", metadata=None),
    ]

    kept = await gate.prepare_tools(SimpleNamespace(), defs)

    assert [d.name for d in kept] == ["get_weather"]


@pytest.mark.security
@pytest.mark.anyio
async def test_an_anonymous_call_leaves_out_an_mcp_tool_its_binding_gates():
    """An MCP binding's approval is stamped on the tool (#2060), not named in the
    spec's capability gates - a visitor must not be offered it either."""
    gate = WithoutApprovalTools(names=frozenset())
    defs = [
        SimpleNamespace(name="crm_update", capability_id=None, metadata={NEEDS_APPROVAL: True}),
        SimpleNamespace(name="crm_read", capability_id=None, metadata={NEEDS_APPROVAL: False}),
        # A capability's tool is not released or gated by metadata.
        SimpleNamespace(name="clock_now", capability_id="clock", metadata={NEEDS_APPROVAL: True}),
    ]

    kept = await gate.prepare_tools(SimpleNamespace(), defs)

    assert [d.name for d in kept] == ["crm_read", "clock_now"]


def test_a_voice_agent_resolves_approvals_inline():
    built = _voice_agent(AgentSpec(name="a"))
    found: list[object] = []
    built.agent.root_capability.apply(found.append)
    assert any(isinstance(c, HandleDeferredToolCalls) for c in found)


def _capabilities_of(built: BuiltAgent) -> list[object]:
    found: list[object] = []
    built.agent.root_capability.apply(found.append)
    return found


@pytest.mark.security
@pytest.mark.parametrize("anonymous", [False, True])
def test_a_text_agent_working_for_a_call_settles_approvals_with_the_caller(anonymous):
    """The call's text twin and its delegates: nobody resumes a call, so nothing parks."""
    spec = AgentSpec(name="a", capabilities=[CapabilityBindingSpec(id="sandbox")])
    built = build_agent(
        spec,
        _model_spec(),
        organization_id=uuid4(),
        answering_call=VoiceOptions(on_deferred=_deny, anonymous=anonymous),
    )

    found = _capabilities_of(built)
    assert any(isinstance(c, HandleDeferredToolCalls) for c in found)
    assert any(isinstance(c, WithoutApprovalTools) for c in found) is anonymous
    # A text run in every other respect: its sandbox, and no realtime-only stand-ins.
    assert len(built.capabilities) == 1
    assert not any(isinstance(c, AnswerUnknownTools) for c in found)
    assert built.agent._system_prompts


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


def test_a_binding_counts_only_while_it_is_switched_on():
    """The one lookup the call's thinking setting and its transcript guard share."""
    on = CapabilityBindingSpec(id="guardrails", config={})
    off = CapabilityBindingSpec(id="thinking", enabled=False, config={})
    spec = AgentSpec(name="a", capabilities=[on, off])

    assert enabled_binding(spec, "guardrails") == on
    assert enabled_binding(spec, "thinking") is None
    assert enabled_binding(spec, "clock") is None


def test_a_pinned_language_is_spoken_unless_the_caller_asks_otherwise():
    instructions = voice_instructions("Help.", VoiceOptions(on_deferred=_deny, language="pl"))

    assert "ISO-639-1 code 'pl'" in instructions


def test_an_embeds_briefing_reaches_the_call_before_the_agents_note():
    """What a text turn on that embed would prepend, so a call knows the same about the visitor."""
    instructions = voice_instructions(
        "Help.",
        VoiceOptions(
            on_deferred=_deny,
            briefing="[Context for this placement: pricing page]",
            voice_note="Be brief.",
        ),
    )

    assert "[Context for this placement: pricing page]" in instructions
    assert instructions.index("pricing page") < instructions.index("Be brief.")


def test_a_call_is_told_the_briefing_is_about_the_caller_and_answered_from():
    """Regression: a hosted page's `order: 123` was in the call's instructions, and
    gpt-realtime still told the caller it had no access to their order number.

    In text the block sits beside the visitor's own words; in a call it is a
    detached paragraph about "the visitor", which the model did not connect with
    the person speaking. The call has to say who the notes are about, that a
    value in them is the answer, and still that they are not instructions.
    """
    briefing = f"{SUPPLIED_HEADER}\norder: 123"
    instructions = voice_instructions("Help.", VoiceOptions(on_deferred=_deny, briefing=briefing))

    lead = instructions[: instructions.index(briefing)]
    assert "the person you are speaking with" in lead
    assert "answer from these notes" in lead
    assert "not instructions" in lead
    assert lead.endswith(CALL_BRIEFING + "\n")


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


def test_a_visitor_is_never_asked_to_approve_out_loud():
    """Regression: told how to ask for approval, gpt-realtime asked a widget
    visitor "Are we good to go?" - though a visitor's call carries no gated tool."""
    visitor = voice_instructions("Help.", VoiceOptions(on_deferred=_deny, anonymous=True))
    member = voice_instructions("Help.", VoiceOptions(on_deferred=_deny))

    assert "approv" not in visitor
    assert "If you cannot do something on this call, say so plainly" in visitor
    assert "Never say an action is done until its result arrives." in visitor
    assert "When a tool needs approval, say that you are asking for it and wait." in member


class _ScriptedConnection(RealtimeConnection):
    """A provider that calls each named tool in turn, one response each, and then waits."""

    def __init__(self, calls: Sequence[str]) -> None:
        self._calls = calls
        self.results: list[str] = []
        self._send_result, self._result_sent = anyio.create_memory_object_stream[str](10)

    async def send(self, content: RealtimeInput) -> None:
        if isinstance(content, ToolResult):
            self.results.append(content.output)
            await self._send_result.send(content.output)

    async def _events(self) -> AsyncIterator[RealtimeCodecEvent]:
        for index, name in enumerate(self._calls):
            yield ToolCall(f"call-{index}", tool_name=name, args="{}")
            yield ResponseDone()
            await self._result_sent.receive()
        await anyio.sleep_forever()

    def frames(self) -> AsyncIterator[RealtimeFrame]:
        return InferredLifecycle().frames(self._events())


class _ScriptedRealtime(RealtimeModel):
    def __init__(self, calls: Sequence[str]) -> None:
        super().__init__()
        self.connection = _ScriptedConnection(calls)
        self.offered: list[str] = []

    @property
    def model_name(self) -> str:
        return "scripted"

    @property
    def system(self) -> str:
        return "scripted"

    @asynccontextmanager
    async def connect(
        self,
        *,
        messages: Sequence[ModelMessage],
        model_settings: object,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[RealtimeConnection]:
        self.offered = [tool.name for tool in model_request_parameters.function_tools]
        yield self.connection


@pytest.mark.anyio
async def test_a_call_answers_a_tool_it_does_not_have_and_carries_on():
    """Regression: a visitor asked to open a page, gpt-realtime called `web_fetch` -
    left out of a visitor's session - twice, and the second unknown name raised
    `UnexpectedModelBehavior` out of the session and ended the call."""
    tools = FunctionToolset()

    @tools.tool_plain
    def get_weather() -> str:
        """The weather."""
        return "sunny"

    built = build_agent(
        AgentSpec(name="a"),
        _model_spec(),
        organization_id=uuid4(),
        voice=VoiceOptions(on_deferred=_deny, anonymous=True),
        extra_toolsets=[tools],
    )
    model = _ScriptedRealtime(["web_fetch", "web_fetch", "get_weather"])
    settled: list[FunctionToolResultEvent] = []

    async with built.agent.realtime(model, deps=built.deps).session() as session:
        with anyio.fail_after(5):
            async for event in session:
                if isinstance(event, FunctionToolResultEvent):
                    settled.append(event)
                if len(settled) == 3:
                    break

    refused, answered = model.connection.results[:2], model.connection.results[2]
    assert [json.loads(output) for output in refused] == [
        {"error": UNAVAILABLE_TOOL.format(name="web_fetch")}
    ] * 2
    assert answered == "sunny"
    assert [event.part.outcome for event in settled] == ["failed", "failed", "success"]
    assert "web_fetch" not in model.offered
