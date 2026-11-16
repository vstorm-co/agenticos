"""The `ask_user` capability through a real agent run (#2064).

The harness owns the tool; what is ours is reaching the run's own question
channel from inside the call, and answering as a decline where there is none.
"""

import json

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import CallDeferred
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults
from pydantic_ai_harness.ask_user import (
    DECLINED,
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
    ask_user_result,
)

from app.agents.ask_user import park_the_question
from app.agents.capabilities._registry import CapabilityBinding, build, load_builtins
from app.agents.capabilities.ask_user import ASK_USER_CAPABILITY_ID
from app.agents.capabilities.ask_user._capability import through_the_surface
from app.agents.deps import AgentDeps
from app.services.agent_runner import PausedRunState, _classify_output

pytestmark = pytest.mark.anyio

QUESTIONS = [
    {
        "header": "Audience",
        "question": "Who will use it?",
        "options": [{"label": "Everyone"}, {"label": "My team"}],
    }
]


def _asks_then_reports(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    returns = [
        part
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    ]
    if not returns:
        return ModelResponse(
            parts=[ToolCallPart("ask_user_question", {"questions": QUESTIONS}, tool_call_id="q1")]
        )
    return ModelResponse(parts=[TextPart(json.dumps(returns[0].content))])


def _agent() -> Agent[AgentDeps, str | DeferredToolRequests]:
    load_builtins()
    capabilities = build([CapabilityBinding(capability_id=ASK_USER_CAPABILITY_ID)])
    return Agent(
        FunctionModel(_asks_then_reports),
        deps_type=AgentDeps,
        capabilities=capabilities,
        output_type=[str, DeferredToolRequests],
    )


async def test_the_question_reaches_the_runs_channel_and_the_picks_reach_the_model() -> None:
    asked: list[AskUserRequest] = []

    async def channel(request: AskUserRequest) -> AskUserResponse:
        asked.append(request)
        return AskUserResponse(answers=(AskUserAnswer(header="Audience", selected=("My team",)),))

    result = await _agent().run("Build me a helper", deps=AgentDeps(ask_questions=channel))

    assert [question.header for question in asked[0].questions] == ["Audience"]
    assert json.loads(result.output) == {"Audience": ["My team"]}


async def test_with_nobody_to_ask_the_model_is_told_the_user_declined() -> None:
    result = await _agent().run("Build me a helper", deps=AgentDeps())

    assert json.loads(result.output) == DECLINED


async def test_the_answerer_outside_a_call_has_no_channel() -> None:
    response = await through_the_surface(AskUserRequest(questions=()))

    assert response == AskUserResponse(cancelled=True)


async def test_a_question_left_unanswered_parks_and_its_answer_continues_the_run() -> None:
    """The mechanism a run parked on a question rests on (#2064): the surface
    raises `CallDeferred`, the run ends waiting on the call, and the answer is
    handed back as that call's result - which the model reads as if answered live."""

    async def gone(request: AskUserRequest) -> AskUserResponse:
        raise CallDeferred

    agent = _agent()
    parked = await agent.run("Build me a helper", deps=AgentDeps(ask_questions=gone))

    assert isinstance(parked.output, DeferredToolRequests)
    [call] = parked.output.calls
    answer = ask_user_result(
        AskUserRequest.from_tool_call(call),
        AskUserResponse(answers=(AskUserAnswer(header="Audience", selected=("Everyone",)),)),
    )
    resumed = await agent.run(
        message_history=parked.all_messages(),
        deferred_tool_results=DeferredToolResults(calls={call.tool_call_id: answer}),
        deps=AgentDeps(),
    )

    assert json.loads(resumed.output) == {"Audience": ["Everyone"]}


async def test_saved_replies_preserve_earlier_tools_across_repeated_questions() -> None:
    """Each continuation rebuilds the agent from JSON, as a different worker does."""
    actions: list[str] = []

    def decide(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returned = {
            part.tool_call_id: part.content
            for message in messages
            for part in getattr(message, "parts", [])
            if isinstance(part, ToolReturnPart)
        }
        if "action" not in returned:
            return ModelResponse(parts=[ToolCallPart("record_action", {}, tool_call_id="action")])
        for call_id in ("question-1", "question-2"):
            if call_id not in returned:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "ask_user_question", {"questions": QUESTIONS}, tool_call_id=call_id
                        )
                    ]
                )
        return ModelResponse(parts=[TextPart(json.dumps(returned))])

    def record_action() -> str:
        actions.append("performed")
        return "done"

    def fresh() -> Agent[AgentDeps, str | DeferredToolRequests]:
        load_builtins()
        return Agent(
            FunctionModel(decide),
            deps_type=AgentDeps,
            tools=[record_action],
            capabilities=build([CapabilityBinding(capability_id=ASK_USER_CAPABILITY_ID)]),
            output_type=[str, DeferredToolRequests],
        )

    parked = await fresh().run("Plan the work", deps=AgentDeps(ask_questions=park_the_question))
    for index, label in enumerate(("Everyone", "My team"), start=1):
        assert isinstance(parked.output, DeferredToolRequests)
        [call] = parked.output.calls
        assert call.tool_call_id == f"question-{index}"
        _, _, _, state = _classify_output(parked, parked={})
        assert state is not None
        state.question_results = {
            call.tool_call_id: ask_user_result(
                AskUserRequest.from_tool_call(call),
                AskUserResponse(answers=(AskUserAnswer(header="Audience", selected=(label,)),)),
            )
        }
        restored = PausedRunState.model_validate_json(state.model_dump_json())
        parked = await fresh().run(
            message_history=ModelMessagesTypeAdapter.validate_python(restored.messages),
            deferred_tool_results=DeferredToolResults(calls=restored.question_results),
            deps=AgentDeps(ask_questions=park_the_question),
        )

    assert json.loads(parked.output) == {
        "action": "done",
        "question-1": {"Audience": ["Everyone"]},
        "question-2": {"Audience": ["My team"]},
    }
    assert actions == ["performed"]
