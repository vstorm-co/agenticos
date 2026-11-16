"""Adding to a run while it works (#2087): the words reach the model at its next request."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app.agents.steering import Steering, SteeringInbox

pytestmark = pytest.mark.anyio


@dataclass
class _Deps:
    steering: SteeringInbox | None


def _said(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]


async def test_a_correction_sent_mid_run_is_read_at_the_next_step_and_kept():
    """The tool stands in for the person: it is mid-run when the correction arrives."""
    applied = AsyncMock()
    inbox = SteeringInbox(on_applied=applied)
    seen: list[list[str]] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(_said(messages))
        if len(seen) == 1:
            return ModelResponse(parts=[ToolCallPart(tool_name="look_up", args={})])
        return ModelResponse(parts=[TextPart(content="Using the EU numbers.")])

    agent = Agent(FunctionModel(model), deps_type=_Deps, capabilities=[Steering()])

    @agent.tool
    def look_up(ctx: RunContext[_Deps]) -> str:
        inbox.add("use the EU numbers")
        return "US: 10, EU: 12"

    result = await agent.run("what are the numbers", deps=_Deps(steering=inbox))

    assert not any("EU numbers" in text for text in seen[0])
    assert any("use the EU numbers" in text for text in seen[1])
    # In the history too, so the transcript and any later request keep it.
    assert any("use the EU numbers" in text for text in _said(result.all_messages()))
    applied.assert_awaited_once_with("use the EU numbers")
    assert inbox.unapplied() == []


async def test_what_arrives_after_the_last_request_stays_unapplied():
    inbox = SteeringInbox()

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        inbox.add("too late")
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(FunctionModel(model), deps_type=_Deps, capabilities=[Steering()])
    await agent.run("go", deps=_Deps(steering=inbox))

    assert inbox.unapplied() == ["too late"]


async def test_a_run_nobody_can_steer_is_untouched():
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=" | ".join(_said(messages)))])

    agent = Agent(FunctionModel(model), deps_type=_Deps, capabilities=[Steering()])
    result = await agent.run("go", deps=_Deps(steering=None))

    assert result.output == "go"


def test_take_hands_each_message_over_once():
    inbox = SteeringInbox()
    inbox.add("a")
    inbox.add("b")

    assert [steer.text for steer in inbox.take()] == ["a", "b"]
    assert inbox.take() == []


def _request(messages: list[ModelMessage]) -> ModelRequestContext:
    return ModelRequestContext(
        model=TestModel(),
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


async def test_a_resumed_provider_turn_is_not_written_into():
    """Its tail is a suspended response echoed back verbatim; adding to it corrupts it."""
    inbox = SteeringInbox()
    inbox.add("hold on")
    tail = ModelResponse(parts=[TextPart(content="half")])
    ctx = MagicMock(deps=_Deps(steering=inbox), messages=[tail])
    request = _request([tail])

    assert await Steering().before_model_request(ctx, request) is request
    assert inbox.unapplied() == ["hold on"]


async def test_the_request_carries_it_even_where_the_history_tail_differs():
    inbox = SteeringInbox()
    inbox.add("shorter, please")
    history_tail = ModelResponse(parts=[TextPart(content="draft")])
    ctx = MagicMock(deps=_Deps(steering=inbox), messages=[history_tail])

    sent = await Steering().before_model_request(
        ctx, _request([ModelRequest(parts=[UserPromptPart(content="write it")])])
    )

    assert "shorter, please" in _said(sent.messages)[-1]
    assert ctx.messages == [history_tail]


@pytest.mark.security
@pytest.mark.parametrize("blocked", [False, True], ids=["redacted", "blocked"])
async def test_a_steer_meets_the_agents_input_guardrail(blocked: bool):
    """Review on #2062: a steer joins from the second request on, past where the
    harness's input edge looks, and reached the provider as typed."""
    from app.agents.capabilities.guardrails import (
        GuardrailBlocked,
        GuardrailsConfig,
        input_screen,
    )

    config = (
        GuardrailsConfig(blocked_keywords_in="salary")
        if blocked
        else GuardrailsConfig(redact_secrets_in=True)
    )
    inbox = SteeringInbox(screen=input_screen(config))
    seen: list[list[str]] = []
    steer = "her salary is 9000" if blocked else "use key sk-ant-api03-" + "x" * 90

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(_said(messages))
        if len(seen) == 1:
            return ModelResponse(parts=[ToolCallPart(tool_name="look_up", args={})])
        return ModelResponse(parts=[TextPart(content="done")])

    agent = Agent(FunctionModel(model), deps_type=_Deps, capabilities=[Steering()])

    @agent.tool
    def look_up(ctx: RunContext[_Deps]) -> str:
        inbox.add(steer)
        return "ok"

    if blocked:
        with pytest.raises(GuardrailBlocked):
            await agent.run("go", deps=_Deps(steering=inbox))
        assert len(seen) == 1
    else:
        await agent.run("go", deps=_Deps(steering=inbox))
        assert not any(steer in text for text in seen[1])
        assert any("Added by the person" in text for text in seen[1])


def test_a_spec_s_steers_are_screened_by_its_own_input_guardrail():
    """The runner reads the spec's guardrails binding: on, off, or absent."""
    from app.agents.spec import AgentSpec, CapabilityBindingSpec
    from app.services.agent_runner import input_screen_for

    guarded = AgentSpec(
        name="Ops",
        capabilities=[
            CapabilityBindingSpec(id="guardrails", config={"blocked_keywords_in": "salary"})
        ],
    )
    switched_off = AgentSpec(
        name="Ops",
        capabilities=[
            CapabilityBindingSpec(
                id="guardrails", enabled=False, config={"blocked_keywords_in": "salary"}
            )
        ],
    )

    assert input_screen_for(guarded) is not None
    assert input_screen_for(switched_off) is None
    assert input_screen_for(AgentSpec(name="Ops")) is None


def test_parallel_coding_listeners_route_corrections_without_consuming_each_others() -> None:
    inbox = SteeringInbox()
    with inbox.listen("api") as first, inbox.listen("web") as second:
        inbox.add("Use the EU numbers")
        assert first.unapplied() == second.unapplied() == []
        inbox.add("[session:api] Use Python")
        assert [item.text for item in first.take()] == ["Use Python"]
        assert second.unapplied() == []
        inbox.add("[session:web] Use TypeScript")
        assert second.unapplied() == ["Use TypeScript"]
        second.take()
    inbox.add("After both finished")
    assert first.unapplied() == second.unapplied() == []
    assert len(inbox.unapplied()) == 4


def test_one_coding_listener_gets_unaddressed_and_buffered_corrections() -> None:
    inbox = SteeringInbox()
    inbox.add("Buffered")
    inbox.add("[session:api] Already addressed")
    inbox.add("[session:web] For web only")
    inbox.add("[session:invalid")
    inbox.add("[session:api]")
    with inbox.listen("api") as listener:
        assert listener.unapplied() == [
            "Buffered",
            "Already addressed",
            "[session:invalid",
            "[session:api]",
        ]
        listener.take()
        inbox.add("Continue")
        assert listener.unapplied() == ["Continue"]


def test_a_second_parallel_listener_does_not_take_an_unaddressed_buffer() -> None:
    inbox = SteeringInbox()
    inbox.add("For the parent")
    with inbox.listen("api"), inbox.listen("web") as second:
        assert second.unapplied() == []
